from pathlib import Path
import tempfile
import unittest

from offlook.core import (
    FileKind,
    copy_files,
    filter_files,
    find_files,
    list_folder,
    move_files,
    organize_by_kind,
)


def build_tree(root: Path) -> None:
    """Create a small folder tree with a PDF, a text file, and a CSV."""
    nested = root / "nested"
    nested.mkdir()
    (root / "Report.PDF").write_bytes(b"%PDF-1.4")
    (nested / "notes.txt").write_text("content", encoding="utf-8")
    (nested / "data.csv").write_text("a,b", encoding="utf-8")


class FileOpsTests(unittest.TestCase):
    def test_filter_multiple_kinds_and_extensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_tree(root)
            pdfs = filter_files(root, kinds=[FileKind.PDF])
            self.assertEqual([item.path.name for item in pdfs], ["Report.PDF"])
            both = filter_files(root, kinds=[FileKind.PDF, FileKind.TEXT])
            self.assertEqual(sorted(item.path.name for item in both), ["Report.PDF", "notes.txt"])
            by_extension = filter_files(root, extensions=[".pdf", ".csv"])
            self.assertEqual(sorted(item.path.name for item in by_extension), ["Report.PDF", "data.csv"])

    def test_filter_without_filters_matches_find_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_tree(root)
            all_files = filter_files(root)
            self.assertEqual(
                sorted(item.path.name for item in all_files),
                sorted(item.path.name for item in find_files(root)),
            )

    def test_list_folder_and_move_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_tree(root)
            listed = list_folder(root)
            self.assertEqual(sorted(path.name for path in listed), ["Report.PDF", "data.csv", "notes.txt"])
            destination = root / "out"
            results = move_files([root / "Report.PDF"], destination)
            self.assertEqual(results[0].status, "moved")
            self.assertTrue((destination / "Report.PDF").is_file())
            self.assertFalse((root / "Report.PDF").exists())

    def test_copy_files_keeps_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_tree(root)
            source = root / "Report.PDF"
            results = copy_files([source], root / "copy")
            self.assertEqual(results[0].status, "copied")
            self.assertTrue(source.exists())
            self.assertTrue((root / "copy" / "Report.PDF").exists())

    def test_organize_by_kind_archives_into_subfolders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_tree(root)
            destination = root / "archive"
            results = organize_by_kind(root, destination, kinds=[FileKind.PDF, FileKind.CSV])
            self.assertEqual(sorted(item.destination.parent.name for item in results), ["csv", "pdf"])
            self.assertTrue((destination / "pdf" / "Report.PDF").is_file())
            self.assertTrue((destination / "csv" / "data.csv").is_file())
            # The untouched text file remains in place.
            self.assertTrue((root / "nested" / "notes.txt").exists())


if __name__ == "__main__":
    unittest.main()
