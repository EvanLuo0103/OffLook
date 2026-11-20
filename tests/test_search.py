from pathlib import Path
import tempfile
import unittest

from offlook.core import FileKind, find_files


class SearchTests(unittest.TestCase):

    def test_recursive_case_insensitive_name_and_type_filters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "Report.PDF").write_bytes(b"%PDF-1.4")
            (root / "budget.xlsx").write_bytes(b"not-previewed")
            (root / "archive.xyz").write_bytes(b"unknown")
            (root / "nested" / "report.txt").write_text("content", encoding="utf-8")
            (root / "nested" / "notes.csv").write_text("a,b", encoding="utf-8")

            results = find_files(root, filename="REPORT")
            self.assertEqual([item.path.name for item in results], ["Report.PDF", "report.txt"])
            pdfs = find_files(root, kind=FileKind.PDF)
            self.assertEqual([item.path.name for item in pdfs], ["Report.PDF"])
            documents = find_files(root, kind=FileKind.DOCUMENT)
            self.assertEqual([item.path.name for item in documents], ["budget.xlsx"])
            other = find_files(root, kind=FileKind.BINARY)
            self.assertEqual([item.path.name for item in other], ["archive.xyz"])

    def test_skips_symlinked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.txt"
            target.write_text("content", encoding="utf-8")
            link = root / "linked.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable")
            self.assertEqual([item.path.name for item in find_files(root)], ["target.txt"])
