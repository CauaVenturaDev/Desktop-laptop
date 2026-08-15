import tempfile
import unittest
from pathlib import Path

from perishare import config as config_mod


class ConfigTest(unittest.TestCase):
    def test_template_generates_unique_secret_and_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = Path(tmp) / "a" / "config.toml"
            path_b = Path(tmp) / "b" / "config.toml"
            config_mod.write_template(path_a)
            config_mod.write_template(path_b)
            cfg_a = config_mod.load(path_a)
            cfg_b = config_mod.load(path_b)
            self.assertEqual(len(cfg_a.secret), 64)
            self.assertNotEqual(cfg_a.secret, cfg_b.secret)
            self.assertTrue(cfg_a.encrypt)
            self.assertEqual(cfg_a.input_port, 42800)
            self.assertEqual(cfg_a.audio_port, 42801)
            self.assertEqual(cfg_a.toggle_hotkey, "<ctrl>+<alt>+<end>")

    def test_existing_file_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config_mod.write_template(path)
            original = path.read_text(encoding="utf-8")
            with self.assertRaises(FileExistsError):
                config_mod.write_template(path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            config_mod.write_template(path, force=True)
            self.assertNotEqual(path.read_text(encoding="utf-8"), original)

    def test_partial_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '[general]\nsecret = "abc"\n\n[input]\nserver_host = "10.0.0.2"\n',
                encoding="utf-8",
            )
            cfg = config_mod.load(path)
            self.assertEqual(cfg.secret, "abc")
            self.assertEqual(cfg.input_server_host, "10.0.0.2")
            self.assertEqual(cfg.input_port, 42800)
            self.assertEqual(cfg.audio_samplerate, 48000)
            self.assertEqual(cfg.audio_blocksize, 480)

    def test_missing_secret_raises_friendly_error(self):
        cfg = config_mod.Config({"general": {"secret": ""}})
        with self.assertRaises(SystemExit):
            cfg.require_secret()

    def test_missing_file_raises_friendly_error(self):
        with self.assertRaises(SystemExit):
            config_mod.load("/caminho/inexistente/config.toml")


if __name__ == "__main__":
    unittest.main()
