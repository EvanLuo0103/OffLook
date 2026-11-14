"""Immutable, pickle-safe preview requests and bounded display results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from offlook.core.config import PreviewConfig
from offlook.core.files import FileInfo


MAX_RASTER_EDGE = 4096
MAX_RASTER_PIXELS = 8388608
# Leave room for metadata and pickle framing around the maximum RGBA raster.
MAX_PREVIEW_PAYLOAD_BYTES = 37748736


@dataclass(frozen=True)
class RenderRequest:
    """Request one file/page with physical-pixel output bounds, not logical sizes."""

    request_id: int
    path: Path
    config: PreviewConfig
    page_index: int = 0
    max_width: int = 1600
    max_height: int = 1600

    def __post_init__(self) -> None:
        """Normalize the path and raise ValueError for invalid request fields."""
        object.__setattr__(self, "path", Path(self.path))
        for name in ("request_id", "page_index"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        for name in ("max_width", "max_height"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= MAX_RASTER_EDGE:
                raise ValueError(f"{name} must be between 1 and {MAX_RASTER_EDGE}")
        if self.max_width * self.max_height > MAX_RASTER_PIXELS:
            raise ValueError("requested raster area exceeds bounds")
        if not isinstance(self.config, PreviewConfig):
            raise ValueError("config must be PreviewConfig")


@dataclass(frozen=True)
class TextContent:
    """At most 200,000 characters, 5,000 lines and 8,192 characters per line."""

    text: str

    def __post_init__(self) -> None:
        """Reject text exceeding the IPC/display contract."""
        if not isinstance(self.text, str) or len(self.text) > 200000:
            raise ValueError("text exceeds display bounds")
        lines = self.text.splitlines()
        if len(lines) > 5000 or any(len(line) > 8192 for line in lines):
            raise ValueError("text exceeds line bounds")


@dataclass(frozen=True)
class TableContent:
    """A string-only table bounded to 200 rows, 50 columns and 512-char cells."""

    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        """Reject mutable or oversized tables before transmission."""
        if type(self.rows) is not tuple or len(self.rows) > 200:
            raise ValueError("table exceeds row bounds")
        total = 0
        for row in self.rows:
            if type(row) is not tuple or len(row) > 50:
                raise ValueError("table exceeds column bounds")
            for cell in row:
                if not isinstance(cell, str) or len(cell) > 512:
                    raise ValueError("table exceeds cell bounds")
                total += len(cell)
        if total > 200000:
            raise ValueError("table exceeds character bounds")


@dataclass(frozen=True)
class RasterContent:
    """A bounded physical-pixel RGBA raster with no image library handles."""

    width: int
    height: int
    rgba: bytes

    def __post_init__(self) -> None:
        """Reject invalid dimensions or mismatched raw byte lengths."""
        if any(type(n) is not int or not 1 <= n <= MAX_RASTER_EDGE for n in (self.width, self.height)):
            raise ValueError("raster dimensions exceed bounds")
        if self.width * self.height > MAX_RASTER_PIXELS:
            raise ValueError("raster area exceeds bounds")
        if type(self.rgba) is not bytes or len(self.rgba) != self.width * self.height * 4:
            raise ValueError("invalid RGBA byte length")


@dataclass(frozen=True)
class MetadataContent:
    """Safe file-card attributes without source content or thumbnail handlers."""

    created_time_ns: int | None
    readonly: bool
    hidden: bool

    def __post_init__(self) -> None:
        """Reject malformed timestamps and non-boolean Windows attributes."""
        if self.created_time_ns is not None and type(self.created_time_ns) is not int:
            raise ValueError("created_time_ns must be an integer or None")
        if type(self.readonly) is not bool or type(self.hidden) is not bool:
            raise ValueError("file attributes must be boolean")


@dataclass(frozen=True)
class PreviewData:
    """Bounded rendering output, original metadata and user-facing notices."""

    file_info: FileInfo
    content: TextContent | TableContent | RasterContent | MetadataContent
    notice: str = ""
    truncated: bool = False
    page_index: int = 0
    page_count: int = 1

    def __post_init__(self) -> None:
        """Reject malformed content, notices or page metadata."""
        if not isinstance(self.file_info, FileInfo):
            raise ValueError("invalid file metadata")
        if not isinstance(self.content, (TextContent, TableContent, RasterContent, MetadataContent)):
            raise ValueError("invalid preview content")
        if not isinstance(self.notice, str) or len(self.notice) > 4096:
            raise ValueError("notice exceeds bounds")
        if type(self.truncated) is not bool:
            raise ValueError("truncated must be boolean")
        if (type(self.page_count) is not int or self.page_count < 1
                or type(self.page_index) is not int or not 0 <= self.page_index < self.page_count):
            raise ValueError("invalid page metadata")
