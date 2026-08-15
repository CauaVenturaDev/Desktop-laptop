"""Carregamento e criação do arquivo de configuração (TOML).

Local padrão:
  Linux:   ~/.config/perishare/config.toml  (respeita XDG_CONFIG_HOME)
  Windows: %APPDATA%\\perishare\\config.toml

O mesmo arquivo (com o MESMO ``secret``) deve existir nas duas máquinas;
apenas ``server_host`` muda na máquina cliente.
"""

from __future__ import annotations

import os
import secrets as _secrets
import sys
import tomllib
from pathlib import Path

APP_NAME = "perishare"

_DEFAULTS = {
    "general": {
        "secret": "",
        "encrypt": True,
    },
    "input": {
        "listen_host": "0.0.0.0",
        "server_host": "127.0.0.1",
        "port": 42800,
        "toggle_hotkey": "<ctrl>+<alt>+<f12>",
    },
    "audio": {
        "listen_host": "0.0.0.0",
        "server_host": "127.0.0.1",
        "port": 42801,
        "samplerate": 48000,
        "channels": 2,
        "blocksize": 480,
        "capture_device": "",
        "playback_device": "",
    },
}

TEMPLATE = """\
# Configuração do PeriShare.
# Copie este arquivo para as DUAS máquinas — o campo "secret" precisa ser
# idêntico nas duas. Na máquina cliente, ajuste "server_host" para o IP da
# máquina servidora.

[general]
# Segredo compartilhado que autentica as duas máquinas entre si.
# Gerado automaticamente por "perishare init". Não o divulgue.
secret = "{secret}"
# Cifra todo o tráfego (teclas digitadas incluem senhas!). Recomendado: true.
encrypt = true

[input]  # Função 1: compartilhamento de teclado e mouse
# No servidor (máquina com teclado/mouse físicos): endereço de escuta.
listen_host = "0.0.0.0"
# No cliente (máquina controlada): IP do servidor na rede local.
server_host = "192.168.0.10"
port = 42800
# Atalho que alterna o controle entre a máquina local e a remota.
toggle_hotkey = "<ctrl>+<alt>+<f12>"

[audio]  # Função 2: compartilhamento de áudio (fones de ouvido)
# No emissor (máquina cuja saída de som será transmitida): endereço de escuta.
listen_host = "0.0.0.0"
# No receptor (máquina com os fones conectados): IP do emissor.
server_host = "192.168.0.10"
port = 42801
samplerate = 48000
channels = 2
# Amostras por bloco; 480 = 10 ms a 48 kHz. Aumente se o áudio picotar.
blocksize = 480
# Dispositivo de captura no emissor (índice ou parte do nome; veja
# "perishare devices"). No Linux use um dispositivo "monitor" para capturar
# o som do sistema; no Windows, "Stereo Mix" ou um cabo virtual.
capture_device = ""
# Dispositivo de reprodução no receptor (os fones). Vazio = padrão do sistema.
playback_device = ""
"""


def default_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / APP_NAME / "config.toml"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / APP_NAME / "config.toml"


class Config:
    def __init__(self, data: dict):
        merged = {}
        for section, defaults in _DEFAULTS.items():
            merged[section] = dict(defaults)
            for key, value in (data.get(section) or {}).items():
                merged[section][key] = value
        self._data = merged

    def _get(self, section: str, key: str):
        return self._data[section][key]

    # --- [general] ---
    @property
    def secret(self) -> str:
        return str(self._get("general", "secret"))

    @property
    def secret_bytes(self) -> bytes:
        return self.secret.encode("utf-8")

    @property
    def encrypt(self) -> bool:
        return bool(self._get("general", "encrypt"))

    def require_secret(self) -> None:
        if not self.secret:
            raise SystemExit(
                "A configuração não tem um 'secret'. Execute 'perishare init' e "
                "copie o mesmo config.toml para as duas máquinas."
            )

    # --- [input] ---
    @property
    def input_listen_host(self) -> str:
        return str(self._get("input", "listen_host"))

    @property
    def input_server_host(self) -> str:
        return str(self._get("input", "server_host"))

    @property
    def input_port(self) -> int:
        return int(self._get("input", "port"))

    @property
    def toggle_hotkey(self) -> str:
        return str(self._get("input", "toggle_hotkey"))

    # --- [audio] ---
    @property
    def audio_listen_host(self) -> str:
        return str(self._get("audio", "listen_host"))

    @property
    def audio_server_host(self) -> str:
        return str(self._get("audio", "server_host"))

    @property
    def audio_port(self) -> int:
        return int(self._get("audio", "port"))

    @property
    def audio_samplerate(self) -> int:
        return int(self._get("audio", "samplerate"))

    @property
    def audio_channels(self) -> int:
        return int(self._get("audio", "channels"))

    @property
    def audio_blocksize(self) -> int:
        return int(self._get("audio", "blocksize"))

    @property
    def audio_capture_device(self) -> str:
        return str(self._get("audio", "capture_device"))

    @property
    def audio_playback_device(self) -> str:
        return str(self._get("audio", "playback_device"))


def write_template(path: Path, force: bool = False) -> Path:
    if path.exists() and not force:
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(secret=_secrets.token_hex(32)), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def load(path: str | os.PathLike | None = None) -> Config:
    cfg_path = Path(path) if path else default_path()
    if not cfg_path.exists():
        raise SystemExit(
            f"Arquivo de configuração não encontrado: {cfg_path}\n"
            "Execute 'perishare init' para criá-lo."
        )
    with open(cfg_path, "rb") as fh:
        try:
            data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(f"Erro de sintaxe em {cfg_path}: {exc}") from exc
    return Config(data)
