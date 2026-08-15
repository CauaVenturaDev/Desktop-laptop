import unittest

try:
    from evdev import ecodes

    from perishare.inputshare import keymap

    HAVE_EVDEV = True
except Exception:
    HAVE_EVDEV = False


@unittest.skipUnless(HAVE_EVDEV, "pacote evdev não instalado")
class KeymapTest(unittest.TestCase):
    def test_char_roundtrip_us_layout(self):
        cases = [
            (ecodes.KEY_A, False, "a"),
            (ecodes.KEY_A, True, "A"),
            (ecodes.KEY_1, False, "1"),
            (ecodes.KEY_1, True, "!"),
            (ecodes.KEY_SLASH, False, "/"),
            (ecodes.KEY_SLASH, True, "?"),
            (ecodes.KEY_BACKSLASH, True, "|"),
        ]
        for code, shift, expected in cases:
            wire = keymap.key_event_to_wire(code, shift)
            self.assertEqual(wire, {"kind": "char", "v": expected})
            self.assertEqual(keymap.wire_to_keycode(wire), code)

    def test_special_roundtrip(self):
        cases = [
            (ecodes.KEY_ENTER, "enter"),
            (ecodes.KEY_ESC, "esc"),
            (ecodes.KEY_LEFTCTRL, "ctrl_l"),
            (ecodes.KEY_F12, "f12"),
            (ecodes.KEY_UP, "up"),
        ]
        for code, name in cases:
            wire = keymap.key_event_to_wire(code, False)
            self.assertEqual(wire, {"kind": "special", "v": name})
            self.assertEqual(keymap.wire_to_keycode(wire), code)

    def test_enter_reverse_prefers_main_key(self):
        # "enter" existe no teclado principal e no numérico; o reverso deve
        # escolher o principal.
        self.assertEqual(keymap.wire_to_keycode({"kind": "special", "v": "enter"}),
                         ecodes.KEY_ENTER)

    def test_buttons(self):
        self.assertTrue(keymap.is_button(ecodes.BTN_LEFT))
        self.assertFalse(keymap.is_button(ecodes.KEY_A))
        self.assertEqual(keymap.button_code_to_name(ecodes.BTN_RIGHT), "right")
        self.assertEqual(keymap.button_name_to_code("middle"), ecodes.BTN_MIDDLE)

    def test_unknown_char_has_no_keycode(self):
        self.assertIsNone(keymap.wire_to_keycode({"kind": "char", "v": "á"}))

    def test_hotkey_parse(self):
        tokens = keymap.parse_hotkey_to_evdev("<ctrl>+<alt>+<f12>")
        self.assertEqual(len(tokens), 3)
        self.assertIn(ecodes.KEY_LEFTCTRL, tokens[0])
        self.assertIn(ecodes.KEY_RIGHTCTRL, tokens[0])
        self.assertIn(ecodes.KEY_LEFTALT, tokens[1])
        self.assertEqual(tokens[2], {ecodes.KEY_F12})

    def test_hotkey_parse_single_letter(self):
        tokens = keymap.parse_hotkey_to_evdev("<ctrl>+q")
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[1], {ecodes.KEY_Q})

    def test_all_key_codes_nonempty_and_ints(self):
        codes = keymap.all_key_codes()
        self.assertGreater(len(codes), 50)
        self.assertTrue(all(isinstance(c, int) for c in codes))


if __name__ == "__main__":
    unittest.main()
