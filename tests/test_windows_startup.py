"""Isolated Windows startup tests using disposable real HKCU registry keys."""

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from offlook.core.errors import OffLookError
from offlook.platforms.windows_startup import StartupManager

if sys.platform == "win32":
    import winreg


@contextmanager
def temporary_registry_path():
    """Yield a unique HKCU subkey path and remove its values/key in finally."""
    registry_path = rf"Software\OffLookStartupTest_{uuid4().hex}"
    try:
        yield registry_path
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry_path)
        except FileNotFoundError:
            pass


@unittest.skipUnless(sys.platform == "win32", "Windows registry integration only")
class StartupManagerTests(unittest.TestCase):
    """Check real registry state without ever touching the production Run key."""

    def test_constructor_and_disabled_state_do_not_create_key(self) -> None:
        """Constructing, reading missing state and disabling do not create a key."""
        with temporary_registry_path() as registry_path:
            manager = StartupManager(registry_path=registry_path)
            self.assertFalse(manager.is_enabled())
            manager.set_enabled(False)
            manager.set_enabled(False)
            with self.assertRaises(FileNotFoundError):
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path):
                    pass

    def test_actual_toggle_preserves_unrelated_value(self) -> None:
        """Enable/disable the default named value while retaining its neighbors."""
        with temporary_registry_path() as registry_path:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry_path) as key:
                winreg.SetValueEx(key, "Unrelated", 0, winreg.REG_SZ, "leave this alone")
            manager = StartupManager(registry_path=registry_path)
            self.assertFalse(manager.is_enabled())
            manager.set_enabled(True)
            self.assertTrue(manager.is_enabled())
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
                command, value_type = winreg.QueryValueEx(key, "OffLook")
                self.assertEqual(value_type, winreg.REG_SZ)
                self.assertEqual(
                    command,
                    subprocess.list2cmdline([
                        str(Path(sys.executable).absolute().with_name("pythonw.exe")),
                        "-m", "offlook", "--background",
                    ]),
                )
            manager.set_enabled(True)
            manager.set_enabled(False)
            self.assertFalse(manager.is_enabled())
            manager.set_enabled(False)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
                self.assertEqual(winreg.QueryValueEx(key, "Unrelated")[0], "leave this alone")
                with self.assertRaises(FileNotFoundError):
                    winreg.QueryValueEx(key, "OffLook")

    def test_config_command_quotes_spaces_and_uses_absolute_path(self) -> None:
        """The actual custom value quotes a spaced Unicode config path for logon."""
        with temporary_registry_path() as registry_path:
            with tempfile.TemporaryDirectory(prefix="offlook startup ") as directory:
                config_path = Path(directory) / "設定 檔案.json"
                config_path.write_text("{}", encoding="utf-8")
                relative_path = os.path.relpath(config_path)
                manager = StartupManager(
                    relative_path, registry_path=registry_path, value_name="Custom OffLook"
                )
                manager.set_enabled(True)
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
                    command, value_type = winreg.QueryValueEx(key, "Custom OffLook")
                    self.assertEqual(value_type, winreg.REG_SZ)
                    self.assertEqual(
                        command,
                        subprocess.list2cmdline([
                            str(Path(sys.executable).absolute().with_name("pythonw.exe")),
                            "-m", "offlook", "--config", str(config_path.absolute()),
                            "--background",
                        ]),
                    )
                    self.assertIn(f'"{config_path.absolute()}"', command)
                    with self.assertRaises(FileNotFoundError):
                        winreg.QueryValueEx(key, "OffLook")
                self.assertTrue(manager.is_enabled())
                manager.set_enabled(False)
                self.assertFalse(manager.is_enabled())

    def test_state_reads_external_registry_changes(self) -> None:
        """is_enabled reads its selected value afresh rather than caching writes."""
        with temporary_registry_path() as registry_path:
            manager = StartupManager(registry_path=registry_path, value_name="Custom OffLook")
            self.assertFalse(manager.is_enabled())
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry_path) as key:
                winreg.SetValueEx(key, "Custom OffLook", 0, winreg.REG_SZ, "existing command")
            self.assertTrue(manager.is_enabled())
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, registry_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, "Custom OffLook")
            self.assertFalse(manager.is_enabled())

    def test_missing_pythonw_does_not_write_registry(self) -> None:
        """A Python environment lacking pythonw fails before creating any key."""
        with temporary_registry_path() as registry_path:
            with tempfile.TemporaryDirectory(prefix="offlook startup ") as directory:
                executable = Path(directory) / "python.exe"
                executable.touch()
                manager = StartupManager(registry_path=registry_path)
                with patch("offlook.platforms.windows_startup.sys.executable", str(executable)):
                    with self.assertRaisesRegex(OffLookError, "pythonw.exe"):
                        manager.set_enabled(True)
                self.assertFalse(manager.is_enabled())
                with self.assertRaises(FileNotFoundError):
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path):
                        pass

    def test_registry_oserror_is_wrapped(self) -> None:
        """An injected access failure retains its OSError cause for callers."""
        with temporary_registry_path() as registry_path:
            manager = StartupManager(registry_path=registry_path)
            failure = PermissionError(5, "access denied")
            with patch("winreg.OpenKey", side_effect=failure):
                with self.assertRaises(OffLookError) as caught:
                    manager.is_enabled()
                self.assertIs(caught.exception.__cause__, failure)
                with self.assertRaises(OffLookError) as caught:
                    manager.set_enabled(False)
                self.assertIs(caught.exception.__cause__, failure)
