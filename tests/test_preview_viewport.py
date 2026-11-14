"""Viewport and bounded raster contracts that do not require a Tk display."""
from __future__ import annotations

from pathlib import Path
import unittest

from offlook.core.config import PreviewConfig
from offlook.preview.models import (
    MAX_RASTER_EDGE,
    MAX_RASTER_PIXELS,
    RasterContent,
    RenderRequest,
)
from offlook.preview.window import bounded_viewport


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


if __name__ == "__main__":
    unittest.main()
