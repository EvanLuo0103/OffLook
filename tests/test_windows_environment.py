"""Windows user-PATH integration tests isolated to disposable HKCU keys."""

from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
import tempfile
from types import SimpleNamespace

from offlook.core.errors import OffLookError
from offlook.platforms.windows_environment import (
    PathUpdateResult,
    _merge_path,
    _normalized_entry,
    add_offlook_to_user_path,
    resolve_offlook_scripts_dir,
)
from offlook.platforms.windows_environment import _broadcast_environment_change
from importlib import metadata

if sys.platform == "win32":
    import winreg


@contextmanager
def temporary_registry_path():
    """Yield a disposable HKCU key and remove it without touching production PATH."""
    registry_path = rf"Software\OffLookTests\{uuid4().hex}"
    try:
        yield registry_path
    finally:
        if sys.platform == "win32":
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry_path)
            except FileNotFoundError:
                pass


class PathMergeTests(unittest.TestCase):
    """Exercise preservation and equivalence rules without requiring Windows."""

    def test_merge_preserves_text_and_empty_entries(self) -> None:
        scripts = Path(r"C:\Users\me\Scripts")
        value = r"%USERPROFILE%\Tools;;C:\原有 路徑"
        merged, changed = _merge_path(value, scripts)
        self.assertTrue(changed)
        self.assertEqual(merged, value + ";" + str(scripts))
        self.assertEqual(_merge_path(merged, scripts), (merged, False))

    def test_equivalent_values_are_not_rewritten(self) -> None:
        scripts = Path(r"C:\Users\me\Scripts")
        with patch.dict(os.environ, {"USERPROFILE": r"C:\Users\me"}, clear=False):
            self.assertEqual(
                _merge_path(r'"%USERPROFILE%\Scripts\\"', scripts),
                (r'"%USERPROFILE%\Scripts\\"', False),
            )

    def test_invalid_and_overlong_values_are_rejected(self) -> None:
        scripts = Path(r"C:\Scripts")
        with self.assertRaises(OffLookError):
            _merge_path("C:\\bad\x00value", scripts)
        with self.assertRaises(OffLookError):
            _merge_path("x" * 32767, scripts)


@unittest.skipUnless(sys.platform == "win32", "Windows registry integration only")
class WindowsPathTests(unittest.TestCase):
    """Use the installed executable and real APIs under a unique HKCU test key."""

    def setUp(self) -> None:
        self.scripts = resolve_offlook_scripts_dir()
        self.registry_path = self.enterContext(temporary_registry_path())
        self.enterContext(patch.dict(os.environ, {"PATH": os.defpath}, clear=False))
        self.broadcast = self.enterContext(patch(
            "offlook.platforms.windows_environment._broadcast_environment_change", return_value=True,
        ))

    def write_path(self, value: object, value_type: int) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.registry_path) as key:
            winreg.SetValueEx(key, "Path", 0, value_type, value)

    def read_path(self) -> tuple[object, int]:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_path) as key:
            return winreg.QueryValueEx(key, "Path")

    def add(self) -> PathUpdateResult:
        return add_offlook_to_user_path(registry_path=self.registry_path)

    def test_expand_sz_preserves_exact_text_and_repeat_is_noop(self) -> None:
        original = r"%USERPROFILE%\Tools;;C:\原有 路徑"
        self.write_path(original, winreg.REG_EXPAND_SZ)
        first = self.add()
        self.assertEqual(first.scripts_dir, self.scripts)
        self.assertTrue(first.changed)
        expected = original + ";" + str(self.scripts)
        self.assertEqual(self.read_path(), (expected, winreg.REG_EXPAND_SZ))
        process_path = os.environ["PATH"]
        self.assertIn(str(self.scripts), process_path.split(";"))
        self.assertFalse(self.add().changed)
        self.assertEqual(self.read_path(), (expected, winreg.REG_EXPAND_SZ))
        self.assertEqual(os.environ["PATH"], process_path)

    def test_equivalent_entries_preserve_type_and_are_not_written(self) -> None:
        with patch.dict(os.environ, {"OFFLOOK_TEST_SCRIPTS": str(self.scripts)}, clear=False):
            entries = (str(self.scripts).upper() + "\\", '  "%OFFLOOK_TEST_SCRIPTS%\\"  ')
            for entry in entries:
                with self.subTest(entry=entry):
                    original = "C:\\Original;;" + entry + ";"
                    self.write_path(original, winreg.REG_EXPAND_SZ)
                    with patch("winreg.SetValueEx", wraps=winreg.SetValueEx) as setter:
                        self.assertFalse(self.add().changed)
                        setter.assert_not_called()
                    self.assertEqual(self.read_path(), (original, winreg.REG_EXPAND_SZ))

    def test_plain_sz_and_trailing_empty_entries_are_preserved(self) -> None:
        original = "C:\\Original;;"
        self.write_path(original, winreg.REG_SZ)
        self.assertTrue(self.add().changed)
        self.assertEqual(self.read_path(), (original + ";" + str(self.scripts), winreg.REG_SZ))

    def test_missing_path_is_created_as_expand_sz(self) -> None:
        self.assertTrue(self.add().changed)
        self.assertEqual(self.read_path(), (str(self.scripts), winreg.REG_EXPAND_SZ))

    def test_invalid_types_and_overlong_path_do_not_change_registry(self) -> None:
        cases = (
            (5, winreg.REG_DWORD),
            (["C:\\Original"], winreg.REG_MULTI_SZ),
            ("x" * 32767, winreg.REG_SZ),
        )
        for value, value_type in cases:
            with self.subTest(value_type=value_type):
                self.write_path(value, value_type)
                with self.assertRaises(OffLookError):
                    self.add()
                self.assertEqual(self.read_path(), (value, value_type))
        self.broadcast.assert_not_called()

    def test_missing_executable_does_not_change_path(self) -> None:
        self.write_path("C:\\Original", winreg.REG_SZ)
        with tempfile.TemporaryDirectory() as directory:
            record = metadata.PackagePath("../Scripts/offlook.exe")
            distribution = SimpleNamespace(files=[record], locate_file=lambda _: Path(directory) / "missing.exe")
            with patch("offlook.platforms.windows_environment.metadata.distribution", return_value=distribution):
                with self.assertRaises(OffLookError):
                    self.add()
        self.assertEqual(self.read_path(), ("C:\\Original", winreg.REG_SZ))
        self.broadcast.assert_not_called()

    def test_latest_path_is_merged_immediately_before_write(self) -> None:
        self.write_path("C:\\Original", winreg.REG_SZ)
        original_query = winreg.QueryValueEx
        reads = 0

        def query_with_external_change(key, name):
            nonlocal reads
            result = original_query(key, name)
            reads += 1
            if reads == 1:
                self.write_path("C:\\External;;", winreg.REG_EXPAND_SZ)
            return result

        with patch("winreg.QueryValueEx", side_effect=query_with_external_change):
            self.assertTrue(self.add().changed)
        self.assertEqual(self.read_path(), ("C:\\External;;;" + str(self.scripts), winreg.REG_EXPAND_SZ))

    def test_broadcast_failure_keeps_successful_write(self) -> None:
        self.broadcast.return_value = False
        result = self.add()
        self.assertTrue(result.changed)
        self.assertFalse(result.broadcast_ok)
        self.assertEqual(self.read_path(), (str(self.scripts), winreg.REG_EXPAND_SZ))

    def test_other_executable_precedence_is_reported_not_reordered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "offlook.exe"
            other.touch()
            os.environ["PATH"] = directory
            with patch.dict(os.environ, {"PATHEXT": ".EXE"}, clear=False):
                result = self.add()
                self.assertIsNotNone(result.conflicting_executable)
                self.assertEqual(_normalized_entry(str(result.conflicting_executable)), _normalized_entry(str(other)))
                self.assertEqual(os.environ["PATH"], directory + ";" + str(self.scripts))
                self.assertTrue(other.is_file())

    def test_registry_permission_error_is_wrapped(self) -> None:
        failure = PermissionError(5, "access denied")
        with patch("winreg.OpenKey", side_effect=failure):
            with self.assertRaises(OffLookError) as caught:
                self.add()
        self.assertIs(caught.exception.__cause__, failure)



class MetadataResolutionTests(unittest.TestCase):
    """Reject absent or ambiguous package records rather than guessing a Scripts path."""

    def test_missing_distribution_is_clear(self) -> None:
        with patch(
            "offlook.platforms.windows_environment.metadata.distribution",
            side_effect=metadata.PackageNotFoundError("offlook"),
        ):
            with self.assertRaises(OffLookError):
                resolve_offlook_scripts_dir()

    def test_record_resolves_actual_relative_scripts_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site_packages = root / "site-packages"
            site_packages.mkdir()
            scripts = root / "Scripts"
            scripts.mkdir()
            (scripts / "offlook.exe").touch()
            records = [metadata.PackagePath("../Scripts/offlook.exe"), metadata.PackagePath("offlook/__init__.py")]
            distribution = SimpleNamespace(files=records, locate_file=lambda record: site_packages / record)
            with patch("offlook.platforms.windows_environment.metadata.distribution", return_value=distribution):
                self.assertEqual(resolve_offlook_scripts_dir(), scripts.resolve())

    def test_missing_empty_and_ambiguous_records_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("first", "second"):
                (root / name).mkdir()
                (root / name / "offlook.exe").touch()
            cases = (
                None,
                [],
                [metadata.PackagePath("offlook/__init__.py")],
                [metadata.PackagePath("missing/offlook.exe")],
                [metadata.PackagePath("first/offlook.exe"), metadata.PackagePath("second/offlook.exe")],
            )
            for records in cases:
                with self.subTest(records=records):
                    distribution = SimpleNamespace(files=records, locate_file=lambda record: root / record)
                    with patch("offlook.platforms.windows_environment.metadata.distribution", return_value=distribution):
                        with self.assertRaises(OffLookError):
                            resolve_offlook_scripts_dir()

    def test_duplicate_records_for_same_executable_are_not_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "offlook.exe").touch()
            records = [metadata.PackagePath("offlook.exe"), metadata.PackagePath("./offlook.exe")]
            distribution = SimpleNamespace(files=records, locate_file=lambda record: root / record)
            with patch("offlook.platforms.windows_environment.metadata.distribution", return_value=distribution):
                self.assertEqual(resolve_offlook_scripts_dir(), root.resolve())


class EnvironmentBroadcastTests(unittest.TestCase):
    """Inspect the Win32 boundary without notifying any running application."""

    def test_declared_types_live_buffer_and_timeout(self) -> None:
        calls = []

        class SendMessage:
            def __call__(self, hwnd, message, wparam, lparam, flags, timeout, result):
                calls.append((hwnd, message, wparam, ctypes.wstring_at(lparam), flags, timeout))
                return 1

        send = SendMessage()
        user32 = SimpleNamespace(SendMessageTimeoutW=send)
        with patch("offlook.platforms.windows_environment.ctypes.WinDLL", return_value=user32, create=True) as load:
            self.assertTrue(_broadcast_environment_change())
        load.assert_called_once_with("user32", use_last_error=True)
        self.assertEqual(calls, [(0xFFFF, 0x001A, 0, "Environment", 0x0002 | 0x0020, 1000)])
        self.assertEqual(send.argtypes, (
            ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
            ctypes.wintypes.UINT, ctypes.wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        ))
        self.assertIs(send.restype, ctypes.c_ssize_t)

    def test_zero_return_and_api_failure_are_reported(self) -> None:
        class SendMessage:
            def __call__(self, *args):
                return 0

        with patch(
            "offlook.platforms.windows_environment.ctypes.WinDLL",
            return_value=SimpleNamespace(SendMessageTimeoutW=SendMessage()), create=True,
        ):
            self.assertFalse(_broadcast_environment_change())
        with patch(
            "offlook.platforms.windows_environment.ctypes.WinDLL", side_effect=OSError("unavailable"), create=True,
        ):
            self.assertFalse(_broadcast_environment_change())
