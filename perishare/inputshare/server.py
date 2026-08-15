"""Servidor de entrada: captura teclado/mouse locais e envia ao cliente.

Roda na máquina que tem o teclado e o mouse físicos. O atalho configurado
(padrão Ctrl+Alt+F12) alterna o controle entre a máquina local e a remota.
Em modo remoto os eventos locais são suprimidos (quando o sistema permite)
e o cursor fica "ancorado" no centro da tela: cada movimento vira um delta
enviado ao cliente e o cursor é reposicionado na âncora — assim o controle
funciona entre telas de resoluções diferentes.
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
import time

from .. import netmsg
from ..security import HandshakeError, make_cipher, server_handshake
from ..service import Service
from .events import button_to_wire, key_to_wire

log = logging.getLogger("perishare.input.server")

_HEARTBEAT_INTERVAL = 2.0


class InputServer(Service):
    name = "input-server"

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self._srv_sock: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._cipher = None
        self._conn_lock = threading.Lock()
        self._send_q: queue.Queue = queue.Queue(maxsize=1024)
        self._last_send = 0.0

        self._remote = False
        self._toggle_requested = threading.Event()
        self._force_local = False

        self._kb_listener = None
        self._mouse_listener = None
        self._hotkey = None
        self._anchor: tuple[int, int] | None = None
        self._mouse_ctl = None

        # Teclas/botões atualmente pressionados que foram encaminhados ao
        # cliente; usados para soltar tudo ao alternar de volta para local.
        self._down_keys: set[tuple] = set()
        self._down_buttons: set[str] = set()

    # ------------------------------------------------------------------ vida
    def start(self) -> None:
        self._cfg.require_secret()
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            raise RuntimeError(
                "Não foi possível inicializar a captura de entrada "
                f"({exc}). No Linux é necessária uma sessão gráfica X11 "
                "(em Wayland o pynput não captura eventos globais)."
            ) from exc
        try:
            keyboard.HotKey.parse(self._cfg.toggle_hotkey)
        except ValueError as exc:
            raise RuntimeError(
                f"toggle_hotkey inválido na configuração: {self._cfg.toggle_hotkey!r} ({exc})"
            ) from exc

        self._mouse_ctl = mouse.Controller()
        self._srv_sock = socket.create_server(
            (self._cfg.input_listen_host, self._cfg.input_port)
        )
        self._srv_sock.settimeout(1.0)
        self._running.set()
        self._spawn(self._accept_loop, "input-accept")
        self._spawn(self._send_loop, "input-send")
        self._spawn(self._main_loop, "input-main")
        log.info(
            "Servidor de entrada escutando em %s:%d. Atalho para alternar: %s",
            self._cfg.input_listen_host,
            self._cfg.input_port,
            self._cfg.toggle_hotkey,
        )

    def stop(self) -> None:
        self._running.clear()
        if self._srv_sock is not None:
            try:
                self._srv_sock.close()
            except OSError:
                pass
        self._drop_client("serviço encerrado")
        super().stop()

    # ------------------------------------------------------------------ rede
    def _accept_loop(self) -> None:
        while self._running.is_set():
            try:
                conn, addr = self._srv_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(10)
                session_key = server_handshake(conn, self._cfg.secret_bytes)
                cipher = make_cipher(session_key, is_server=True, enabled=self._cfg.encrypt)
                conn.settimeout(None)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except (HandshakeError, OSError) as exc:
                log.warning("Conexão de %s rejeitada: %s", addr, exc)
                conn.close()
                continue
            except RuntimeError as exc:
                log.error("%s", exc)
                conn.close()
                continue
            with self._conn_lock:
                old = self._conn
                self._conn, self._cipher = conn, cipher
            if old is not None:
                try:
                    old.close()
                except OSError:
                    pass
            log.info("Cliente conectado: %s:%d", addr[0], addr[1])
            threading.Thread(
                target=self._conn_reader, args=(conn,), name="input-reader", daemon=True
            ).start()

    def _conn_reader(self, conn: socket.socket) -> None:
        # O cliente não envia dados; este recv serve para detectar desconexão.
        conn.settimeout(1.0)
        while self._running.is_set():
            try:
                if not conn.recv(4096):
                    break
            except socket.timeout:
                continue
            except OSError:
                break
        with self._conn_lock:
            still_current = self._conn is conn
        if still_current:
            self._drop_client("cliente desconectou")

    def _drop_client(self, reason: str) -> None:
        with self._conn_lock:
            conn, self._conn, self._cipher = self._conn, None, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
            log.info("Conexão encerrada (%s).", reason)
        self._down_keys.clear()
        self._down_buttons.clear()
        if self._remote:
            # Sem cliente não podemos ficar com a entrada local suprimida.
            self._force_local = True
            self._toggle_requested.set()

    def _enqueue(self, msg: dict) -> None:
        try:
            self._send_q.put_nowait(msg)
        except queue.Full:
            try:
                self._send_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._send_q.put_nowait(msg)
            except queue.Full:
                pass

    def _send_loop(self) -> None:
        while self._running.is_set():
            try:
                msg = self._send_q.get(timeout=0.2)
            except queue.Empty:
                if time.monotonic() - self._last_send > _HEARTBEAT_INTERVAL:
                    self._transmit({"t": "ping"})
                continue
            self._transmit(msg)

    def _transmit(self, msg: dict) -> None:
        with self._conn_lock:
            conn, cipher = self._conn, self._cipher
        if conn is None:
            return
        try:
            netmsg.send_json(conn, msg, cipher)
            self._last_send = time.monotonic()
        except OSError:
            self._drop_client("erro de envio")

    def _has_client(self) -> bool:
        with self._conn_lock:
            return self._conn is not None

    # ------------------------------------------------------- modo e listeners
    def _main_loop(self) -> None:
        self._build_listeners()
        while self._running.is_set():
            if self._toggle_requested.wait(timeout=0.2):
                self._toggle_requested.clear()
                self._apply_toggle()
        self._stop_listeners()

    def _request_toggle(self) -> None:
        self._toggle_requested.set()

    def _apply_toggle(self) -> None:
        if self._remote or self._force_local:
            self._force_local = False
            if self._remote:
                self._release_all_remote()
                self._remote = False
                log.info("Controle de volta nesta máquina (modo local).")
                self._rebuild_listeners()
            return
        if not self._has_client():
            log.warning("Nenhum cliente conectado; continuando em modo local.")
            return
        self._anchor = self._screen_center()
        self._warp()
        self._remote = True
        log.info(
            "Controlando a máquina remota. Pressione %s para voltar.",
            self._cfg.toggle_hotkey,
        )
        self._rebuild_listeners()

    def _release_all_remote(self) -> None:
        for kind, value in list(self._down_keys):
            self._enqueue({"t": "kb", "down": False, "key": {"kind": kind, "v": value}})
        for name in list(self._down_buttons):
            self._enqueue({"t": "mb", "b": name, "down": False})
        self._down_keys.clear()
        self._down_buttons.clear()

    def _screen_center(self) -> tuple[int, int]:
        # Sem API de tela no pynput: empurra o cursor para um canto extremo,
        # deixa o SO limitá-lo à borda e usa a posição resultante como tamanho.
        try:
            self._mouse_ctl.position = (100000, 100000)
            width, height = self._mouse_ctl.position
            if width > 1 and height > 1:
                return (width // 2, height // 2)
        except Exception:
            pass
        try:
            x, y = self._mouse_ctl.position
            return (max(1, x), max(1, y))
        except Exception:
            return (400, 300)

    def _warp(self) -> None:
        if self._anchor is None:
            return
        try:
            self._mouse_ctl.position = self._anchor
        except Exception:
            pass

    def _build_listeners(self) -> None:
        from pynput import keyboard, mouse

        self._hotkey = keyboard.HotKey(
            keyboard.HotKey.parse(self._cfg.toggle_hotkey), self._request_toggle
        )
        suppress = self._remote
        self._kb_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release, suppress=suppress
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
            suppress=suppress,
        )
        try:
            self._kb_listener.start()
            self._mouse_listener.start()
            self._kb_listener.wait()
            self._mouse_listener.wait()
        except Exception as exc:
            if suppress:
                log.warning(
                    "Não foi possível suprimir a entrada local (%s); os eventos "
                    "também afetarão esta máquina. Limitação comum em X11.",
                    exc,
                )
                self._stop_listeners()
                self._kb_listener = keyboard.Listener(
                    on_press=self._on_press, on_release=self._on_release
                )
                self._mouse_listener = mouse.Listener(
                    on_move=self._on_move,
                    on_click=self._on_click,
                    on_scroll=self._on_scroll,
                )
                self._kb_listener.start()
                self._mouse_listener.start()
            else:
                raise

    def _stop_listeners(self) -> None:
        for listener in (self._kb_listener, self._mouse_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._kb_listener = None
        self._mouse_listener = None

    def _rebuild_listeners(self) -> None:
        self._stop_listeners()
        self._build_listeners()

    # ------------------------------------------------------------- callbacks
    def _feed_hotkey(self, key, pressed: bool) -> None:
        if self._hotkey is None or self._kb_listener is None:
            return
        try:
            canonical = self._kb_listener.canonical(key)
            if pressed:
                self._hotkey.press(canonical)
            else:
                self._hotkey.release(canonical)
        except Exception:
            pass

    def _on_press(self, key) -> None:
        self._feed_hotkey(key, pressed=True)
        if self._toggle_requested.is_set() or not self._remote:
            return
        wire = key_to_wire(key)
        if wire is None:
            return
        self._down_keys.add((wire["kind"], wire["v"]))
        self._enqueue({"t": "kb", "down": True, "key": wire})

    def _on_release(self, key) -> None:
        self._feed_hotkey(key, pressed=False)
        if not self._remote:
            return
        wire = key_to_wire(key)
        if wire is None:
            return
        self._down_keys.discard((wire["kind"], wire["v"]))
        self._enqueue({"t": "kb", "down": False, "key": wire})

    def _on_move(self, x, y) -> None:
        if not self._remote or self._anchor is None:
            return
        ax, ay = self._anchor
        if (x, y) == (ax, ay):
            return  # evento gerado pelo nosso próprio reposicionamento
        dx, dy = x - ax, y - ay
        if dx or dy:
            self._enqueue({"t": "mm", "dx": dx, "dy": dy})
        self._warp()

    def _on_click(self, x, y, button, pressed) -> None:
        if not self._remote:
            return
        name = button_to_wire(button)
        if pressed:
            self._down_buttons.add(name)
        else:
            self._down_buttons.discard(name)
        self._enqueue({"t": "mb", "b": name, "down": bool(pressed)})

    def _on_scroll(self, x, y, dx, dy) -> None:
        if not self._remote:
            return
        self._enqueue({"t": "ms", "dx": int(dx), "dy": int(dy)})
