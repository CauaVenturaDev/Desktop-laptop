"""Base comum dos quatro serviços (entrada servidor/cliente, áudio envio/recepção)."""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("perishare")


class Service:
    """Serviço com start()/stop() não bloqueantes e run_forever() para a CLI."""

    name = "service"

    def __init__(self):
        self._running = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        self._running.clear()
        for thread in self._threads:
            thread.join(timeout=3)
        self._threads.clear()

    def _spawn(self, target, name: str) -> threading.Thread:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)
        return thread

    def run_forever(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            log.info("Encerrando (Ctrl+C)...")
        finally:
            self.stop()
