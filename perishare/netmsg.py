"""Enquadramento de mensagens no socket TCP.

Cada mensagem é um frame: 4 bytes de tamanho (big-endian) seguidos do
payload. Quando um cifrador é fornecido, o payload trafega cifrado
(AES-GCM) e o tamanho refere-se ao texto cifrado.
"""

from __future__ import annotations

import json
import struct

# Limite generoso: o maior frame legítimo é um bloco de áudio (< 1 MiB).
MAX_FRAME = 8 * 1024 * 1024


class ConnectionClosed(ConnectionError):
    """A outra ponta encerrou a conexão."""


def recvn(sock, n: int) -> bytes:
    """Lê exatamente *n* bytes do socket ou levanta ConnectionClosed."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionClosed("conexão encerrada pela outra ponta")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_frame(sock, payload: bytes, cipher=None) -> None:
    if cipher is not None:
        payload = cipher.seal(payload)
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def recv_frame(sock, cipher=None) -> bytes:
    (size,) = struct.unpack(">I", recvn(sock, 4))
    if size > MAX_FRAME:
        raise ConnectionError(f"frame de {size} bytes excede o limite do protocolo")
    payload = recvn(sock, size)
    if cipher is not None:
        payload = cipher.open(payload)
    return payload


def send_json(sock, obj, cipher=None) -> None:
    send_frame(sock, json.dumps(obj, separators=(",", ":")).encode("utf-8"), cipher)


def recv_json(sock, cipher=None):
    return json.loads(recv_frame(sock, cipher).decode("utf-8"))
