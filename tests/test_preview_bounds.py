"""Regression checks for real local-file decoding and bounded rendering on Windows."""

from dataclasses import replace
from pathlib import Path
import os
import sys
import tempfile
import unittest

from offlook.core.errors import FileAccessError, PreviewError
from offlook.core.files import FileKind, FileTypeDetector
from offlook.preview.models import MetadataContent, RasterContent, RenderRequest, TableContent, TextContent
from offlook.preview.registry import default_renderers
from offlook.preview.renderers.image import ImageRenderer
from offlook.preview.renderers.metadata import MetadataRenderer
from offlook.preview.renderers.pdf import PdfRenderer
from offlook.preview.renderers.text import TextRenderer
from offlook.preview.worker import _render_request
from preview_fixtures import config, pdf, png


@unittest.skipUnless(sys.platform == "win32", "local-file boundary is Windows-only")
class PreviewBoundsTests(unittest.TestCase):
    """Exercise actual parsers and temporary files without mocks or user selections."""

    def setUp(self) -> None:
        """Create a dedicated temporary directory and production renderer snapshot."""
        self.temp = tempfile.TemporaryDirectory(prefix="offlook-bounds-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.renderers = default_renderers().snapshot()

    def render(self, path: Path, **changes: object):
        """Render a real fixture through production central dispatch with config overrides."""
        return _render_request(RenderRequest(1, path, config(**changes)), self.renderers)

    def test_bom_and_gb18030_chinese(self) -> None:
        """UTF BOMs and detected GB18030 retain original Chinese, not fixed codec aliases."""
        phrase = "中文文件预览，大学小组本地处理。\n"
        for encoding in ("utf-8-sig", "utf-16", "utf-32", "gb18030"):
            with self.subTest(encoding=encoding):
                path = self.root / f"{encoding}.txt"
                path.write_bytes((phrase * 40).encode(encoding))
                info = FileTypeDetector().detect(path)
                self.assertEqual(info.kind, FileKind.TEXT)
                data = self.render(path)
                self.assertIsInstance(data.content, TextContent)
                self.assertIn(phrase, data.content.text)

    def test_incremental_byte_cut_and_invalid_internal_byte(self) -> None:
        """A cut Chinese character is buffered, whereas actual malformed UTF-8 is warned."""
        path = self.root / "cut.txt"
        path.write_bytes(b"a" * 4095 + "中".encode() + b"SENTINEL")
        data = self.render(path, max_file_size_bytes=4096)
        self.assertTrue(data.truncated)
        self.assertNotIn("SENTINEL", data.content.text)
        self.assertNotIn("\ufffd", data.content.text)
        path.write_bytes(b"normal text " * 100 + b"\xff" + b" trailing")
        info = replace(FileTypeDetector().detect(path), encoding="utf-8", encoding_confidence=1.0)
        data = TextRenderer().render(info, RenderRequest(2, path, config()))
        self.assertIn("\ufffd", data.content.text)
        self.assertIn("undecodable", data.notice)

    def test_text_display_limits_and_empty(self) -> None:
        """Text display obeys line, character and row bounds and identifies empty files."""
        for name, text in (("longline", "x" * 9000), ("manylines", "x\n" * 6000), ("characters", ("x" * 100 + "\n") * 3000)):
            path = self.root / f"{name}.txt"
            path.write_text(text, encoding="utf-8")
            data = self.render(path)
            self.assertTrue(data.truncated)
            self.assertLessEqual(len(data.content.text), 200000)
            self.assertLessEqual(len(data.content.text.splitlines()), 5000)
            self.assertTrue(all(len(line) <= 8192 for line in data.content.text.splitlines()))
        path = self.root / "empty.txt"
        path.write_bytes(b"")
        self.assertIn("Empty file", self.render(path).notice)

    def test_oversized_media_returns_metadata_without_decoding(self) -> None:
        """Real PNG/PDF above eight bytes retain metadata without invoking a decoder."""
        for path in (png(self.root / "image.png"), pdf(self.root / "document.pdf")):
            with self.subTest(path=path.name):
                request = RenderRequest(1, path, config(max_file_size_bytes=8))
                data = _render_request(request, {})
                self.assertIsInstance(data.content, MetadataContent)
                self.assertEqual(data.notice, "Safety preview limit exceeded; showing file information only")
                self.assertEqual(data.file_info, FileTypeDetector().detect(path))
                stat = os.stat(path, follow_symlinks=False)
                self.assertEqual(data.file_info.path, path)
                self.assertEqual(data.file_info.path.name, path.name)
                self.assertEqual(data.file_info.size_bytes, stat.st_size)
                self.assertEqual(data.file_info.modified_time_ns, stat.st_mtime_ns)
                created = getattr(stat, "st_birthtime_ns", stat.st_ctime_ns)
                self.assertEqual(data.content.created_time_ns, created)
                self.assertEqual(data.content.readonly, bool(stat.st_file_attributes & 0x1))
                self.assertEqual(data.content.hidden, bool(stat.st_file_attributes & 0x2))

    def test_unknown_binary_and_empty_file_return_metadata(self) -> None:
        """Unknown NUL-containing and empty files yield safe cards, not decoded content."""
        binary = self.root / "unknown.bin"
        binary.write_bytes(bytes(range(256)) * 4)
        data = self.render(binary)
        self.assertEqual(data.file_info.kind, FileKind.BINARY)
        self.assertIsInstance(data.content, MetadataContent)
        self.assertEqual(data.notice, "Content preview is not supported for this format")
        self.assertEqual(data.file_info.size_bytes, 1024)
        empty = self.root / "empty.bin"
        empty.write_bytes(b"")
        data = self.render(empty)
        self.assertIsInstance(data.content, MetadataContent)
        self.assertEqual(data.file_info.size_bytes, 0)

    def test_metadata_rejects_changed_or_missing_file(self) -> None:
        """Metadata cards report stale or missing files instead of silently succeeding."""
        path = self.root / "changing.bin"
        path.write_bytes(b"\0original")
        info = FileTypeDetector().detect(path)
        request = RenderRequest(1, path, config())
        path.write_bytes(b"\0changed-size")
        with self.assertRaises(FileAccessError):
            MetadataRenderer().render(info, request)
        path.unlink()
        with self.assertRaises(FileAccessError):
            MetadataRenderer().render(info, request)

    def test_supported_extensions_only_controls_dispatch(self) -> None:
        """An empty allowlist leaves recognition intact but selects a metadata card."""
        path = self.root / "known.txt"
        path.write_text("hello", encoding="utf-8")
        self.assertEqual(FileTypeDetector().detect(path).kind, FileKind.TEXT)
        data = self.render(path, supported_extensions=())
        self.assertIsInstance(data.content, MetadataContent)
        self.assertEqual(data.file_info.kind, FileKind.TEXT)
        self.assertEqual(data.notice, "Content preview is not enabled for this extension")

    def test_csv_quoted_newlines_and_incomplete_tail(self) -> None:
        """Quoted newlines survive; a byte-cut quoted tail is discarded explicitly."""
        path = self.root / "quoted.csv"
        path.write_bytes(b'first,second\n"hello\nworld",=1+1\nlast,"unfinished record"\n')
        data = self.render(path)
        self.assertIsInstance(data.content, TableContent)
        self.assertEqual(data.content.rows[0], ("first", "second"))
        self.assertEqual(data.content.rows[1], ("hello\nworld", "=1+1"))
        data = self.render(path, max_file_size_bytes=42)
        self.assertIsInstance(data.content, TableContent)
        self.assertEqual(len(data.content.rows), 2)
        self.assertTrue(data.truncated)
        self.assertIn("trailing CSV record", data.notice)

    def test_csv_cell_column_row_and_total_bounds(self) -> None:
        """Oversized tables cannot exceed any of the display contracts."""
        path = self.root / "bounded.tsv"
        line = "\t".join(["x" * 600] * 55) + "\n"
        path.write_text(line * 210, encoding="utf-8")
        data = self.render(path)
        self.assertIsInstance(data.content, TableContent)
        self.assertTrue(data.truncated)
        self.assertLessEqual(len(data.content.rows), 200)
        self.assertTrue(all(len(row) <= 50 for row in data.content.rows))
        self.assertTrue(all(len(cell) <= 512 for row in data.content.rows for cell in row))
        self.assertLessEqual(sum(len(cell) for row in data.content.rows for cell in row), 200000)
        # Independently reach the row limit without hitting the character limit.
        path.write_text("a\tb\n" * 205, encoding="utf-8")
        data = self.render(path)
        self.assertEqual(len(data.content.rows), 200)
        self.assertIn("200-row", data.notice)

    def test_csv_invalid_syntax_falls_back_to_labeled_text(self) -> None:
        """Malformed nontruncated CSV is not presented as a successful partial table."""
        path = self.root / "bad.csv"
        path.write_text('a,b\n"unterminated', encoding="utf-8")
        data = self.render(path)
        self.assertIsInstance(data.content, TextContent)
        self.assertIn("CSV parsing failed; showing the text prefix", data.notice)

    def test_pixel_bomb_rejected_and_normal_image_ratio(self) -> None:
        """A valid compressed bomb is rejected before full decoding; normal ratios stay."""
        bomb = png(self.root / "bomb.png", 5001, 5000)
        with self.assertRaises(PreviewError):
            ImageRenderer().render(FileTypeDetector().detect(bomb), RenderRequest(3, bomb, config()))
        normal = png(self.root / "normal.png")
        request = RenderRequest(4, normal, config(), max_width=100, max_height=100)
        data = ImageRenderer().render(FileTypeDetector().detect(normal), request)
        self.assertIsInstance(data.content, RasterContent)
        self.assertEqual((data.content.width, data.content.height), (100, 50))
        self.assertEqual(data.content.rgba[:4], b"\xff\0\0\xff")

    def test_high_resolution_image_and_native_small_image(self) -> None:
        """Large images use the requested pixels while small sources are never enlarged."""
        for name, width, height, expected in (
            ("small.png", 400, 200, (400, 200)),
            ("large.png", 4000, 2000, (3200, 1600)),
        ):
            with self.subTest(name=name):
                path = png(self.root / name, width, height)
                request = RenderRequest(6, path, config(), max_width=3200, max_height=2400)
                data = ImageRenderer().render(FileTypeDetector().detect(path), request)
                self.assertIsInstance(data.content, RasterContent)
                self.assertEqual((data.content.width, data.content.height), expected)
                middle = ((data.content.height // 2) * data.content.width + data.content.width // 2) * 4
                self.assertEqual(data.content.rgba[middle:middle + 4], b"\xff\0\0\xff")
                self.assertEqual(len(data.content.rgba), expected[0] * expected[1] * 4)

    def test_corrupt_supported_media_remains_an_error(self) -> None:
        """A supported, in-budget corrupt file must not masquerade as a valid card."""
        for name in ("broken.png", "broken.pdf"):
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(b"not valid media")
                with self.assertRaises(PreviewError):
                    self.render(path)

    def test_pdf_second_page_and_invalid_page(self) -> None:
        """Real second-page rendering obeys bounds and rejects out-of-range pages."""
        path = pdf(self.root / "pages.pdf")
        info = FileTypeDetector().detect(path)
        request = RenderRequest(5, path, config(), page_index=1, max_width=121, max_height=89)
        data = PdfRenderer().render(info, request)
        self.assertEqual((data.page_index, data.page_count), (1, 2))
        self.assertLessEqual(data.content.width, 121)
        self.assertLessEqual(data.content.height, 89)
        self.assertGreater(data.content.width, data.content.height)
        self.assertEqual(data.content.rgba[:4], b"\0\0\xff\xff")
        with self.assertRaises(PreviewError):
            PdfRenderer().render(info, replace(request, page_index=2))
        path = self.root / "empty.pdf"
        path.write_bytes(b"")
        with self.assertRaises(PreviewError):
            self.render(path)

    def test_pdf_second_page_uses_full_requested_resolution(self) -> None:
        """A 400-by-200 page renders at 8x rather than the obsolete 2x ceiling."""
        path = pdf(self.root / "high-resolution.pdf")
        request = RenderRequest(7, path, config(), page_index=1, max_width=3200, max_height=2400)
        data = PdfRenderer().render(FileTypeDetector().detect(path), request)
        self.assertIsInstance(data.content, RasterContent)
        self.assertEqual((data.page_index, data.page_count), (1, 2))
        self.assertEqual((data.content.width, data.content.height), (3200, 1600))
        middle = ((data.content.height // 2) * data.content.width + data.content.width // 2) * 4
        self.assertEqual(data.content.rgba[middle:middle + 4], b"\0\0\xff\xff")
        self.assertEqual(len(data.content.rgba), 3200 * 1600 * 4)


class MetadataContentTests(unittest.TestCase):
    """Keep the pickle-safe card contract strict independently of Windows file I/O."""

    def test_timestamp_and_boolean_types(self) -> None:
        """Only integer/absent timestamps and actual booleans are accepted."""
        for created in (None, 0, 123456789):
            self.assertEqual(MetadataContent(created, False, True).created_time_ns, created)
        for created in (True, False, 1.5, "123"):
            with self.subTest(created=created), self.assertRaises(ValueError):
                MetadataContent(created, False, False)
        for readonly, hidden in ((1, False), (False, 0), (None, False), (False, "yes")):
            with self.subTest(readonly=readonly, hidden=hidden), self.assertRaises(ValueError):
                MetadataContent(None, readonly, hidden)
