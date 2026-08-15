import socket
import threading
import unittest

from perishare import netmsg
from perishare.security import (
    HandshakeError,
    client_handshake,
    make_cipher,
    server_handshake,
)

try:
    import cryptography  # noqa: F401

    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


def _run_handshake(server_secret: bytes, client_secret: bytes):
    a, b = socket.socketpair()
    results = {}

    def server():
        try:
            results["server"] = server_handshake(a, server_secret)
        except Exception as exc:
            results["server_error"] = exc
            a.close()  # desbloqueia o cliente, que aguarda a resposta final

    thread = threading.Thread(target=server)
    thread.start()
    try:
        results["client"] = client_handshake(b, client_secret)
    except Exception as exc:
        results["client_error"] = exc
    thread.join()
    a.close()
    b.close()
    return results


class HandshakeTest(unittest.TestCase):
    def test_matching_secret_derives_same_key(self):
        results = _run_handshake(b"segredo-compartilhado", b"segredo-compartilhado")
        self.assertNotIn("server_error", results)
        self.assertNotIn("client_error", results)
        self.assertEqual(results["server"], results["client"])
        self.assertEqual(len(results["server"]), 32)

    def test_wrong_secret_rejected(self):
        results = _run_handshake(b"segredo-correto", b"segredo-errado")
        self.assertIn("server_error", results)
        self.assertIsInstance(results["server_error"], HandshakeError)

    def test_sessions_have_distinct_keys(self):
        first = _run_handshake(b"mesmo-segredo", b"mesmo-segredo")
        second = _run_handshake(b"mesmo-segredo", b"mesmo-segredo")
        self.assertNotEqual(first["server"], second["server"])


@unittest.skipUnless(HAVE_CRYPTO, "pacote cryptography não instalado")
class CipherTest(unittest.TestCase):
    def _pair(self):
        key = b"k" * 32
        return (
            make_cipher(key, is_server=True, enabled=True),
            make_cipher(key, is_server=False, enabled=True),
        )

    def test_roundtrip_both_directions(self):
        server, client = self._pair()
        for i in range(20):
            message = f"evento {i}".encode()
            self.assertEqual(client.open(server.seal(message)), message)
            self.assertEqual(server.open(client.seal(message)), message)

    def test_tampering_detected(self):
        server, client = self._pair()
        sealed = bytearray(server.seal(b"dados"))
        sealed[-1] ^= 0xFF
        with self.assertRaises(ConnectionError):
            client.open(bytes(sealed))

    def test_cipher_over_socket_frames(self):
        server, client = self._pair()
        a, b = socket.socketpair()
        try:
            netmsg.send_json(a, {"t": "mm", "dx": 3, "dy": -7}, server)
            self.assertEqual(netmsg.recv_json(b, client), {"t": "mm", "dx": 3, "dy": -7})
        finally:
            a.close()
            b.close()

    def test_disabled_returns_none(self):
        self.assertIsNone(make_cipher(b"k" * 32, is_server=True, enabled=False))


if __name__ == "__main__":
    unittest.main()
