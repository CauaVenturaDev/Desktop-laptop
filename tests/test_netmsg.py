import socket
import threading
import unittest

from perishare import netmsg


class NetmsgTest(unittest.TestCase):
    def test_json_roundtrip(self):
        a, b = socket.socketpair()
        try:
            payload = {"t": "kb", "down": True, "key": {"kind": "char", "v": "á"}}
            netmsg.send_json(a, payload)
            self.assertEqual(netmsg.recv_json(b), payload)
        finally:
            a.close()
            b.close()

    def test_multiple_frames_in_order(self):
        a, b = socket.socketpair()
        try:
            for i in range(50):
                netmsg.send_frame(a, bytes([i]) * (i + 1))
            for i in range(50):
                self.assertEqual(netmsg.recv_frame(b), bytes([i]) * (i + 1))
        finally:
            a.close()
            b.close()

    def test_closed_connection_raises(self):
        a, b = socket.socketpair()
        a.close()
        try:
            with self.assertRaises(netmsg.ConnectionClosed):
                netmsg.recv_frame(b)
        finally:
            b.close()

    def test_oversized_frame_rejected(self):
        a, b = socket.socketpair()
        try:
            a.sendall((netmsg.MAX_FRAME + 1).to_bytes(4, "big"))
            with self.assertRaises(ConnectionError):
                netmsg.recv_frame(b)
        finally:
            a.close()
            b.close()

    def test_concurrent_send_and_recv(self):
        a, b = socket.socketpair()
        frames = [f"mensagem {i}".encode() for i in range(200)]

        def sender():
            for frame in frames:
                netmsg.send_frame(a, frame)

        thread = threading.Thread(target=sender)
        thread.start()
        try:
            received = [netmsg.recv_frame(b) for _ in frames]
            self.assertEqual(received, frames)
        finally:
            thread.join()
            a.close()
            b.close()


if __name__ == "__main__":
    unittest.main()
