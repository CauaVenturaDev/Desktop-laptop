"""Emissor de áudio: captura um dispositivo local e transmite pela rede.

Roda na máquina cujo som deve tocar nos fones da outra. Para transmitir o
som do sistema, configure ``capture_device`` com um dispositivo de
monitor/loopback (veja ``perishare devices``); com um microfone selecionado,
transmite o microfone. PCM bruto s16le em blocos pequenos, sem compressão —
adequado a redes locais.
"""

from __future__ import annotations

import collections
import logging
import socket
import threading

from .. import netmsg
from ..security import HandshakeError, make_cipher, server_handshake
from ..service import Service
from .devices import resolve_device

log = logging.getLogger("perishare.audio.sender")

_QUEUE_BLOCKS = 32  # ~320 ms de fila de captura antes de descartar


class AudioSender(Service):
    name = "audio-send"

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self._srv_sock: socket.socket | None = None

    def start(self) -> None:
        self._cfg.require_secret()
        try:
            import sounddevice  # noqa: F401
        except Exception as exc:
            raise RuntimeError(
                f"Não foi possível carregar o sounddevice/PortAudio ({exc}). "
                "No Arch instale o pacote 'python-sounddevice'."
            ) from exc
        self._device = resolve_device(self._cfg.audio_capture_device, "input")
        self._srv_sock = socket.create_server(
            (self._cfg.audio_listen_host, self._cfg.audio_port)
        )
        self._srv_sock.settimeout(1.0)
        self._running.set()
        self._spawn(self._serve_loop, "audio-send")
        log.info(
            "Emissor de áudio escutando em %s:%d.",
            self._cfg.audio_listen_host,
            self._cfg.audio_port,
        )

    def stop(self) -> None:
        self._running.clear()
        if self._srv_sock is not None:
            try:
                self._srv_sock.close()
            except OSError:
                pass
        super().stop()

    def _serve_loop(self) -> None:
        while self._running.is_set():
            try:
                conn, addr = self._srv_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            log.info("Receptor de áudio conectado: %s:%d", addr[0], addr[1])
            try:
                self._stream_to(conn)
            except HandshakeError as exc:
                log.warning("Conexão de %s rejeitada: %s", addr, exc)
            except (ConnectionError, OSError) as exc:
                log.info("Receptor desconectado (%s).", exc)
            except RuntimeError as exc:
                log.error("%s", exc)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _stream_to(self, conn: socket.socket) -> None:
        import sounddevice as sd

        conn.settimeout(10)
        session_key = server_handshake(conn, self._cfg.secret_bytes)
        cipher = make_cipher(session_key, is_server=True, enabled=self._cfg.encrypt)
        conn.settimeout(None)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        rate = self._cfg.audio_samplerate
        channels = self._cfg.audio_channels
        blocksize = self._cfg.audio_blocksize
        netmsg.send_json(
            conn,
            {"rate": rate, "channels": channels, "blocksize": blocksize, "format": "s16le"},
            cipher,
        )

        buffer: collections.deque = collections.deque(maxlen=_QUEUE_BLOCKS)
        ready = threading.Condition()

        def callback(indata, frames, timeinfo, status):
            if status:
                log.debug("Status da captura: %s", status)
            with ready:
                buffer.append(bytes(indata))
                ready.notify()

        with sd.RawInputStream(
            device=self._device,
            samplerate=rate,
            channels=channels,
            dtype="int16",
            blocksize=blocksize,
            callback=callback,
        ):
            log.info("Transmitindo áudio (%d Hz, %d canais)...", rate, channels)
            while self._running.is_set():
                with ready:
                    if not buffer:
                        ready.wait(timeout=0.2)
                    frame = buffer.popleft() if buffer else None
                if frame is None:
                    continue
                netmsg.send_frame(conn, frame, cipher)
