"""Serialização dos eventos de teclado/mouse para o protocolo de rede.

Teclas com caractere trafegam como o próprio caractere e teclas especiais
(Enter, setas, modificadores...) pelo nome simbólico do pynput — ambos
portáveis entre Linux e Windows. Teclas sem caractere nem nome (raras)
usam o código virtual da plataforma como último recurso, o que só é fiel
entre máquinas de mesmo sistema operacional.

O pynput é importado dentro das funções para que este módulo possa ser
importado (e testado) em ambientes sem servidor gráfico.
"""

from __future__ import annotations


def key_to_wire(key):
    from pynput import keyboard

    if isinstance(key, keyboard.Key):
        return {"kind": "special", "v": key.name}
    if isinstance(key, keyboard.KeyCode):
        char = key.char
        if char is not None and len(char) == 1:
            # Com Ctrl pressionado o X11 entrega caracteres de controle
            # (Ctrl+A -> \x01); normaliza de volta para a letra, já que os
            # modificadores são encaminhados separadamente.
            if 1 <= ord(char) <= 26:
                char = chr(ord(char) + 96)
            return {"kind": "char", "v": char}
        if key.vk is not None:
            return {"kind": "vk", "v": int(key.vk)}
    return None


def key_from_wire(data):
    from pynput import keyboard

    kind = data.get("kind")
    value = data.get("v")
    if kind == "special":
        try:
            return keyboard.Key[value]
        except KeyError:
            return None
    if kind == "char":
        return keyboard.KeyCode.from_char(value)
    if kind == "vk":
        return keyboard.KeyCode.from_vk(int(value))
    return None


def button_to_wire(button) -> str:
    return button.name


def button_from_wire(name: str):
    from pynput import mouse

    return getattr(mouse.Button, name, mouse.Button.left)
