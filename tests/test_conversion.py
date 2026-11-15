from pathlib import Path
import tempfile
import unittest

from PIL import Image

from offlook.core import (
    ConversionError,
    convert_file,
    convert_files,
    normalize_target,
    reachable_targets,
    target_formats,
)

try:
    import docx  # noqa: F401

    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


class ConversionTests(unittest.TestCase):
    @staticmethod
    def _image(root: Path, name: str = "pic.png", size: tuple[int, int] = (40, 30)) -> Path:
        path = root / name
        Image.new("RGB", size, (120, 40, 40)).save(path)
        return path

    def test_image_to_jpeg_and_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._image(root)
            outcome = convert_file(source, "jpg")
            self.assertEqual([path.suffix for path in outcome.outputs], [".jpg"])
            self.assertTrue(outcome.outputs[0].is_file())
            pdf = convert_file(source, "pdf")
            self.assertEqual(pdf.outputs[0].suffix, ".pdf")
            self.assertTrue(pdf.outputs[0].is_file())

    def test_output_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._image(root)
            (root / "pic.jpg").write_bytes(b"existing")
            outcome = convert_file(source, "jpg")
            self.assertEqual(outcome.outputs[0].name, "pic (1).jpg")

    def test_text_to_txt_and_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "note.md"
            source.write_text("# Hello\nworld", encoding="utf-8")
            txt = convert_file(source, "txt")
            self.assertEqual(txt.outputs[0].suffix, ".txt")
            self.assertIn("world", txt.outputs[0].read_text(encoding="utf-8"))
            pdf = convert_file(source, "pdf")
            self.assertEqual(pdf.outputs[0].suffix, ".pdf")

    @unittest.skipUnless(HAS_DOCX, "python-docx is not installed")
    def test_text_to_docx(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "note.txt"
            source.write_text("line one\nline two", encoding="utf-8")
            outcome = convert_file(source, "docx")
            self.assertEqual(outcome.outputs[0].suffix, ".docx")
            self.assertTrue(outcome.outputs[0].is_file())

    def test_normalize_target_aliases(self):
        self.assertEqual(normalize_target("jpeg"), ".jpg")
        self.assertEqual(normalize_target(".PDF"), ".pdf")
        with self.assertRaises(ConversionError):
            normalize_target("exe")

    def test_reachable_targets_filtered_by_source(self):
        self.assertIn(".pdf", reachable_targets(["a.png"]))
        self.assertNotIn(".docx", reachable_targets(["a.png"]))
        self.assertIn(".txt", reachable_targets(["a.md"]))
        self.assertNotIn(".png", reachable_targets(["a.md"]))
        self.assertEqual(target_formats()[0], ".pdf")

    def test_multi_image_combines_to_one_pdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._image(root, "a.png", (30, 20))
            second = self._image(root, "b.png", (20, 30))
            outcomes = convert_files([first, second], "pdf")
            self.assertEqual(len(outcomes), 1)
            self.assertEqual(len(outcomes[0].outputs), 1)
            self.assertEqual(outcomes[0].outputs[0].suffix, ".pdf")

    def test_unsupported_conversion_raises(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "blob.bin"
            source.write_bytes(b"\x00\x01\x02")
            with self.assertRaises(ConversionError):
                convert_file(source, "txt")


if __name__ == "__main__":
    unittest.main()
