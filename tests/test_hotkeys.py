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
        for values in (
            {"hotkey_enabled": True, "always_on_top": False},
            {"hotkey_enabled": False, "hotkey": "Alt+P"},
        ):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                old = json.dumps(values).encode("utf-8")
                path.write_bytes(old)
                config = ConfigManager(path).load()
                self.assertEqual(config.hotkey, values.get("hotkey", "Ctrl+Space"))
                self.assertEqual(config.search_hotkey, "Ctrl+Q")
                self.assertEqual(config.diff_hotkey, "Ctrl+Alt+D")
                self.assertEqual(path.read_bytes(), old)

    def test_canonical_shortcut_roundtrips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            config = replace(
                manager.current,
                hotkey=" shift + CTRL + p ",
                search_hotkey=" alt + ctrl + s ",
                diff_hotkey=" shift + alt + d ",
            )
            manager.update(config, persist=True)
            saved = json.loads(path.read_text(encoding="utf-8"))
            for field, canonical in (
                ("hotkey", "Ctrl+Shift+P"),
                ("search_hotkey", "Ctrl+Alt+S"),
                ("diff_hotkey", "Alt+Shift+D"),
            ):
                self.assertEqual(getattr(config, field), canonical)
                self.assertEqual(saved[field], canonical)
            self.assertEqual(ConfigManager(path).load(), config)

    def test_invalid_shortcut_cannot_replace_saved_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            config = PreviewConfig(hotkey="Ctrl+Alt+P")
            manager.update(config, persist=True)
            saved = path.read_bytes()
            for field in ("hotkey", "search_hotkey", "diff_hotkey"):
                with self.subTest(field=field), self.assertRaises(ConfigError) as caught:
                    manager.update(replace(config, **{field: "Win+P"}), persist=True)
                self.assertIsInstance(caught.exception.__cause__, HotkeyError)
                self.assertIn(field, str(caught.exception))
                self.assertEqual(manager.current, config)
                self.assertEqual(path.read_bytes(), saved)
                self.assertEqual(ConfigManager(path).load(), config)

    def test_invalid_json_shortcut_retains_current_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            config = PreviewConfig(hotkey="Alt+P")
            manager.update(config)
            for field in ("hotkey", "search_hotkey", "diff_hotkey"):
                with self.subTest(field=field):
                    invalid = json.dumps({field: "F12"}).encode("utf-8")
                    path.write_bytes(invalid)
                    with self.assertRaises(ConfigError) as caught:
                        manager.load()
                    self.assertIsInstance(caught.exception.__cause__, HotkeyError)
                    self.assertIn(field, str(caught.exception))
                    self.assertEqual(manager.current, config)
                    self.assertEqual(path.read_bytes(), invalid)

    def test_pairwise_duplicates_never_replace_or_save_config(self) -> None:
        pairs = (
            ("hotkey", "search_hotkey"),
            ("hotkey", "diff_hotkey"),
            ("search_hotkey", "diff_hotkey"),
        )
        for enabled in (True, False):
            for first, second in pairs:
                with self.subTest(enabled=enabled, fields=(first, second)):
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "config.json"
                        manager = ConfigManager(path)
                        config = replace(manager.current, hotkey_enabled=enabled)
                        manager.update(config, persist=True)
                        saved = path.read_bytes()
                        changes = {first: "shift + ctrl + p", second: "CTRL+SHIFT+P"}
                        message = (
                            "Shortcut combinations must be different: "
                            f"{first} and {second} both use Ctrl+Shift+P"
                        )
                        with self.assertRaises(ConfigError) as caught:
                            manager.update(replace(config, **changes), persist=True)
                        self.assertEqual(str(caught.exception), message)
                        self.assertEqual(manager.current, config)
                        self.assertEqual(path.read_bytes(), saved)
                        self.assertEqual(ConfigManager(path).load(), config)

    def test_legacy_duplicate_json_names_conflicting_fields_without_reset(self) -> None:
        for first, second in (
            ("hotkey", "search_hotkey"),
            ("hotkey", "diff_hotkey"),
            ("search_hotkey", "diff_hotkey"),
        ):
            for enabled in (True, False):
                with self.subTest(enabled=enabled, fields=(first, second)):
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "config.json"
                        manager = ConfigManager(path)
                        previous = manager.current
                        invalid = json.dumps({
                            "hotkey_enabled": enabled,
                            first: "alt + shift + p",
                            second: "SHIFT+ALT+P",
                        }).encode("utf-8")
                        path.write_bytes(invalid)
                        with self.assertRaises(ConfigError) as caught:
                            manager.load()
                        self.assertEqual(
                            str(caught.exception),
                            "Shortcut combinations must be different: "
                            f"{first} and {second} both use Alt+Shift+P",
                        )
                        self.assertEqual(manager.current, previous)
                        self.assertEqual(path.read_bytes(), invalid)

    def test_default_combinations_can_move_to_another_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigManager(path)
            config = replace(
                manager.current,
                hotkey="Ctrl+Q",
                search_hotkey="Ctrl+Alt+D",
                diff_hotkey="Ctrl+Space",
            )
            manager.update(config, persist=True)
            self.assertEqual(ConfigManager(path).load(), config)
