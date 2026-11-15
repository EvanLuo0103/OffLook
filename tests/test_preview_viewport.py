"""Bounded viewport contracts and real-Tk interrupted-render regressions."""
from __future__ import annotations

from pathlib import Path
import time
import tkinter as tk
import unittest

from offlook.core.config import PreviewConfig
from offlook.core.files import FileInfo, FileKind
from offlook.preview.models import (
    MAX_RASTER_EDGE,
    MAX_RASTER_PIXELS,
    MetadataContent,
    PreviewData,
    RasterContent,
    RenderRequest,
    TextContent,
)
from offlook.preview.window import PreviewWindow, bounded_viewport
from offlook.ui.theme import apply_theme


class PreviewViewportTests(unittest.TestCase):
    def test_non_positive_viewport_is_safe(self) -> None:
        for width, height in ((0, 0), (-4, 20), (20, -4)):
            result = bounded_viewport(width, height)
            self.assertGreaterEqual(result[0], 1)
            self.assertGreaterEqual(result[1], 1)

    def test_large_viewport_preserves_bounds_and_ratio(self) -> None:
        width, height = bounded_viewport(7680, 4320)
        self.assertLessEqual(width, MAX_RASTER_EDGE)
        self.assertLessEqual(height, MAX_RASTER_EDGE)
        self.assertLessEqual(width * height, MAX_RASTER_PIXELS)
        self.assertAlmostEqual(width / height, 7680 / 4320, delta=0.002)

    def test_square_cap(self) -> None:
        width, height = bounded_viewport(4096, 4096)
        self.assertEqual((width, height), (2896, 2896))
        self.assertLessEqual(width * height, MAX_RASTER_PIXELS)

    def test_raster_rejects_edge_and_rgba_overflow(self) -> None:
        with self.assertRaises(ValueError):
            RasterContent(MAX_RASTER_EDGE + 1, 1, b"\0\0\0\xff")
        with self.assertRaises(ValueError):
            RasterContent(1, 1, b"\0\0\0")

    def test_render_request_rejects_invalid_viewport(self) -> None:
        path = Path("preview.dat")
        with self.assertRaises(ValueError):
            RenderRequest(1, path, PreviewConfig(), max_width=0, max_height=10)
        with self.assertRaises(ValueError):
            RenderRequest(1, path, PreviewConfig(), max_width=MAX_RASTER_EDGE + 1, max_height=1)


class PreviewSuspensionTests(unittest.TestCase):
    """Exercise actual controls while collecting their worker-render requests."""

    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        self.addCleanup(self.destroy_windows)
        self.root.withdraw()
        apply_theme(self.root)
        self.requests: list[tuple[int, int, int]] = []
        self.view = PreviewWindow(
            self.root, Path("fixture.pdf"), always_on_top=False,
            on_render=lambda page, width, height: self.requests.append((page, width, height)),
            on_close=lambda: None,
        )
        self.view.window.minsize(1, 1)
        self.view.window.geometry("640x480")
        self.pump_until(lambda: bool(self.requests))

    def destroy_windows(self) -> None:
        try:
            view = getattr(self, "view", None)
            if view is not None:
                view.destroy()
        finally:
            self.root.destroy()

    def flush_viewport(self) -> None:
        # Calling a scheduled callback directly must first remove its Tk timer;
        # otherwise the callback clears the only handle needed during teardown.
        if self.view._resize_job is not None:
            self.view.window.after_cancel(self.view._resize_job)
            self.view._resize_job = None
        self.view._viewport_changed()

    def pump_until(self, predicate) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Preview did not reach the expected render state")

    def data(self, content, *, kind=FileKind.PDF, page=0) -> PreviewData:
        info = FileInfo(Path("fixture.pdf"), kind, 4, 0, ".pdf", None, None)
        return PreviewData(info, content, page_index=page,
                           page_count=2 if kind == FileKind.PDF else 1)

    def assert_initial_render_resumes(self, content, kind) -> None:
        first = self.requests[-1]
        count = len(self.requests)
        self.view.set_render_suspended(True)
        self.view.set_render_suspended(True)
        self.flush_viewport()
        self.assertEqual(len(self.requests), count)
        self.view.set_render_suspended(False)
        self.assertEqual(self.requests[count:], [first])
        self.view.set_render_suspended(False)
        self.flush_viewport()
        self.assertEqual(self.requests[count:], [first])
        self.view.show(self.data(content, kind=kind))
        self.assertFalse(self.view._loading)
        self.assertNotIn("Loading", self.view._status.cget("text"))
        self.assertTrue(self.view.body.winfo_children())

    def test_canceled_initial_text_reissues_same_viewport_once(self) -> None:
        self.assert_initial_render_resumes(TextContent("Recovered text"), FileKind.TEXT)
        self.assertEqual(self.view._text.get("1.0", "end-1c"), "Recovered text")

    def test_canceled_initial_metadata_reissues_without_a_raster(self) -> None:
        self.assert_initial_render_resumes(MetadataContent(None, False, False), FileKind.BINARY)
        self.assertIsNone(self.view._raster)

    def test_canceled_resolution_request_preserves_image_and_page(self) -> None:
        try:
            import PIL.ImageTk
        except ImportError as exc:
            self.skipTest(f"Pillow Tk support is unavailable: {exc}")
        raster = RasterContent(32, 32, b"\xff\0\0\xff" * (32 * 32))
        self.view.show(self.data(raster))
        self.view._page(1)
        self.view.show(self.data(raster, page=1))
        completed = self.requests[-1]
        count = len(self.requests)
        self.view.window.geometry("900x650")
        self.pump_until(lambda: len(self.requests) > count)
        self.assertEqual(self.requests[-1][0], 1)
        self.assertGreater(self.requests[-1][1], completed[1])
        displayed = self.view._image
        self.view.set_render_suspended(True)
        self.view.set_render_suspended(True)
        self.view.window.geometry("640x480")
        self.pump_until(lambda: self.view._viewport()[0] <= completed[1]
                        and self.view._viewport()[1] <= completed[2])
        self.flush_viewport()
        self.assertIs(self.view._image, displayed)
        self.assertIsNotNone(self.view._photo)
        count = len(self.requests)
        self.view.set_render_suspended(False)
        self.assertEqual(len(self.requests), count + 1)
        self.assertEqual(self.requests[-1][0], 1)
        self.assertLessEqual(self.requests[-1][1], completed[1])
        self.assertIs(self.view._image, displayed)
        self.view.set_render_suspended(False)
        self.flush_viewport()
        self.assertEqual(len(self.requests), count + 1)
        self.view.show(self.data(raster, page=1))
        self.assertFalse(self.view._loading)
        self.assertEqual(self.view._page_label.cget("text"), "2/2")

    def test_completed_raster_keeps_smaller_viewport_noop(self) -> None:
        try:
            import PIL.ImageTk
        except ImportError as exc:
            self.skipTest(f"Pillow Tk support is unavailable: {exc}")
        self.view.show(self.data(RasterContent(1, 1, b"\0\0\0\xff")))
        count = len(self.requests)
        displayed = self.view._image
        self.view.set_render_suspended(True)
        self.view.window.geometry("600x440")
        self.pump_until(lambda: self.view._viewport()[0] <= self.requests[-1][1]
                        and self.view._viewport()[1] <= self.requests[-1][2])
        self.flush_viewport()
        self.view.set_render_suspended(False)
        self.assertEqual(len(self.requests), count)
        self.assertIs(self.view._image, displayed)
        self.assertFalse(self.view._loading)

    def test_completed_error_is_not_retried_on_resume(self) -> None:
        self.view.show_error("Original render error")
        count = len(self.requests)
        self.view.set_render_suspended(True)
        self.flush_viewport()
        self.view.set_render_suspended(False)
        self.assertEqual(len(self.requests), count)
        self.assertEqual(self.view._status.cget("text"), "Original render error")
        self.assertFalse(self.view._loading)


if __name__ == "__main__":
    unittest.main()
