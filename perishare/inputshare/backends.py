"""Seleção do backend de entrada conforme a plataforma e a configuração.

- ``pynput``: X11 e Windows. Não exige permissões especiais. Não funciona em
  Wayland.
- ``evdev``: Linux em nível de kernel (evdev + uinput). Funciona em qualquer
  compositor, incluindo Wayland/Hyprland. Exige acesso a /dev/input e
  /dev/uinput (grupo 'input' + regra udev; veja packaging/linux/).

Com ``backend = "auto"`` (padrão):
  - Windows  -> pynput
  - Linux em sessão Wayland ($WAYLAND_DISPLAY definido) -> evdev
  - Linux em X11 -> pynput (funciona sem configurar permissões)
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("perishare.input")

VALID_BACKENDS = ("auto", "pynput", "evdev")


def resolve_backend(cfg) -> str:
    choice = (cfg.input_backend or "auto").lower()
    if choice not in VALID_BACKENDS:
        raise SystemExit(
            f"backend inválido em [input]: {choice!r}. Use um de: {', '.join(VALID_BACKENDS)}."
        )
    if choice != "auto":
        return choice
    if sys.platform == "win32":
        return "pynput"
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
        return "evdev"
    return "pynput"


def make_input_server(cfg):
    backend = resolve_backend(cfg)
    log.debug("Backend de entrada (servidor): %s", backend)
    if backend == "evdev":
        from .evdev_server import EvdevInputServer

        return EvdevInputServer(cfg)
    from .server import InputServer

    return InputServer(cfg)


def make_input_client(cfg):
    backend = resolve_backend(cfg)
    log.debug("Backend de entrada (cliente): %s", backend)
    if backend == "evdev":
        from .evdev_client import EvdevInputClient

        return EvdevInputClient(cfg)
    from .client import InputClient

    return InputClient(cfg)
