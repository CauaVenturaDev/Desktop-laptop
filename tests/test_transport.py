import logging
import time
import unittest

from perishare import config as config_mod
from perishare.inputshare.transport import ClientTransport, ServerTransport

log = logging.getLogger("test.transport")


class EchoServer(ServerTransport):
    def on_client_connected(self, addr):
        self._enqueue({"t": "hello", "n": 1})
        self._enqueue({"t": "kb", "down": True, "key": {"kind": "char", "v": "a"}})

    def stop(self):
        self.stop_transport()
        super().stop()


class CollectClient(ClientTransport):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.msgs = []

    def _apply(self, msg):
        self.msgs.append(msg)


def _wait(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TransportIntegrationTest(unittest.TestCase):
    def _run_with(self, encrypt):
        cfg = config_mod.Config({"general": {"secret": "segredo-comum", "encrypt": encrypt}})
        server = EchoServer(cfg, "127.0.0.1", 0, log)
        server.start_transport()
        port = server._srv_sock.getsockname()[1]
        client = CollectClient(cfg, "127.0.0.1", port, log)
        client.start_transport()
        try:
            ok = _wait(lambda: len(client.msgs) >= 2)
            self.assertTrue(ok, f"mensagens recebidas: {client.msgs}")
            self.assertIn({"t": "hello", "n": 1}, client.msgs)
            self.assertIn(
                {"t": "kb", "down": True, "key": {"kind": "char", "v": "a"}}, client.msgs
            )
        finally:
            client.stop()
            server.stop()

    def test_plaintext(self):
        self._run_with(encrypt=False)

    def test_encrypted(self):
        self._run_with(encrypt=True)

    def test_wrong_secret_never_delivers(self):
        server_cfg = config_mod.Config({"general": {"secret": "certo", "encrypt": True}})
        client_cfg = config_mod.Config({"general": {"secret": "errado", "encrypt": True}})
        server = EchoServer(server_cfg, "127.0.0.1", 0, log)
        server.start_transport()
        port = server._srv_sock.getsockname()[1]
        client = CollectClient(client_cfg, "127.0.0.1", port, log)
        client.start_transport()
        try:
            delivered = _wait(lambda: len(client.msgs) > 0, timeout=1.5)
            self.assertFalse(delivered, "mensagem não deveria ser entregue com segredo errado")
        finally:
            client.stop()
            server.stop()


if __name__ == "__main__":
    unittest.main()
