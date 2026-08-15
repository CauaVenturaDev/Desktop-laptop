"""Transporte de rede reutilizável para o backend evdev/uinput.

Espelha a lógica de rede já usada pelo backend pynput (``server.py`` /
``client.py``), mas isolada em classes-base com ganchos, para o backend
evdev reaproveitar sem tocar no caminho pynput que já funciona.

- ``ServerTransport``: aceita conexões, faz o handshake/cifra e envia
  mensagens de uma fila. A subclasse produz eventos chamando ``_enqueue`` e
  reage a conexão/queda pelos ganchos ``on_client_connected``/``on_client_lost``.
- ``ClientTransport``: conecta, reconecta, faz o handshake/cifra e entrega
  cada mensagem recebida a ``_apply``. Ao cair, chama ``_release_all``.
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
import time

from .. import netmsg
from ..security import HandshakeError, client_handshake, make_cipher, server_handshake
from ..service import Service

_HEARTBEAT_INTERVAL = 2.0
_RETRY_DELAY = 3.0


class ServerTransport(Service):
    def __init__(self, cfg, listen_host: str, port: int, logger: logging.Logger):
        super().__init__()
        self._cfg = cfg
        self._listen_host = listen_host
        self._port = port
        self._log = logger
        self._srv_sock: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._cipher = None
        self._conn_lock = threading.Lock()
        self._send_q: queue.Queue = queue.Queue(maxsize=1024)
        self._last_send = 0.0

    def start_transport(self) -> None:
        self._cfg.require_secret()
        self._srv_sock = socket.create_server((self._listen_host, self._port))
        self._srv_sock.settimeout(1.0)
        self._running.set()
        self._spawn(self._accept_loop, "srv-accept")
        self._spawn(self._send_loop, "srv-send")

    def stop_transport(self) -> None:
        self._running.clear()
        if self._srv_sock is not None:
            try:
                self._srv_sock.close()
            except OSError:
                pass
        self._drop_client("serviço encerrado")

    # ---- ganchos para a subclasse ----
    def on_client_connected(self, addr) -> None:  # pragma: no cover - trivial
        pass

    def on_client_lost(self) -> None:  # pragma: no cover - trivial
        pass

    # ---- rede ----
    def _accept_loop(self) -> None:
        while self._running.is_set():
            try:
                conn, addr = self._srv_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(10)
                session_key = server_handshake(conn, self._cfg.secret_bytes)
                cipher = make_cipher(session_key, is_server=True, enabled=self._cfg.encrypt)
                conn.settimeout(None)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except (HandshakeError, OSError) as exc:
                self._log.warning("Conexão de %s rejeitada: %s", addr, exc)
                conn.close()
                continue
            except RuntimeError as exc:
                self._log.error("%s", exc)
                conn.close()
                continue
            with self._conn_lock:
                old = self._conn
                self._conn, self._cipher = conn, cipher
            if old is not None:
                try:
                    old.close()
                except OSError:
                    pass
            self._log.info("Cliente conectado: %s:%d", addr[0], addr[1])
            self.on_client_connected(addr)
            threading.Thread(
                target=self._conn_reader, args=(conn,), name="srv-reader", daemon=True
            ).start()

    def _conn_reader(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        while self._running.is_set():
            try:
                if not conn.recv(4096):
                    break
            except socket.timeout:
                continue
            except OSError:
                break
        with self._conn_lock:
            still_current = self._conn is conn
        if still_current:
            self._drop_client("cliente desconectou")

    def _drop_client(self, reason: str) -> None:
        with self._conn_lock:
            conn, self._conn, self._cipher = self._conn, None, None
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
            self._log.info("Conexão encerrada (%s).", reason)
            self.on_client_lost()

    def _enqueue(self, msg: dict) -> None:
        try:
            self._send_q.put_nowait(msg)
        except queue.Full:
            try:
                self._send_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._send_q.put_nowait(msg)
            except queue.Full:
                pass

    def _send_loop(self) -> None:
        while self._running.is_set():
            try:
                msg = self._send_q.get(timeout=0.2)
            except queue.Empty:
                if time.monotonic() - self._last_send > _HEARTBEAT_INTERVAL:
                    self._transmit({"t": "ping"})
                continue
            self._transmit(msg)

    def _transmit(self, msg: dict) -> None:
        with self._conn_lock:
            conn, cipher = self._conn, self._cipher
        if conn is None:
            return
        try:
            netmsg.send_json(conn, msg, cipher)
            self._last_send = time.monotonic()
        except OSError:
            self._drop_client("erro de envio")

    def _has_client(self) -> bool:
        with self._conn_lock:
            return self._conn is not None


class ClientTransport(Service):
    def __init__(self, cfg, server_host: str, port: int, logger: logging.Logger):
        super().__init__()
        self._cfg = cfg
        self._server_host = server_host
        self._port = port
        self._log = logger

    def start_transport(self) -> None:
        self._cfg.require_secret()
        self._running.set()
        self._spawn(self._run_loop, "client")

    # ---- a subclasse implementa a injeção ----
    def _apply(self, msg: dict) -> None:
        raise NotImplementedError

    def _release_all(self) -> None:  # pragma: no cover - trivial
        pass

    # ---- rede ----
    def _run_loop(self) -> None:
        while self._running.is_set():
            sock = None
            try:
                sock = socket.create_connection((self._server_host, self._port), timeout=5)
                sock.settimeout(10)
                session_key = client_handshake(sock, self._cfg.secret_bytes)
                cipher = make_cipher(session_key, is_server=False, enabled=self._cfg.encrypt)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._log.info("Conectado ao servidor de entrada.")
                self._receive(sock, cipher)
            except HandshakeError as exc:
                self._log.error("Falha de autenticação: %s", exc)
            except (ConnectionError, OSError) as exc:
                self._log.info("Servidor de entrada indisponível (%s).", exc)
            except RuntimeError as exc:
                self._log.error("%s", exc)
                break
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self._release_all()
            deadline = time.monotonic() + _RETRY_DELAY
            while self._running.is_set() and time.monotonic() < deadline:
                time.sleep(0.2)

    def _receive(self, sock: socket.socket, cipher) -> None:
        sock.settimeout(1.0)
        idle = 0.0
        while self._running.is_set():
            try:
                msg = netmsg.recv_json(sock, cipher)
            except socket.timeout:
                idle += 1.0
                if idle > 10.0:
                    raise ConnectionError("servidor silencioso há 10 s")
                continue
            idle = 0.0
            self._apply(msg)
