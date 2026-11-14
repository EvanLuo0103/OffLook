"""Pure shortcut parsing and atomic configuration persistence regressions."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from offlook.core import HotkeySpec, parse_hotkey
from offlook.core.config import ConfigManager, PreviewConfig
from offlook.core.errors import ConfigError, HotkeyError
from offlook.platforms.windows_hotkey import HotkeyListener


class HotkeyParserTests(unittest.TestCase):
    """Check the deliberately limited grammar independently of Windows registration."""

    def test_canonical_order_and_win32_values(self) -> None:
        self.assertEqual(parse_hotkey(" shift + CTRL + p "), HotkeySpec("Ctrl+Shift+P", 6, 0x50))
        self.assertEqual(parse_hotkey("alt+ctrl+shift+space"), HotkeySpec("Ctrl+Alt+Shift+Space", 7, 0x20))
        for number in (*range(1, 4), *range(5, 12)):
            with self.subTest(number=number):
                self.assertEqual(parse_hotkey(f"Alt+f{number}"), HotkeySpec(f"Alt+F{number}", 1, 0x6F + number))
        for key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            with self.subTest(key=key):
                self.assertEqual(parse_hotkey(f"ctrl+{key.lower()}"), HotkeySpec(f"Ctrl+{key}", 2, ord(key)))
        self.assertEqual(parse_hotkey("Ctrl+Alt+F4"), HotkeySpec("Ctrl+Alt+F4", 3, 0x73))

    def test_invalid_and_reserved_shortcuts(self) -> None:
        values = (
            "", "  ", None, 5, True, "Ctrl++P", "+Ctrl+P", "Ctrl+P+", "Ctrl+Ctrl+P",
            "Alt+alt+P", "Shift+Shift+Ctrl+P", "P", "Space", "Shift+P", "Ctrl", "Alt+Shift",
            "Ctrl+A+B", "Ctrl+F12", "Alt+F4", "Alt+Space",
            "Ctrl+F0", "Ctrl+F01", "Ctrl+F13", "Ctrl+Enter", "Ctrl+空白",
            "Ctrl+é", "Control+P", "Ctrl+ ",
        )
        for value in values:
            with self.subTest(value=value), self.assertRaises(HotkeyError):
                parse_hotkey(value)
        for name in ("Win", "Windows", "Meta", "Super", "LWin", "RWin"):
            with self.subTest(name=name), self.assertRaises(HotkeyError):
                parse_hotkey(f"Ctrl+{name}+P")

    def test_spec_and_listener_combo_are_readonly(self) -> None:
        spec = parse_hotkey("Ctrl+P")
        with self.assertRaises(FrozenInstanceError):
            spec.canonical = "Alt+P"
        listener = HotkeyListener("shift+ctrl+p")
        self.assertEqual(listener.combo, "Ctrl+Shift+P")
        self.assertTrue(listener.is_stopped)
        self.assertEqual(listener.poll(), [])
        with self.assertRaises(AttributeError):
            listener.combo = "Alt+P"
        with self.assertRaises(HotkeyError):
            HotkeyListener("Win+P")

    def test_thread_start_error_retains_combo(self) -> None:
        listener = HotkeyListener("Ctrl+Alt+P")
        with patch("offlook.platforms.windows_hotkey.threading.Thread.start", side_effect=RuntimeError("unavailable")):
            listener.start()
        events = listener.poll()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["combo"], "Ctrl+Alt+P")
        self.assertIn("unavailable", events[0]["message"])
        self.assertTrue(listener.is_stopped)
        listener.stop()


class HotkeyConfigTests(unittest.TestCase):
    """Keep old JSON compatible and invalid drafts away from the saved configuration."""

    def test_old_json_defaults_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            old = '{"hotkey_enabled": true, "always_on_top": false}'
            path.write_text(old, encoding="utf-8")
            self.assertEqual(ConfigManager(path).load().hotkey, "Ctrl+Space")
            self.assertEqual(path.read_text(encoding="utf-8"), old)

    def test_canonical_shortcut_roundtrips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            config = replace(manager.current, hotkey=" shift + CTRL + p ")
            manager.update(config, persist=True)
            self.assertEqual(config.hotkey, "Ctrl+Shift+P")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["hotkey"], "Ctrl+Shift+P")
            self.assertEqual(ConfigManager(path).load(), config)

    def test_invalid_shortcut_cannot_replace_saved_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            config = PreviewConfig(hotkey="Ctrl+Alt+P")
            manager.update(config, persist=True)
            saved = path.read_bytes()
            with self.assertRaises(ConfigError) as caught:
                manager.update(replace(config, hotkey="Win+P"), persist=True)
            self.assertIsInstance(caught.exception.__cause__, HotkeyError)
            self.assertEqual(manager.current, config)
            self.assertEqual(path.read_bytes(), saved)
            self.assertEqual(ConfigManager(path).load(), config)

    def test_invalid_json_shortcut_retains_current_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            config = PreviewConfig(hotkey="Alt+P")
            manager.update(config)
            path.write_text('{"hotkey": "F12"}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                manager.load()
            self.assertEqual(manager.current, config)
