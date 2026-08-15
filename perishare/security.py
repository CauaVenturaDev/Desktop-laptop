"""Autenticação mútua e cifragem da sessão.

As duas máquinas compartilham um segredo (gerado por ``perishare init`` e
copiado para ambas). O handshake autentica os dois lados com HMAC-SHA256
sobre nonces aleatórios — sem o segredo, nenhum host da rede consegue
injetar teclado/mouse nem ouvir o áudio. Depois do handshake, uma chave de
sessão é derivada (HKDF-SHA256) e, com ``encrypt = true``, todos os frames
trafegam cifrados com AES-256-GCM.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading

PROTO_MAGIC = b"PSHR1\n"
_NONCE_LEN = 16
_MAC_LEN = 32


class HandshakeError(Exception):
    """Falha de autenticação ou protocolo durante o handshake."""


def _recvn(sock, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        try:
            chunk = sock.recv(remaining)
        except OSError as exc:
            raise HandshakeError(f"erro de rede durante o handshake: {exc}") from exc
        if not chunk:
            raise HandshakeError("conexão encerrada durante o handshake")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _hkdf_sha256(secret: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    prk = hmac.digest(salt, secret, hashlib.sha256)
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.digest(prk, block + info + bytes([counter]), hashlib.sha256)
        out += block
        counter += 1
    return out[:length]


def server_handshake(sock, secret: bytes) -> bytes:
    """Lado que aceita conexões. Retorna a chave de sessão."""
    nonce_s = os.urandom(_NONCE_LEN)
    sock.sendall(PROTO_MAGIC + nonce_s)
    reply = _recvn(sock, _NONCE_LEN + _MAC_LEN)
    nonce_c, mac_c = reply[:_NONCE_LEN], reply[_NONCE_LEN:]
    expected = hmac.digest(secret, nonce_s + nonce_c + b"client", hashlib.sha256)
    if not hmac.compare_digest(mac_c, expected):
        raise HandshakeError("segredo incorreto (autenticação do cliente falhou)")
    sock.sendall(hmac.digest(secret, nonce_c + nonce_s + b"server", hashlib.sha256))
    return _hkdf_sha256(secret, nonce_s + nonce_c, b"perishare-session")


def client_handshake(sock, secret: bytes) -> bytes:
    """Lado que se conecta. Retorna a chave de sessão."""
    header = _recvn(sock, len(PROTO_MAGIC) + _NONCE_LEN)
    if header[: len(PROTO_MAGIC)] != PROTO_MAGIC:
        raise HandshakeError("resposta inválida do servidor (protocolo desconhecido)")
    nonce_s = header[len(PROTO_MAGIC):]
    nonce_c = os.urandom(_NONCE_LEN)
    mac_c = hmac.digest(secret, nonce_s + nonce_c + b"client", hashlib.sha256)
    sock.sendall(nonce_c + mac_c)
    mac_s = _recvn(sock, _MAC_LEN)
    expected = hmac.digest(secret, nonce_c + nonce_s + b"server", hashlib.sha256)
    if not hmac.compare_digest(mac_s, expected):
        raise HandshakeError("segredo incorreto (autenticação do servidor falhou)")
    return _hkdf_sha256(secret, nonce_s + nonce_c, b"perishare-session")


class Cipher:
    """AES-256-GCM com nonce de contador, um contador por direção.

    O TCP garante ordem de entrega, então os contadores de envio e recepção
    das duas pontas avançam em sincronia; um frame reordenado, repetido ou
    adulterado falha na autenticação do GCM.
    """

    def __init__(self, key: bytes, send_label: bytes, recv_label: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aead = AESGCM(key)
        self._send_label = send_label
        self._recv_label = recv_label
        self._send_ctr = 0
        self._recv_ctr = 0
        self._send_lock = threading.Lock()

    def seal(self, data: bytes) -> bytes:
        with self._send_lock:
            ctr = self._send_ctr
            self._send_ctr += 1
        nonce = self._send_label + ctr.to_bytes(8, "big")
        return self._aead.encrypt(nonce, data, None)

    def open(self, data: bytes) -> bytes:
        nonce = self._recv_label + self._recv_ctr.to_bytes(8, "big")
        self._recv_ctr += 1
        try:
            return self._aead.decrypt(nonce, data, None)
        except Exception as exc:
            raise ConnectionError(
                "falha ao decifrar mensagem (segredos divergentes ou dados corrompidos)"
            ) from exc


def make_cipher(session_key: bytes, is_server: bool, enabled: bool):
    """Cria o cifrador da sessão, ou ``None`` com cifragem desativada."""
    if not enabled:
        return None
    try:
        import cryptography  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "encrypt = true na configuração, mas o pacote Python 'cryptography' "
            "não está instalado. Instale-o (pacman -S python-cryptography ou "
            "pip install cryptography) ou defina encrypt = false."
        ) from exc
    if is_server:
        return Cipher(session_key, send_label=b"srv:", recv_label=b"cli:")
    return Cipher(session_key, send_label=b"cli:", recv_label=b"srv:")
