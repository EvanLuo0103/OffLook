"""Explicit renderer registration and pickle-safe snapshots; no plugin discovery."""

from __future__ import annotations

import importlib
import inspect

from offlook.core.errors import PreviewError
from offlook.core.files import FileKind
from offlook.preview.renderers.base import Renderer


class RendererRegistry:
    """Map file kinds to explicitly registered, importable renderer classes."""

    def __init__(self) -> None:
        """Create an empty registry; use default_renderers for built-ins."""
        self._renderers: dict[FileKind, type[Renderer]] = {}

    def register(self, kind: FileKind, renderer_type: type[Renderer], *, replace: bool = False) -> None:
        """Register a concrete importable class or raise PreviewError on conflicts."""
        if not isinstance(kind, FileKind):
            raise PreviewError("The renderer kind must be a FileKind")
        if not isinstance(renderer_type, type) or not issubclass(renderer_type, Renderer) or inspect.isabstract(renderer_type):
            raise PreviewError("The renderer must be a concrete Renderer subclass")
        if renderer_type.__module__ == "__main__" or "<locals>" in renderer_type.__qualname__:
            raise PreviewError("The renderer must be a top-level class in an importable module")
        if "." in renderer_type.__qualname__:
            raise PreviewError("The renderer must be a module-level class")
        try:
            imported = getattr(importlib.import_module(renderer_type.__module__), renderer_type.__name__)
            if imported is not renderer_type:
                raise AttributeError("class identity mismatch")
            inspect.signature(renderer_type).bind()
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            raise PreviewError("The renderer must be importable and support construction without arguments") from exc
        if kind in self._renderers and not replace:
            raise PreviewError(f"Renderer already registered: {kind.value}")
        self._renderers[kind] = renderer_type

    def resolve(self, kind: FileKind) -> type[Renderer]:
        """Return the registered class or raise PreviewError for missing kinds."""
        try:
            return self._renderers[kind]
        except KeyError as exc:
            raise PreviewError(f"No renderer registered: {kind}") from exc

    def snapshot(self) -> dict[FileKind, type[Renderer]]:
        """Return an independent, ordinary pickle-safe dictionary for spawning."""
        return dict(self._renderers)


def default_renderers() -> RendererRegistry:
    """Build a fresh registry without importing Pillow/PDFium or creating workers."""
    from offlook.preview.renderers.metadata import MetadataRenderer
    from offlook.preview.renderers.csv import CsvRenderer
    from offlook.preview.renderers.image import ImageRenderer
    from offlook.preview.renderers.pdf import PdfRenderer
    from offlook.preview.renderers.text import TextRenderer

    registry = RendererRegistry()
    for kind in (FileKind.TEXT, FileKind.MARKDOWN, FileKind.CODE):
        registry.register(kind, TextRenderer)
    registry.register(FileKind.CSV, CsvRenderer)
    registry.register(FileKind.IMAGE, ImageRenderer)
    registry.register(FileKind.PDF, PdfRenderer)
    registry.register(FileKind.BINARY, MetadataRenderer)
    return registry
