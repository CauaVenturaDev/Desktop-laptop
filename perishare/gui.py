"""Painel gráfico (Tkinter) com os quatro serviços do PeriShare.

Tkinter faz parte da biblioteca padrão do Python no Windows; no Arch Linux
é o pacote 'tk'.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from . import __version__, config as config_mod

log = logging.getLogger("perishare.gui")


class _QueueLogHandler(logging.Handler):
    def __init__(self, output: queue.Queue):
        super().__init__()
        self._output = output
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._output.put_nowait(self.format(record))
        except queue.Full:
            pass


_SERVICES = (
    (
        "Servidor de entrada",
        "envia o teclado/mouse desta máquina",
        "perishare.inputshare.backends",
        "make_input_server",
    ),
    (
        "Cliente de entrada",
        "esta máquina é controlada pela outra",
        "perishare.inputshare.backends",
        "make_input_client",
    ),
    (
        "Emissor de áudio",
        "transmite o som desta máquina",
        "perishare.audioshare.sender",
        "AudioSender",
    ),
    (
        "Receptor de áudio",
        "toca o som remoto nos fones daqui",
        "perishare.audioshare.receiver",
        "AudioReceiver",
    ),
)


class App:
    def __init__(self, root: tk.Tk, cfg):
        self._root = root
        self._cfg = cfg
        self._instances: list = [None] * len(_SERVICES)
        self._status_vars: list[tk.StringVar] = []
        self._buttons: list[ttk.Button] = []

        root.title(f"PeriShare {__version__}")
        root.minsize(560, 420)

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        for index, (title, subtitle, _, _) in enumerate(_SERVICES):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=3)
            box = ttk.Frame(row)
            box.pack(side="left", fill="x", expand=True)
            ttk.Label(box, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
            ttk.Label(box, text=subtitle, foreground="#666666").pack(anchor="w")
            status = tk.StringVar(value="parado")
            self._status_vars.append(status)
            ttk.Label(row, textvariable=status, width=10, anchor="center").pack(
                side="left", padx=6
            )
            button = ttk.Button(
                row, text="Iniciar", width=10, command=lambda i=index: self._toggle(i)
            )
            button.pack(side="left")
            self._buttons.append(button)

        ttk.Separator(frame).pack(fill="x", pady=6)
        ttk.Label(frame, text="Log:").pack(anchor="w")
        self._log_widget = scrolledtext.ScrolledText(frame, height=10, state="disabled")
        self._log_widget.pack(fill="both", expand=True)

        self._log_queue: queue.Queue = queue.Queue(maxsize=1000)
        handler = _QueueLogHandler(self._log_queue)
        logging.getLogger("perishare").addHandler(handler)

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_logs()

    def _toggle(self, index: int) -> None:
        if self._instances[index] is None:
            self._start(index)
        else:
            self._stop(index)

    def _start(self, index: int) -> None:
        import importlib

        _, _, module_name, class_name = _SERVICES[index]
        service_cls = getattr(importlib.import_module(module_name), class_name)
        instance = service_cls(self._cfg)
        try:
            instance.start()
        except (RuntimeError, SystemExit, OSError, ValueError) as exc:
            messagebox.showerror("PeriShare", str(exc))
            self._status_vars[index].set("erro")
            return
        self._instances[index] = instance
        self._status_vars[index].set("ativo")
        self._buttons[index].configure(text="Parar")

    def _stop(self, index: int) -> None:
        instance, self._instances[index] = self._instances[index], None
        self._status_vars[index].set("parando...")
        self._buttons[index].configure(state="disabled")

        def worker():
            try:
                instance.stop()
            finally:
                self._root.after(0, self._mark_stopped, index)

        threading.Thread(target=worker, daemon=True).start()

    def _mark_stopped(self, index: int) -> None:
        self._status_vars[index].set("parado")
        self._buttons[index].configure(text="Iniciar", state="normal")

    def _poll_logs(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._log_widget.configure(state="normal")
                self._log_widget.insert("end", line + "\n")
                self._log_widget.see("end")
                self._log_widget.configure(state="disabled")
        except queue.Empty:
            pass
        self._root.after(200, self._poll_logs)

    def _on_close(self) -> None:
        for instance in self._instances:
            if instance is not None:
                try:
                    instance.stop()
                except Exception:
                    pass
        self._root.destroy()


def run_gui(config_path=None) -> int:
    try:
        cfg = config_mod.load(config_path)
    except SystemExit as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("PeriShare", str(exc))
        return 1
    root = tk.Tk()
    App(root, cfg)
    root.mainloop()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
