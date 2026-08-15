"""Cliente de entrada (backend Linux/kernel): injeta via /dev/uinput.

Cria um teclado+mouse virtuais no kernel; o compositor (Wayland/Hyprland ou
X11) os trata como hardware real. Preferimos o código de tecla bruto do
evdev quando o emissor o envia (fidelidade perfeita Linux ⇄ Linux) e
recorremos ao mapa de caracteres quando o emissor é pynput (Windows/X11).

Segurança: um dispositivo virtual é inofensivo ao sistema — não interfere no
teclado físico. Ainda assim, ao cair a conexão soltamos todas as teclas e
botões que ficaram pressionados, para nada travar apertado.
"""

from __future__ import annotations

import logging

from . import keymap
from .transport import ClientTransport

log = logging.getLogger("perishare.input.evdev-client")

_UINPUT_NAME = "PeriShare Virtual Input"


class EvdevInputClient(ClientTransport):
    name = "input-client"

    def __init__(self, cfg):
        super().__init__(cfg, cfg.input_server_host, cfg.input_port, logger=log)
        self._ui = None
        self._down_keys: set = set()
        self._down_btns: set = set()

    def start(self) -> None:
        self._cfg.require_secret()
        try:
            from evdev import UInput, ecodes
        except Exception as exc:  # ImportError, e possíveis erros de binding
            raise RuntimeError(_missing_evdev_msg(exc)) from exc

        capabilities = {
            ecodes.EV_KEY: keymap.all_key_codes(),
            ecodes.EV_REL: [
                ecodes.REL_X,
                ecodes.REL_Y,
                ecodes.REL_WHEEL,
                ecodes.REL_HWHEEL,
            ],
        }
        try:
            self._ui = UInput(events=capabilities, name=_UINPUT_NAME)
        except PermissionError as exc:
            raise RuntimeError(_uinput_perm_msg()) from exc
        except (OSError, Exception) as exc:  # FileNotFoundError etc.
            raise RuntimeError(_uinput_generic_msg(exc)) from exc

        self.start_transport()
        log.info(
            "Cliente de entrada (uinput) ativo; conectando a %s:%d ...",
            self._server_host,
            self._port,
        )

    def stop(self) -> None:
        super().stop()  # encerra threads e solta teclas via _release_all
        if self._ui is not None:
            try:
                self._ui.close()
            except Exception:
                pass
            self._ui = None

    def _apply(self, msg: dict) -> None:
        from evdev import ecodes

        kind = msg.get("t")
        ui = self._ui
        if ui is None:
            return
        try:
            if kind == "mm":
                ui.write(ecodes.EV_REL, ecodes.REL_X, int(msg["dx"]))
                ui.write(ecodes.EV_REL, ecodes.REL_Y, int(msg["dy"]))
                ui.syn()
            elif kind == "mb":
                code = keymap.button_name_to_code(msg.get("b"))
                if code is None:
                    return
                down = bool(msg["down"])
                ui.write(ecodes.EV_KEY, code, 1 if down else 0)
                ui.syn()
                (self._down_btns.add if down else self._down_btns.discard)(code)
            elif kind == "ms":
                dx, dy = int(msg.get("dx", 0)), int(msg.get("dy", 0))
                if dy:
                    ui.write(ecodes.EV_REL, ecodes.REL_WHEEL, dy)
                if dx:
                    ui.write(ecodes.EV_REL, ecodes.REL_HWHEEL, dx)
                ui.syn()
            elif kind == "kb":
                code = msg.get("code")
                if code is None:
                    code = keymap.wire_to_keycode(msg.get("key") or {})
                if code is None:
                    return
                down = bool(msg["down"])
                ui.write(ecodes.EV_KEY, int(code), 1 if down else 0)
                ui.syn()
                (self._down_keys.add if down else self._down_keys.discard)(int(code))
            elif kind == "ping":
                pass
        except (KeyError, ValueError, TypeError) as exc:
            log.debug("Evento inválido ignorado: %s (%s)", msg, exc)
        except Exception as exc:
            log.debug("Falha ao injetar evento %s: %s", msg, exc)

    def _release_all(self) -> None:
        from evdev import ecodes

        ui = self._ui
        if ui is None:
            self._down_keys.clear()
            self._down_btns.clear()
            return
        for code in list(self._down_keys) + list(self._down_btns):
            try:
                ui.write(ecodes.EV_KEY, code, 0)
            except Exception:
                pass
        try:
            ui.syn()
        except Exception:
            pass
        self._down_keys.clear()
        self._down_btns.clear()


def _missing_evdev_msg(exc) -> str:
    return (
        "Backend evdev/uinput indisponível: não foi possível carregar o pacote "
        f"'evdev' ({exc}). Instale-o (Arch: 'sudo pacman -S python-evdev'; "
        "outros: 'pip install evdev') ou use o backend pynput em uma sessão X11 "
        '(defina backend = "pynput" em [input]).'
    )


def _uinput_perm_msg() -> str:
    return (
        "Sem permissão para criar o dispositivo virtual em /dev/uinput.\n"
        "Solução (uma vez só, veja packaging/linux/):\n"
        "  1. Regra udev: instale 99-perishare-uinput.rules em /etc/udev/rules.d/\n"
        "  2. Carregue o módulo: sudo modprobe uinput\n"
        "  3. Entre no grupo 'input': sudo usermod -aG input $USER (e refaça login)\n"
        "Nenhuma dessas etapas é feita automaticamente pelo app."
    )


def _uinput_generic_msg(exc) -> str:
    return (
        f"Não foi possível abrir /dev/uinput ({exc}). "
        "Verifique se o módulo do kernel 'uinput' está carregado "
        "(sudo modprobe uinput) e as permissões (packaging/linux/)."
    )
