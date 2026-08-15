"""Servidor de entrada (backend Linux/kernel): captura via /dev/input/event*.

Roda na máquina com o teclado/mouse físicos. Lê os eventos direto do kernel
(evdev), o que funciona em qualquer compositor — X11, Wayland, Hyprland ou
até no console — ao contrário do backend pynput, restrito ao X11.

--- Segurança do "grab" (captura exclusiva) ---
O maior risco de um KVM em nível de kernel é o usuário ficar "trancado":
capturamos o teclado/mouse com EVIOCGRAB para suprimir a entrada local, e se
o app travasse com o grab ativo o usuário perderia o controle. Mitigações:

  1. Só capturamos com grab no modo REMOTO. No modo local não há grab algum —
     a máquina funciona normalmente.
  2. O atalho de alternância é detectado a partir do próprio fluxo evdev, que
     continua sendo lido mesmo com grab ativo. Ou seja, o atalho SEMPRE
     libera o controle.
  3. Qualquer saída — stop(), exceção, SIGTERM/SIGHUP, Ctrl+C — libera o grab.
  4. O grab é atrelado ao descritor de arquivo aberto: se o processo morrer
     (inclusive por SIGKILL), o kernel libera o grab automaticamente. Não há
     como ficar trancado com o processo encerrado.
  5. Se a conexão com o cliente cair no modo remoto, voltamos ao modo local
     (liberando o grab) na hora.
  6. Com grab = false na configuração, nunca capturamos com exclusividade
     (a entrada vai para as duas máquinas) — modo ultraconservador, zero risco
     de trancar.
"""

from __future__ import annotations

import atexit
import logging
import os
import selectors
import signal
import threading

from . import keymap
from .transport import ServerTransport

log = logging.getLogger("perishare.input.evdev-server")

_VIRTUAL_NAME = "PeriShare Virtual Input"


class EvdevInputServer(ServerTransport):
    name = "input-server"

    def __init__(self, cfg):
        super().__init__(cfg, cfg.input_listen_host, cfg.input_port, logger=log)
        self._use_grab = cfg.input_grab
        self._hotkey_str = cfg.toggle_hotkey
        self._devices: list = []
        self._selector: selectors.BaseSelector | None = None
        self._hotkey_tokens: list = []

        self._remote = False
        self._toggle_latched = False
        self._grabbed = False
        self._state_lock = threading.RLock()

        self._pressed: set = set()      # códigos evdev fisicamente pressionados
        self._fwd_keys: set = set()     # teclas encaminhadas como "down" à remota
        self._fwd_btns: set = set()     # botões encaminhados como "down"
        self._rel_dx = 0
        self._rel_dy = 0
        self._signals_installed = False

    # ------------------------------------------------------------------ vida
    def start(self) -> None:
        self._cfg.require_secret()
        try:
            import evdev  # noqa: F401
        except Exception as exc:
            raise RuntimeError(_missing_evdev_msg(exc)) from exc

        self._hotkey_tokens = keymap.parse_hotkey_to_evdev(self._hotkey_str)
        if not self._hotkey_tokens:
            raise RuntimeError(
                f"toggle_hotkey inválido para o backend evdev: {self._hotkey_str!r}"
            )

        self._devices = _open_input_devices()
        if not self._devices:
            raise RuntimeError(_no_devices_msg())

        self._selector = selectors.DefaultSelector()
        for dev in self._devices:
            self._selector.register(dev, selectors.EVENT_READ)

        self.start_transport()
        self._spawn(self._capture_loop, "evdev-capture")
        self._install_safety_backstops()

        names = ", ".join(sorted({d.name for d in self._devices}))
        log.info(
            "Servidor de entrada (evdev) escutando em %s:%d. Dispositivos: %s",
            self._listen_host,
            self._port,
            names,
        )
        log.info(
            "Atalho para alternar: %s | captura exclusiva (grab): %s",
            self._hotkey_str,
            "sim" if self._use_grab else "não",
        )

    def stop(self) -> None:
        # Prioridade absoluta: garantir que a entrada local volte ao usuário.
        self._set_remote(False)
        self._safe_ungrab()
        self.stop_transport()  # limpa _running, fecha o socket, encerra o cliente
        super().stop()         # junta as threads (Service.stop)
        for dev in self._devices:
            try:
                dev.close()
            except Exception:
                pass
        self._devices = []
        if self._selector is not None:
            try:
                self._selector.close()
            except Exception:
                pass
            self._selector = None

    def on_client_lost(self) -> None:
        # Sem cliente não podemos ficar com a entrada local suprimida.
        if self._remote:
            log.info("Cliente perdido; devolvendo o controle a esta máquina.")
            self._set_remote(False)

    # ----------------------------------------------------- captura principal
    def _capture_loop(self) -> None:
        from evdev import ecodes

        assert self._selector is not None
        while self._running.is_set():
            try:
                ready = self._selector.select(timeout=0.2)
            except OSError:
                break
            for key, _mask in ready:
                dev = key.fileobj
                try:
                    for event in dev.read():
                        self._handle_event(event, ecodes)
                except OSError:
                    # Dispositivo removido (ex.: teclado USB desconectado).
                    self._drop_device(dev)
        self._safe_ungrab()

    def _drop_device(self, dev) -> None:
        try:
            self._selector.unregister(dev)
        except (KeyError, ValueError, OSError):
            pass
        try:
            dev.close()
        except Exception:
            pass
        if dev in self._devices:
            self._devices.remove(dev)
        log.warning("Dispositivo de entrada removido: %s", getattr(dev, "name", "?"))

    def _handle_event(self, event, ecodes) -> None:
        if event.type == ecodes.EV_KEY:
            self._handle_key(event, ecodes)
        elif event.type == ecodes.EV_REL:
            self._handle_rel(event, ecodes)
        elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
            self._flush_motion()

    def _handle_key(self, event, ecodes) -> None:
        code = event.code
        value = event.value  # 0=solta, 1=pressiona, 2=repete

        if value == 1:
            self._pressed.add(code)
        elif value == 0:
            self._pressed.discard(code)

        # Detecção do atalho a partir do fluxo bruto (funciona mesmo com grab).
        if self._hotkey_active():
            if not self._toggle_latched:
                self._toggle_latched = True
                self._toggle()
            return  # não encaminha as teclas do atalho
        else:
            self._toggle_latched = False

        if not self._remote:
            return

        if keymap.is_button(code):
            if value == 2:
                return  # botões de mouse não têm autorrepetição
            name = keymap.button_code_to_name(code)
            if name is None:
                return
            if value == 1:
                self._fwd_btns.add(code)
                self._enqueue({"t": "mb", "b": name, "down": True})
            elif code in self._fwd_btns:
                # Só solta na remota o que realmente enviamos como pressionado.
                self._fwd_btns.discard(code)
                self._enqueue({"t": "mb", "b": name, "down": False})
            return

        if value in (1, 2):
            shift_active = _shift_active(self._pressed, ecodes)
            wire = keymap.key_event_to_wire(code, shift_active)
            self._fwd_keys.add(code)
            self._enqueue({"t": "kb", "down": True, "key": wire, "code": code})
        elif code in self._fwd_keys:
            # Evita "soltar" na remota teclas nunca enviadas (ex.: os
            # modificadores usados só para acionar o atalho de alternância).
            self._fwd_keys.discard(code)
            wire = keymap.key_event_to_wire(code, False)
            self._enqueue({"t": "kb", "down": False, "key": wire, "code": code})

    def _handle_rel(self, event, ecodes) -> None:
        if not self._remote:
            return
        if event.code == ecodes.REL_X:
            self._rel_dx += event.value
        elif event.code == ecodes.REL_Y:
            self._rel_dy += event.value
        elif event.code == ecodes.REL_WHEEL:
            self._enqueue({"t": "ms", "dx": 0, "dy": int(event.value)})
        elif event.code == ecodes.REL_HWHEEL:
            self._enqueue({"t": "ms", "dx": int(event.value), "dy": 0})

    def _flush_motion(self) -> None:
        if self._remote and (self._rel_dx or self._rel_dy):
            self._enqueue({"t": "mm", "dx": self._rel_dx, "dy": self._rel_dy})
        self._rel_dx = 0
        self._rel_dy = 0

    def _hotkey_active(self) -> bool:
        if not self._hotkey_tokens:
            return False
        return all(token & self._pressed for token in self._hotkey_tokens)

    # ------------------------------------------------------- modo remoto/grab
    def _toggle(self) -> None:
        self._set_remote(not self._remote)

    def _set_remote(self, state: bool) -> None:
        with self._state_lock:
            if state == self._remote:
                return
            if state:
                if not self._has_client():
                    log.warning("Nenhum cliente conectado; permanecendo em modo local.")
                    return
                self._remote = True
                if self._use_grab:
                    self._grab(True)
                log.info(
                    "Controlando a máquina remota. Pressione %s para voltar.",
                    self._hotkey_str,
                )
            else:
                self._release_forwarded()
                if self._use_grab:
                    self._grab(False)
                self._remote = False
                log.info("Controle de volta nesta máquina (modo local).")

    def _release_forwarded(self) -> None:
        # Solta na máquina remota tudo que ficou pressionado, evitando travar.
        for code in list(self._fwd_keys):
            wire = keymap.key_event_to_wire(code, False)
            self._enqueue({"t": "kb", "down": False, "key": wire, "code": code})
        for code in list(self._fwd_btns):
            name = keymap.button_code_to_name(code)
            if name is not None:
                self._enqueue({"t": "mb", "b": name, "down": False})
        self._fwd_keys.clear()
        self._fwd_btns.clear()

    def _grab(self, state: bool) -> None:
        with self._state_lock:
            if state == self._grabbed:
                return
            for dev in list(self._devices):
                try:
                    if state:
                        dev.grab()
                    else:
                        dev.ungrab()
                except OSError:
                    pass
            self._grabbed = state

    def _safe_ungrab(self) -> None:
        try:
            self._grab(False)
        except Exception:
            pass

    # --------------------------------------------------------- backstops OS
    def _install_safety_backstops(self) -> None:
        atexit.register(self._safe_ungrab)
        if self._signals_installed:
            return
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGHUP):
                try:
                    signal.signal(sig, self._on_signal)
                except (ValueError, OSError):
                    pass
            self._signals_installed = True

    def _on_signal(self, signum, frame):
        # Converte em KeyboardInterrupt para run_forever() chamar stop() e
        # liberar o grab de forma limpa.
        raise KeyboardInterrupt


def _shift_active(pressed: set, ecodes) -> bool:
    return ecodes.KEY_LEFTSHIFT in pressed or ecodes.KEY_RIGHTSHIFT in pressed


def _open_input_devices() -> list:
    """Abre teclados e ponteiros, ignorando nosso próprio dispositivo virtual."""
    import evdev
    from evdev import ecodes

    devices = []
    denied = 0
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except PermissionError:
            denied += 1
            continue
        except OSError:
            continue
        if dev.name == _VIRTUAL_NAME:
            dev.close()
            continue
        caps = dev.capabilities()
        keys = set(caps.get(ecodes.EV_KEY, []))
        rels = set(caps.get(ecodes.EV_REL, []))
        is_keyboard = ecodes.KEY_A in keys or ecodes.KEY_ENTER in keys
        is_pointer = (ecodes.REL_X in rels and ecodes.REL_Y in rels) or ecodes.BTN_LEFT in keys
        if is_keyboard or is_pointer:
            devices.append(dev)
        else:
            dev.close()
    if not devices:
        # O evdev.list_devices() oculta os dispositivos ilegíveis, então
        # "lista vazia" quase sempre é falta de permissão de leitura, não
        # ausência de hardware. Diagnostica pelos nós brutos e pelo grupo.
        raise RuntimeError(_no_devices_msg(saw_denied=denied > 0))
    return devices


def _user_in_group(name: str) -> bool:
    try:
        import grp

        entry = grp.getgrnam(name)
    except (KeyError, ImportError):
        return False
    if entry.gr_gid in os.getgroups():
        return True
    try:
        import getpass

        return getpass.getuser() in entry.gr_mem
    except Exception:
        return os.environ.get("USER", "") in entry.gr_mem


def _missing_evdev_msg(exc) -> str:
    return (
        "Backend evdev/uinput indisponível: não foi possível carregar o pacote "
        f"'evdev' ({exc}). Instale-o (Arch: 'sudo pacman -S python-evdev'; "
        "outros: 'pip install evdev') ou use o backend pynput em uma sessão X11 "
        '(defina backend = "pynput" em [input]).'
    )


def _no_devices_msg(saw_denied: bool = False) -> str:
    import glob

    nodes = glob.glob("/dev/input/event*")
    if not nodes and not saw_denied:
        return (
            "Nenhum dispositivo em /dev/input/event*. Isso é raro: verifique se há "
            "teclado/mouse conectados e se o kernel os expõe."
        )
    if _user_in_group("input"):
        return (
            "Não foi possível ler os dispositivos de /dev/input, embora você já "
            "esteja no grupo 'input' — a SESSÃO ATUAL ainda não aplicou o grupo.\n"
            "Faça logout/login (ou reinicie). Para testar sem relogar, rode nesta "
            "mesma shell:\n"
            "  newgrp input\n"
            "  perishare input-server\n"
            "Confira com 'id' que 'input' aparece nos seus grupos."
        )
    return (
        "Sem permissão para ler /dev/input/event*. Seu usuário não está no grupo "
        "'input'. Rode:\n"
        "  sudo usermod -aG input $USER\n"
        "e faça logout/login (o grupo só vale em sessões novas). Alternativa sem "
        'grupo: use backend = "pynput" no servidor (X11). O app não altera '
        "permissões sozinho."
    )
