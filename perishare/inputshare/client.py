"""Cliente de entrada: recebe eventos do servidor e os injeta localmente.

Roda na máquina que será controlada pelo teclado/mouse da outra. Reconecta
sozinho se a conexão cair e, por segurança, solta todas as teclas e botões
que estavam pressionados quando a conexão termina.
"""

from __future__ import annotations

import logging
import socket
import time

from .. import netmsg
from ..security import HandshakeError, client_handshake, make_cipher
from ..service import Service
from .events import button_from_wire, key_from_wire

log = logging.getLogger("perishare.input.client")

_RETRY_DELAY = 3.0


class InputClient(Service):
    name = "input-client"

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self._kb_ctl = None
        self._mouse_ctl = None
        self._down_keys: set = set()
        self._down_buttons: set = set()

    def start(self) -> None:
        self._cfg.require_secret()
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            raise RuntimeError(
                "Não foi possível inicializar a injeção de entrada "
                f"({exc}). No Linux é necessária uma sessão gráfica X11."
            ) from exc
        self._kb_ctl = keyboard.Controller()
        self._mouse_ctl = mouse.Controller()
        self._running.set()
        self._spawn(self._run_loop, "input-client")
        log.info(
            "Cliente de entrada ativo; conectando a %s:%d ...",
            self._cfg.input_server_host,
            self._cfg.input_port,
        )

    def _run_loop(self) -> None:
        while self._running.is_set():
            sock = None
            try:
                sock = socket.create_connection(
                    (self._cfg.input_server_host, self._cfg.input_port), timeout=5
                )
                sock.settimeout(10)
                session_key = client_handshake(sock, self._cfg.secret_bytes)
                cipher = make_cipher(
                    session_key, is_server=False, enabled=self._cfg.encrypt
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                log.info("Conectado ao servidor de entrada.")
                self._receive(sock, cipher)
            except HandshakeError as exc:
                log.error("Falha de autenticação: %s", exc)
            except (ConnectionError, OSError) as exc:
                log.info("Servidor de entrada indisponível (%s).", exc)
            except RuntimeError as exc:
                log.error("%s", exc)
                break
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self._release_all()
            deadline = time.monotonic() + _RETRY_DELAY
            while self._running.is_set() and time.monotonic() < deadline:
                time.sleep(0.2)

    def _receive(self, sock: socket.socket, cipher) -> None:
        sock.settimeout(1.0)
        idle = 0.0
        while self._running.is_set():
            try:
                msg = netmsg.recv_json(sock, cipher)
            except socket.timeout:
                idle += 1.0
                if idle > 10.0:
                    raise ConnectionError("servidor silencioso há 10 s")
                continue
            idle = 0.0
            self._apply(msg)

    def _apply(self, msg: dict) -> None:
        kind = msg.get("t")
        try:
            if kind == "mm":
                self._mouse_ctl.move(int(msg["dx"]), int(msg["dy"]))
            elif kind == "mb":
                button = button_from_wire(msg["b"])
                if msg["down"]:
                    self._down_buttons.add(button)
                    self._mouse_ctl.press(button)
                else:
                    self._down_buttons.discard(button)
                    self._mouse_ctl.release(button)
            elif kind == "ms":
                self._mouse_ctl.scroll(int(msg["dx"]), int(msg["dy"]))
            elif kind == "kb":
                key = key_from_wire(msg.get("key") or {})
                if key is None:
                    return
                if msg["down"]:
                    self._down_keys.add(key)
                    self._kb_ctl.press(key)
                else:
                    self._down_keys.discard(key)
                    self._kb_ctl.release(key)
            elif kind == "ping":
                pass
        except (KeyError, ValueError, TypeError) as exc:
            log.debug("Evento inválido ignorado: %s (%s)", msg, exc)
        except Exception as exc:
            log.debug("Falha ao injetar evento %s: %s", msg, exc)

    def _release_all(self) -> None:
        for key in list(self._down_keys):
            try:
                self._kb_ctl.release(key)
            except Exception:
                pass
        for button in list(self._down_buttons):
            try:
                self._mouse_ctl.release(button)
            except Exception:
                pass
        self._down_keys.clear()
        self._down_buttons.clear()
