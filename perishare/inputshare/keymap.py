"""Tradução entre códigos de tecla do evdev (kernel Linux) e o formato de rede.

O backend evdev/uinput usa códigos de tecla do kernel (KEY_A = 30, ...). O
backend pynput (X11/Windows) usa caracteres e nomes simbólicos. Para que as
duas pontas conversem em qualquer combinação, o emissor evdev envia os DOIS:
o código bruto do evdev (``code``, fidelidade perfeita entre Linux ⇄ Linux) e
uma representação portável (``key`` com caractere/nome, para receptores
pynput). O receptor escolhe a melhor forma disponível.

As tabelas são construídas sob demanda para que o módulo possa ser importado
mesmo sem o pacote ``evdev`` instalado (só as funções exigem o evdev).
"""

from __future__ import annotations

from functools import lru_cache

# --- Teclas de caractere no layout US QWERTY: (nome evdev, sem shift, com shift).
_CHAR_ROWS = [
    ("KEY_GRAVE", "`", "~"),
    ("KEY_1", "1", "!"), ("KEY_2", "2", "@"), ("KEY_3", "3", "#"),
    ("KEY_4", "4", "$"), ("KEY_5", "5", "%"), ("KEY_6", "6", "^"),
    ("KEY_7", "7", "&"), ("KEY_8", "8", "*"), ("KEY_9", "9", "("),
    ("KEY_0", "0", ")"), ("KEY_MINUS", "-", "_"), ("KEY_EQUAL", "=", "+"),
    ("KEY_Q", "q", "Q"), ("KEY_W", "w", "W"), ("KEY_E", "e", "E"),
    ("KEY_R", "r", "R"), ("KEY_T", "t", "T"), ("KEY_Y", "y", "Y"),
    ("KEY_U", "u", "U"), ("KEY_I", "i", "I"), ("KEY_O", "o", "O"),
    ("KEY_P", "p", "P"), ("KEY_LEFTBRACE", "[", "{"),
    ("KEY_RIGHTBRACE", "]", "}"), ("KEY_BACKSLASH", "\\", "|"),
    ("KEY_A", "a", "A"), ("KEY_S", "s", "S"), ("KEY_D", "d", "D"),
    ("KEY_F", "f", "F"), ("KEY_G", "g", "G"), ("KEY_H", "h", "H"),
    ("KEY_J", "j", "J"), ("KEY_K", "k", "K"), ("KEY_L", "l", "L"),
    ("KEY_SEMICOLON", ";", ":"), ("KEY_APOSTROPHE", "'", '"'),
    ("KEY_Z", "z", "Z"), ("KEY_X", "x", "X"), ("KEY_C", "c", "C"),
    ("KEY_V", "v", "V"), ("KEY_B", "b", "B"), ("KEY_N", "n", "N"),
    ("KEY_M", "m", "M"), ("KEY_COMMA", ",", "<"), ("KEY_DOT", ".", ">"),
    ("KEY_SLASH", "/", "?"),
]

# Teclado numérico: um caractere só (mesma tecla com/sem shift para o texto).
_CHAR_KP = [
    ("KEY_KPASTERISK", "*"), ("KEY_KPPLUS", "+"), ("KEY_KPMINUS", "-"),
    ("KEY_KPSLASH", "/"), ("KEY_KPDOT", "."),
    ("KEY_KP0", "0"), ("KEY_KP1", "1"), ("KEY_KP2", "2"), ("KEY_KP3", "3"),
    ("KEY_KP4", "4"), ("KEY_KP5", "5"), ("KEY_KP6", "6"), ("KEY_KP7", "7"),
    ("KEY_KP8", "8"), ("KEY_KP9", "9"),
]

# Teclas especiais: (nome evdev, nome pynput). A ordem importa para o mapa
# reverso (nome pynput -> código): a primeira ocorrência vence, então a tecla
# "principal" (ex.: Enter em vez de Enter do teclado numérico) vem antes.
_SPECIALS = [
    ("KEY_ESC", "esc"), ("KEY_TAB", "tab"), ("KEY_CAPSLOCK", "caps_lock"),
    ("KEY_ENTER", "enter"), ("KEY_KPENTER", "enter"), ("KEY_SPACE", "space"),
    ("KEY_BACKSPACE", "backspace"), ("KEY_DELETE", "delete"),
    ("KEY_INSERT", "insert"), ("KEY_HOME", "home"), ("KEY_END", "end"),
    ("KEY_PAGEUP", "page_up"), ("KEY_PAGEDOWN", "page_down"),
    ("KEY_UP", "up"), ("KEY_DOWN", "down"), ("KEY_LEFT", "left"),
    ("KEY_RIGHT", "right"),
    ("KEY_LEFTCTRL", "ctrl_l"), ("KEY_RIGHTCTRL", "ctrl_r"),
    ("KEY_LEFTSHIFT", "shift"), ("KEY_RIGHTSHIFT", "shift_r"),
    ("KEY_LEFTALT", "alt_l"), ("KEY_RIGHTALT", "alt_gr"),
    ("KEY_LEFTMETA", "cmd"), ("KEY_RIGHTMETA", "cmd_r"),
    ("KEY_COMPOSE", "menu"), ("KEY_MENU", "menu"),
    ("KEY_SYSRQ", "print_screen"), ("KEY_SCROLLLOCK", "scroll_lock"),
    ("KEY_PAUSE", "pause"), ("KEY_NUMLOCK", "num_lock"),
    ("KEY_VOLUMEUP", "media_volume_up"), ("KEY_VOLUMEDOWN", "media_volume_down"),
    ("KEY_MUTE", "media_volume_mute"), ("KEY_PLAYPAUSE", "media_play_pause"),
    ("KEY_NEXTSONG", "media_next"), ("KEY_PREVIOUSSONG", "media_previous"),
] + [(f"KEY_F{n}", f"f{n}") for n in range(1, 21)]

# Botões do mouse: (nome evdev, nome pynput).
_BUTTONS = [
    ("BTN_LEFT", "left"), ("BTN_RIGHT", "right"), ("BTN_MIDDLE", "middle"),
]

# Tokens de modificador para o atalho de alternância (nome -> conjunto evdev).
_MODIFIER_TOKENS = {
    "ctrl": ("KEY_LEFTCTRL", "KEY_RIGHTCTRL"),
    "control": ("KEY_LEFTCTRL", "KEY_RIGHTCTRL"),
    "alt": ("KEY_LEFTALT", "KEY_RIGHTALT"),
    "alt_gr": ("KEY_RIGHTALT",),
    "shift": ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"),
    "cmd": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
    "super": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
    "win": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
    "meta": ("KEY_LEFTMETA", "KEY_RIGHTMETA"),
}


def _code(name: str):
    from evdev import ecodes

    return getattr(ecodes, name, None)


@lru_cache(maxsize=1)
def _code_to_special() -> dict:
    out = {}
    for evname, pyname in _SPECIALS:
        code = _code(evname)
        if code is not None:
            out.setdefault(code, pyname)
    return out


@lru_cache(maxsize=1)
def _special_to_code() -> dict:
    out = {}
    for evname, pyname in _SPECIALS:
        code = _code(evname)
        if code is not None:
            out.setdefault(pyname, code)
    return out


@lru_cache(maxsize=1)
def _code_to_chars() -> dict:
    out = {}
    for evname, base, shifted in _CHAR_ROWS:
        code = _code(evname)
        if code is not None:
            out[code] = (base, shifted)
    for evname, ch in _CHAR_KP:
        code = _code(evname)
        if code is not None:
            out[code] = (ch, ch)
    return out


@lru_cache(maxsize=1)
def _char_to_code() -> dict:
    out = {}
    # Numérico primeiro para que a fileira principal ("/", "-", ...) prevaleça.
    for evname, ch in _CHAR_KP:
        code = _code(evname)
        if code is not None:
            out[ch] = code
    for evname, base, shifted in _CHAR_ROWS:
        code = _code(evname)
        if code is not None:
            out[base] = code
            out[shifted] = code
    return out


@lru_cache(maxsize=1)
def _code_to_button() -> dict:
    out = {}
    for evname, pyname in _BUTTONS:
        code = _code(evname)
        if code is not None:
            out[code] = pyname
    return out


@lru_cache(maxsize=1)
def _button_to_code() -> dict:
    return {pyname: _code(evname) for evname, pyname in _BUTTONS if _code(evname) is not None}


# ------------------------------------------------------------------ públicos
def is_button(code: int) -> bool:
    return code in _code_to_button()


def button_code_to_name(code: int):
    return _code_to_button().get(code)


def button_name_to_code(name: str):
    return _button_to_code().get(name)


def key_event_to_wire(code: int, shift_active: bool):
    """Código evdev -> dict portável (``key``) para receptores pynput, ou None."""
    special = _code_to_special().get(code)
    if special is not None:
        return {"kind": "special", "v": special}
    pair = _code_to_chars().get(code)
    if pair is not None:
        return {"kind": "char", "v": pair[1] if shift_active else pair[0]}
    return None


def wire_to_keycode(key: dict):
    """dict ``key`` (de um emissor pynput) -> código evdev, ou None.

    Usado só quando o emissor não mandou o ``code`` bruto (US layout).
    """
    kind = key.get("kind")
    value = key.get("v")
    if kind == "special":
        return _special_to_code().get(value)
    if kind == "char":
        return _char_to_code().get(value)
    return None


def all_key_codes() -> list:
    """Todos os códigos EV_KEY que o dispositivo uinput precisa declarar."""
    codes = set(_code_to_special()) | set(_code_to_chars()) | set(_code_to_button())
    return sorted(codes)


def parse_hotkey_to_evdev(hotkey: str) -> list:
    """"<ctrl>+<alt>+<f12>" -> lista de conjuntos de códigos evdev.

    Cada conjunto é um "token" do atalho; o atalho está ativo quando, para
    cada token, ao menos um de seus códigos está pressionado.
    """
    tokens = []
    for part in hotkey.split("+"):
        name = part.strip().lower().strip("<>")
        if not name:
            continue
        if name in _MODIFIER_TOKENS:
            codes = {_code(n) for n in _MODIFIER_TOKENS[name]}
        else:
            single = _special_to_code().get(name) or _char_to_code().get(name)
            codes = {single} if single is not None else set()
        codes.discard(None)
        if codes:
            tokens.append(codes)
    return tokens
