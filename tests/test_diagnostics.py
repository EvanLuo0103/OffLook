"""CLI configuration failures must not enter GUI or native shortcut startup."""

import builtins
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from offlook.cli import main


@unittest.skipUnless(sys.platform == "win32", "OffLook CLI requires Windows")
class SearchShortcutDiagnosticConfigTests(unittest.TestCase):
    def test_invalid_explicit_config_exits_without_desktop_or_registration(self) -> None:
        cases = (
            ("malformed JSON", '{"search_hotkey":', "valid UTF-8 JSON"),
            ("missing file", None, "does not exist"),
            ("invalid search key", '{"search_hotkey": "Win+Q"}', "search_hotkey"),
            (
                "duplicate combinations",
                '{"hotkey_enabled": false, "search_hotkey": "ctrl+space"}',
                "hotkey and search_hotkey both use Ctrl+Space",
            ),
            (
                "duplicate comparison key",
                '{"search_hotkey": "Alt+P", "diff_hotkey": "alt+p"}',
                "search_hotkey and diff_hotkey both use Alt+P",
            ),
            (
                "duplicate JSON keys",
                '{"search_hotkey": "Alt+P", "search_hotkey": "Alt+Q"}',
                "Duplicate configuration key: search_hotkey",
            ),
        )
        original_import = builtins.__import__

        def import_without_gui(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "tkinter" or name.startswith("tkinter.") or name == "offlook.gui":
                raise AssertionError("Invalid diagnostic config must not import a GUI")
            return original_import(name, globals, locals, fromlist, level)

        for label, contents, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                if contents is not None:
                    path.write_text(contents, encoding="utf-8")
                before = path.read_bytes() if path.exists() else None
                stderr = io.StringIO()
                stdout = io.StringIO()
                with (
                    patch(
                        "offlook.platforms.windows_hotkey.HotkeyListener",
                        side_effect=AssertionError("Must not register a native shortcut"),
                    ),
                    patch("builtins.__import__", side_effect=import_without_gui),
                    redirect_stderr(stderr),
                    redirect_stdout(stdout),
                ):
                    result = main(["--config", str(path), "diagnose-search-shortcut"])
                self.assertEqual(result, 2)
                self.assertIn("OffLook:", stderr.getvalue())
                self.assertIn(expected, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(path.read_bytes() if path.exists() else None, before)
