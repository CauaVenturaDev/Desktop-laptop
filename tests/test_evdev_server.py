import unittest

try:
    from evdev import ecodes

    from perishare.inputshare import keymap
    from perishare.inputshare.evdev_server import EvdevInputServer

    HAVE_EVDEV = True
except Exception:
    HAVE_EVDEV = False

from perishare import config as config_mod


class FakeDevice:
    def __init__(self, name="fake"):
        self.name = name
        self.grabbed = False
        self.closed = False
        self.grab_calls = 0
        self.ungrab_calls = 0

    def grab(self):
        if self.grabbed:
            raise OSError("já capturado")
        self.grabbed = True
        self.grab_calls += 1

    def ungrab(self):
        if not self.grabbed:
            raise OSError("não capturado")
        self.grabbed = False
        self.ungrab_calls += 1

    def close(self):
        self.closed = True


class FakeEvent:
    def __init__(self, etype, code, value):
        self.type = etype
        self.code = code
        self.value = value


def _key(code, value):
    return FakeEvent(ecodes.EV_KEY, code, value)


@unittest.skipUnless(HAVE_EVDEV, "pacote evdev não instalado")
class EvdevServerStateMachineTest(unittest.TestCase):
    def _make(self, grab=True):
        cfg = config_mod.Config(
            {"general": {"secret": "s"}, "input": {"grab": grab}}
        )
        server = EvdevInputServer(cfg)
        server._hotkey_tokens = keymap.parse_hotkey_to_evdev(cfg.toggle_hotkey)
        server._devices = [FakeDevice("kbd"), FakeDevice("mouse")]
        self._has_client = [True]
        server._has_client = lambda: self._has_client[0]
        self.captured = []
        server._enqueue = self.captured.append
        return server

    def _feed(self, server, event):
        server._handle_event(event, ecodes)

    def _toggle_hotkey(self, server):
        self._feed(server, _key(ecodes.KEY_LEFTCTRL, 1))
        self._feed(server, _key(ecodes.KEY_LEFTALT, 1))
        self._feed(server, _key(ecodes.KEY_END, 1))

    def _release_hotkey(self, server):
        # Como no uso real: o usuário solta o atalho antes de continuar.
        self._feed(server, _key(ecodes.KEY_END, 0))
        self._feed(server, _key(ecodes.KEY_LEFTALT, 0))
        self._feed(server, _key(ecodes.KEY_LEFTCTRL, 0))

    def test_local_mode_does_not_forward_or_grab(self):
        server = self._make()
        self._feed(server, _key(ecodes.KEY_A, 1))
        self._feed(server, _key(ecodes.KEY_A, 0))
        self.assertEqual(self.captured, [])
        self.assertFalse(any(d.grabbed for d in server._devices))

    def test_toggle_grabs_and_forwards(self):
        server = self._make()
        self._toggle_hotkey(server)
        self.assertTrue(server._remote)
        self.assertTrue(all(d.grabbed for d in server._devices))
        # O atalho em si não é encaminhado.
        self.assertEqual(self.captured, [])
        self._release_hotkey(server)
        self.assertEqual(self.captured, [])

        # Digitar no modo remoto encaminha com o código evdev bruto.
        self._feed(server, _key(ecodes.KEY_A, 1))
        self.assertEqual(
            self.captured[-1],
            {"t": "kb", "down": True, "key": {"kind": "char", "v": "a"},
             "code": ecodes.KEY_A},
        )
        self._feed(server, _key(ecodes.KEY_A, 0))
        self.assertEqual(self.captured[-1]["down"], False)

    def test_hotkey_modifiers_not_released_on_remote(self):
        server = self._make()
        self._toggle_hotkey(server)
        self.captured.clear()
        # Soltar os modificadores do atalho não deve virar "release" na remota.
        self._feed(server, _key(ecodes.KEY_END, 0))
        self._feed(server, _key(ecodes.KEY_LEFTALT, 0))
        self._feed(server, _key(ecodes.KEY_LEFTCTRL, 0))
        self.assertEqual(self.captured, [])

    def test_mouse_move_and_button(self):
        server = self._make()
        self._toggle_hotkey(server)
        self._release_hotkey(server)
        self.captured.clear()
        self._feed(server, FakeEvent(ecodes.EV_REL, ecodes.REL_X, 5))
        self._feed(server, FakeEvent(ecodes.EV_REL, ecodes.REL_Y, -3))
        self._feed(server, FakeEvent(ecodes.EV_SYN, ecodes.SYN_REPORT, 0))
        self.assertIn({"t": "mm", "dx": 5, "dy": -3}, self.captured)
        self._feed(server, _key(ecodes.BTN_LEFT, 1))
        self.assertEqual(self.captured[-1], {"t": "mb", "b": "left", "down": True})

    def test_client_lost_releases_and_ungrabs(self):
        server = self._make()
        self._toggle_hotkey(server)
        self._release_hotkey(server)
        self._feed(server, _key(ecodes.KEY_A, 1))  # tecla pressionada no remoto
        self.captured.clear()
        server.on_client_lost()
        self.assertFalse(server._remote)
        self.assertFalse(any(d.grabbed for d in server._devices))
        # A tecla pressionada foi solta na remota.
        self.assertTrue(
            any(m.get("t") == "kb" and m.get("down") is False for m in self.captured)
        )

    def test_toggle_without_client_stays_local(self):
        server = self._make()
        self._has_client[0] = False
        self._toggle_hotkey(server)
        self.assertFalse(server._remote)
        self.assertFalse(any(d.grabbed for d in server._devices))

    def test_grab_false_never_grabs(self):
        server = self._make(grab=False)
        self._toggle_hotkey(server)
        self.assertTrue(server._remote)
        self.assertFalse(any(d.grabbed for d in server._devices))
        self._release_hotkey(server)
        # Ainda encaminha eventos, só não captura com exclusividade.
        self._feed(server, _key(ecodes.KEY_A, 1))
        self.assertEqual(self.captured[-1]["code"], ecodes.KEY_A)

    def test_stop_ungrabs_and_closes(self):
        server = self._make()
        self._toggle_hotkey(server)
        self.assertTrue(all(d.grabbed for d in server._devices))
        devices = list(server._devices)
        server.stop()
        self.assertTrue(all(not d.grabbed for d in devices))
        self.assertTrue(all(d.closed for d in devices))

    def test_toggle_back_to_local_ungrabs(self):
        server = self._make()
        self._toggle_hotkey(server)
        self.assertTrue(server._remote)
        # Solta o atalho e aciona de novo para voltar ao local.
        self._feed(server, _key(ecodes.KEY_END, 0))
        self._feed(server, _key(ecodes.KEY_LEFTALT, 0))
        self._feed(server, _key(ecodes.KEY_LEFTCTRL, 0))
        self._toggle_hotkey(server)
        self.assertFalse(server._remote)
        self.assertFalse(any(d.grabbed for d in server._devices))


if __name__ == "__main__":
    unittest.main()
