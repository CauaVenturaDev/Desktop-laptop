"""Receptor de áudio: recebe o fluxo da rede e reproduz nos fones locais.

Roda na máquina onde os fones estão conectados. Mantém um pequeno buffer
de jitter (~40 ms) para absorver variações da rede e descarta o excedente
para a latência não crescer. Reconecta sozinho se a conexão cair.
"""

from __future__ import annotations

import collections
import logging
import socket
import time

from .. import netmsg
from ..security import HandshakeError, client_handshake, make_cipher
from ..service import Service
from .devices import resolve_device

log = logging.getLogger("perishare.audio.receiver")

_RETRY_DELAY = 3.0
_PREBUFFER_BLOCKS = 4
_MAX_BUFFER_BLOCKS = 16


class AudioReceiver(Service):
    name = "audio-recv"

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg

    def start(self) -> None:
        self._cfg.require_secret()
        try:
            import sounddevice  # noqa: F401
        except Exception as exc:
            raise RuntimeError(
                f"Não foi possível carregar o sounddevice/PortAudio ({exc}). "
                "No Arch instale o pacote 'python-sounddevice'."
            ) from exc
        self._device = resolve_device(self._cfg.audio_playback_device, "output")
        self._running.set()
        self._spawn(self._run_loop, "audio-recv")
        log.info(
            "Receptor de áudio ativo; conectando a %s:%d ...",
            self._cfg.audio_server_host,
            self._cfg.audio_port,
        )

    def _run_loop(self) -> None:
        while self._running.is_set():
            sock = None
            try:
                sock = socket.create_connection(
                    (self._cfg.audio_server_host, self._cfg.audio_port), timeout=5
                )
                sock.settimeout(10)
                session_key = client_handshake(sock, self._cfg.secret_bytes)
                cipher = make_cipher(
                    session_key, is_server=False, enabled=self._cfg.encrypt
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                header = netmsg.recv_json(sock, cipher)
                self._play(sock, header, cipher)
            except HandshakeError as exc:
                log.error("Falha de autenticação: %s", exc)
            except (ConnectionError, OSError) as exc:
                log.info("Emissor de áudio indisponível (%s).", exc)
            except RuntimeError as exc:
                log.error("%s", exc)
                break
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            deadline = time.monotonic() + _RETRY_DELAY
            while self._running.is_set() and time.monotonic() < deadline:
                time.sleep(0.2)

    def _play(self, sock: socket.socket, header: dict, cipher) -> None:
        import sounddevice as sd

        if header.get("format") != "s16le":
            raise ConnectionError(f"formato de áudio não suportado: {header.get('format')!r}")
        rate = int(header["rate"])
        channels = int(header["channels"])
        blocksize = int(header["blocksize"])
        frame_bytes = blocksize * channels * 2
        silence = b"\x00" * frame_bytes

        buffer: collections.deque = collections.deque()

        def callback(outdata, frames, timeinfo, status):
            if status:
                log.debug("Status da reprodução: %s", status)
            data = buffer.popleft() if buffer else silence
            if len(data) != len(outdata):
                data = (data + silence)[: len(outdata)]
            outdata[:] = data

        sock.settimeout(5)
        for _ in range(_PREBUFFER_BLOCKS):
            buffer.append(netmsg.recv_frame(sock, cipher))

        with sd.RawOutputStream(
            device=self._device,
            samplerate=rate,
            channels=channels,
            dtype="int16",
            blocksize=blocksize,
            callback=callback,
        ):
            log.info("Reproduzindo áudio remoto (%d Hz, %d canais)...", rate, channels)
            while self._running.is_set():
                buffer.append(netmsg.recv_frame(sock, cipher))
                while len(buffer) > _MAX_BUFFER_BLOCKS:
                    buffer.popleft()
