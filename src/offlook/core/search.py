"""Bounded recursive local-file search by name and detected document category."""

from __future__ import annotations

from dataclasses import dataclass
import ntpath
import os
from pathlib import Path
import re

from .errors import FileAccessError
from .files import FileKind


@dataclass(frozen=True)
class SearchResult:
    """A matching file and its extension-based document category."""

    path: Path
    kind: FileKind


def _validate_folder(folder: str | Path) -> Path:
    """Validate a selected local folder without following links or network paths."""
    try:
        raw = os.fspath(folder)
    except TypeError as exc:
        raise FileAccessError("The search folder must be a string or Path") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise FileAccessError("The search folder is empty or contains invalid characters")
    if os.name == "nt":
        raw = raw.replace("/", "\\")
    if raw.startswith("\\\\") or (
        re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw)
        and not re.match(r"^[A-Za-z]:", raw)
    ):
        raise FileAccessError("Only local folders can be searched")
    if ":" in raw[2:] or (":" in raw and not re.match(r"^[A-Za-z]:", raw)):
        raise FileAccessError("Alternate data stream paths are not allowed")
    try:
        normalized = Path(ntpath.abspath(raw) if os.name == "nt" else os.path.abspath(raw))
        if not normalized.is_dir():
            raise FileAccessError("Select an existing folder")
    except (OSError, ValueError) as exc:
        raise FileAccessError("Cannot access the selected folder") from exc
    return normalized


def _kind_for_extension(path: Path) -> FileKind:
    """Classify a search result using the same extension categories as previews."""
    from .files import _EXTENSION_KINDS

    return _EXTENSION_KINDS.get(path.suffix.lower(), FileKind.BINARY)


def find_files(
    folder: str | Path,
    *,
    filename: str = "",
    kind: FileKind | None = None,
) -> tuple[SearchResult, ...]:
    """Recursively find local regular files matching name and document category.

    ``filename`` is a case-insensitive substring match against the file name.
    Search does not read file contents, follow symlinks/reparse points, or
    traverse directories that cannot be inspected.
    """
    root = _validate_folder(folder)
    if not isinstance(filename, str):
        raise FileAccessError("The filename filter must be text")
    if kind is not None and not isinstance(kind, FileKind):
        raise FileAccessError("The document type filter is invalid")
    needle = filename.casefold().strip()
    matches: list[SearchResult] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name.casefold())
        except OSError as exc:
            if current == root:
                raise FileAccessError("Cannot read the selected folder") from exc
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            path = Path(entry.path)
            if needle not in entry.name.casefold():
                continue
            entry_kind = _kind_for_extension(path)
            if kind is None or entry_kind is kind:
                matches.append(SearchResult(path, entry_kind))
    return tuple(matches)
