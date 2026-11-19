"""Bounded local-file metadata, signature, and text-encoding identification."""

import codecs
from dataclasses import dataclass
from enum import Enum
import math
from pathlib import Path

from .errors import FileAccessError, PreviewError


class FileKind(str, Enum):
    """Content categories supported by the renderer registry, with stable string values."""

    IMAGE = "image"
    TEXT = "text"
    MARKDOWN = "markdown"
    PDF = "pdf"
    CODE = "code"
    CSV = "csv"
    DOCUMENT = "document"
    BINARY = "binary"


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico")
TEXT_EXTENSIONS = (".txt", ".log", ".ini", ".cfg", ".conf", ".rst", ".tex")
MARKDOWN_EXTENSIONS = (".md", ".markdown")
PDF_EXTENSIONS = (".pdf",)
CODE_EXTENSIONS = (
    ".py", ".pyw", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml",
    ".xml", ".html", ".htm", ".css", ".c", ".h", ".cpp", ".hpp", ".java", ".cs", ".go", ".rs",
    ".sql", ".sh", ".ps1", ".bat",
)
CSV_EXTENSIONS = (".csv", ".tsv")
DOCUMENT_EXTENSIONS = (
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".zip",
)
DEFAULT_SUPPORTED_EXTENSIONS = (
    IMAGE_EXTENSIONS + TEXT_EXTENSIONS + MARKDOWN_EXTENSIONS + PDF_EXTENSIONS
    + CODE_EXTENSIONS + CSV_EXTENSIONS + ("",)
)
_EXTENSION_KINDS = {
    **dict.fromkeys(IMAGE_EXTENSIONS, FileKind.IMAGE),
    **dict.fromkeys(TEXT_EXTENSIONS, FileKind.TEXT),
    **dict.fromkeys(MARKDOWN_EXTENSIONS, FileKind.MARKDOWN),
    **dict.fromkeys(PDF_EXTENSIONS, FileKind.PDF),
    **dict.fromkeys(CODE_EXTENSIONS, FileKind.CODE),
    **dict.fromkeys(CSV_EXTENSIONS, FileKind.CSV),
    **dict.fromkeys(DOCUMENT_EXTENSIONS, FileKind.DOCUMENT),
}


@dataclass(frozen=True)
class FileInfo:
    """Immutable local-file metadata and sampled encoding, not a decoding guarantee.

    Encoding fields are None for non-text files; confidence describes only the
    bounded sample, and malformed bytes beyond that sample may still occur.
    """

    path: Path
    kind: FileKind
    size_bytes: int
    modified_time_ns: int
    extension: str
    encoding: str | None
    encoding_confidence: float | None


def _media_kind(sample: bytes) -> FileKind | None:
    """Return a recognized raster/PDF signature category, or None."""
    if sample.startswith(b"%PDF-"):
        return FileKind.PDF
    if (
        sample.startswith(b"\x89PNG\r\n\x1a\n")
        or sample.startswith(b"\xff\xd8\xff")
        or sample.startswith((b"GIF87a", b"GIF89a", b"BM"))
        or (sample.startswith(b"RIFF") and sample[8:12] == b"WEBP")
        or sample.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"))
        or sample.startswith(b"\x00\x00\x01\x00")
    ):
        return FileKind.IMAGE
    return None


def _bom_encoding(sample: bytes) -> str | None:
    """Return BOM-aware codec names, checking UTF-32 before the UTF-16 prefix."""
    for signatures, encoding in (
        ((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE), "utf-32"),
        ((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE), "utf-16"),
        ((codecs.BOM_UTF8,), "utf-8-sig"),
    ):
        if sample.startswith(signatures):
            return encoding
    return None


def _looks_binary(sample: bytes) -> bool:
    """Identify NUL or over ten percent non-whitespace ASCII control bytes."""
    if b"\x00" in sample:
        return True
    controls = sum(byte < 32 and byte not in (9, 10, 11, 12, 13) or byte == 127 for byte in sample)
    return bool(sample) and controls / len(sample) > 0.10


def _detect_encoding(sample: bytes, *, complete: bool) -> tuple[str | None, float]:
    """Try strict incremental UTF-8, then bounded chardet; raise PreviewError if unavailable."""
    try:
        codecs.getincrementaldecoder("utf-8")(errors="strict").decode(sample, final=complete)
        return "utf-8", 1.0
    except UnicodeDecodeError:
        pass
    try:
        import chardet

        result = chardet.detect(sample, max_bytes=len(sample), prefer_superset=True)
    except (ImportError, TypeError, ValueError) as exc:
        raise PreviewError("Text encoding detection failed; check the chardet runtime dependency") from exc
    encoding = result.get("encoding")
    confidence = result.get("confidence", 0.0)
    if not isinstance(encoding, str):
        return None, 0.0
    try:
        codecs.lookup(encoding)
        confidence = float(confidence)
    except (LookupError, TypeError, ValueError):
        return None, 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    return encoding, max(0.0, min(1.0, confidence))


class FileTypeDetector:
    """Identify local files using at most 64 KiB of content, independently of configuration."""

    def detect(self, path: str | Path) -> FileInfo:
        """Return metadata/category/encoding or raise FileAccessError/PreviewError.

        Performs bounded synchronous disk I/O: GUI callers must run this in a
        worker, never directly inside a Tk callback. Revalidate just before the
        content read and reject observed size/mtime changes rather than retrying.
        Supported-extension configuration affects rendering, not classification.
        """
        from offlook.platforms.windows_files import validate_local_file

        local_path = validate_local_file(path)
        try:
            before = local_path.stat()
            validate_local_file(local_path)
            with local_path.open("rb") as stream:
                sample = stream.read(min(65536, before.st_size))
            after = local_path.stat()
        except (OSError, ValueError) as exc:
            raise FileAccessError("Cannot read the file; it may have disappeared or be in use") from exc
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
            or len(sample) != min(65536, before.st_size)
        ):
            raise FileAccessError("The file changed during detection; preview it again")
        extension = local_path.suffix.lower()
        declared = _EXTENSION_KINDS.get(extension)
        media = _media_kind(sample)
        if media is not None or declared in (FileKind.IMAGE, FileKind.PDF):
            kind = declared if declared in (FileKind.IMAGE, FileKind.PDF) else media
            return FileInfo(local_path, kind, before.st_size, before.st_mtime_ns, extension, None, None)
        encoding = _bom_encoding(sample)
        confidence = 1.0
        if encoding is None:
            if _looks_binary(sample):
                return FileInfo(local_path, FileKind.BINARY, before.st_size, before.st_mtime_ns, extension, None, None)
            encoding, confidence = _detect_encoding(sample, complete=len(sample) == before.st_size)
        kind = declared or (FileKind.TEXT if confidence >= 0.70 else FileKind.BINARY)
        if kind is FileKind.BINARY:
            encoding = None
            encoding_confidence = None
        else:
            encoding_confidence = confidence
        return FileInfo(local_path, kind, before.st_size, before.st_mtime_ns, extension, encoding, encoding_confidence)
