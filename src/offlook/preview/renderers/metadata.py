"""Local metadata-only cards without reading content or invoking thumbnail providers."""

import os

from offlook.core.errors import FileAccessError
from offlook.core.files import FileInfo
from offlook.platforms.windows_files import validate_local_file
from offlook.preview.models import MetadataContent, PreviewData, RenderRequest
from offlook.preview.renderers.base import Renderer


class MetadataRenderer(Renderer):
    """Inspect safe local file attributes without executing third-party handlers."""

    def render(self, info: FileInfo, request: RenderRequest) -> PreviewData:
        """Return file-card attributes, rejecting inaccessible or changed files."""
        try:
            path = validate_local_file(info.path)
            stat = os.stat(path, follow_symlinks=False)
            if stat.st_size != info.size_bytes or stat.st_mtime_ns != info.modified_time_ns:
                raise FileAccessError("The file changed during preview; reopen it")
        except FileAccessError:
            raise
        except OSError as exc:
            raise FileAccessError(f"Cannot read file information: {exc}") from exc
        created = getattr(stat, "st_birthtime_ns", None)
        if created is None and os.name == "nt":
            created = stat.st_ctime_ns
        attributes = getattr(stat, "st_file_attributes", 0)
        # Metadata never delegates unknown formats to Shell or third-party decoders.
        content = MetadataContent(created, bool(attributes & 0x1), bool(attributes & 0x2))
        return PreviewData(info, content)
