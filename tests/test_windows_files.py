"""Conservative local file/folder validation without contacting remote paths."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from offlook.core.errors import FileAccessError
from offlook.platforms.windows_files import validate_local_file, validate_local_folder


class LocalPathSyntaxTests(unittest.TestCase):
    def test_unsafe_paths_reject_before_normalization_or_filesystem_access(self) -> None:
        paths = (
            "", "\x00", r"\\server\share\folder", r"\\?\C:\folder",
            r"\\.\C:\folder", "https://example.invalid/folder", "file:///C:/folder",
            r"C:\folder:stream", r"C:\folder\file.txt:stream", "shell:Downloads",
        )
        for validator in (validate_local_file, validate_local_folder):
            for path in paths:
                with self.subTest(validator=validator.__name__, path=path):
                    with patch("offlook.platforms.windows_files.ntpath.abspath",
                               side_effect=AssertionError("Unsafe input reached normalization")):
                        with self.assertRaises(FileAccessError):
                            validator(path)


@unittest.skipUnless(sys.platform == "win32", "local-path boundary is Windows-only")
class WindowsFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import win32file
        except ImportError as exc:
            self.skipTest(f"pywin32 is unavailable: {exc}")
        self.win32file = win32file
        self.temporary = tempfile.TemporaryDirectory(prefix="offlook-local-path-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "ordinary folder"
        self.folder.mkdir()
        self.file = self.folder / "ordinary.txt"
        self.file.write_text("local content\n", encoding="utf-8")

    def test_file_and_folder_accept_their_own_type(self) -> None:
        self.assertEqual(validate_local_file(self.file), self.file)
        self.assertEqual(validate_local_folder(self.folder), self.folder)
        self.assertEqual(validate_local_file(str(self.file).replace("\\", "/")), self.file)
        self.assertEqual(validate_local_folder(str(self.folder).replace("\\", "/")), self.folder)

    def test_file_and_folder_reject_the_other_type(self) -> None:
        with self.assertRaisesRegex(FileAccessError, "regular file"):
            validate_local_file(self.folder)
        with self.assertRaisesRegex(FileAccessError, "local folder"):
            validate_local_folder(self.file)

    def test_missing_file_and_folder_are_rejected(self) -> None:
        missing = self.folder / "does-not-exist"
        for validator in (validate_local_file, validate_local_folder):
            with self.subTest(validator=validator.__name__):
                with self.assertRaises(FileAccessError):
                    validator(missing)

    def test_remote_drive_type_rejects_before_attribute_access(self) -> None:
        # Only simulate the drive-type boundary; never address an actual network drive.
        for validator, path in ((validate_local_file, self.file),
                                (validate_local_folder, self.folder)):
            with self.subTest(validator=validator.__name__):
                with patch.object(self.win32file, "GetDriveType", return_value=4) as drive_type:
                    with patch.object(self.win32file, "GetFileAttributes",
                                      side_effect=AssertionError("Remote drive attributes queried")):
                        with self.assertRaisesRegex(FileAccessError, "Network"):
                            validator(path)
                    drive_type.assert_called_once_with(path.drive + "\\")


if __name__ == "__main__":
    unittest.main()
