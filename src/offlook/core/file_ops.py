"""Safe, bounded local file-management operations shared by the UI and AI port.

Every operation restricts itself to validated local drive-letter paths: UNC,
alternate data streams, network drives, and symlinks/reparse points are not
followed. Move/copy are blocking disk operations; callers own thread selection
and must not run them inside a Tk callback. Results are returned per file so a
batch never loses individual failures.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import ntpath
import os
from pathlib import Path
import re
import shutil

from .errors import FileAccessError
from .files import FileKind
from .search import _iter_files, _kind_for_extension, _validate_folder


@dataclass(frozen=True)
class TransferResult:
    """One source file's move/copy outcome with a stable status token."""

    source: Path
    destination: Path
    status: str  # "moved" | "copied" | "skipped" | "failed"
    message: str = ""


def _validate_local_path_string(raw: str) -> str:
    """Reject URLs, UNC, ADS, and nonstandard drive letters without OS I/O."""
    raw = raw.replace("/", "\\")
    if raw.startswith("\\\\"):
        raise FileAccessError("Network UNC and extended namespace paths are not allowed")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) and not re.match(r"^[A-Za-z]:", raw):
        raise FileAccessError("URLs and nonstandard drive-letter paths are not allowed")
    if ":" in raw[2:] or (":" in raw and not re.match(r"^[A-Za-z]:", raw)):
        raise FileAccessError("NTFS alternate data streams and nonstandard drive-letter paths are not allowed")
    try:
        normalized = ntpath.abspath(raw) if os.name == "nt" else os.path.abspath(raw)
    except (OSError, ValueError) as exc:
        raise FileAccessError("Cannot normalize the path") from exc
    drive, tail = ntpath.splitdrive(normalized)
    if not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\"):
        raise FileAccessError("Only local standard drive-letter paths are allowed")
    return normalized


def _validate_file_path(path: str | Path) -> Path:
    """Validate and return an existing local regular file without following links."""
    try:
        raw = os.fspath(path)
    except TypeError as exc:
        raise FileAccessError("The file path must be a string or Path") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise FileAccessError("The file path is empty or contains invalid characters")
    if os.name == 'nt':
        from offlook.platforms.windows_files import validate_local_file

        return validate_local_file(raw)
    normalized = Path(_validate_local_path_string(raw))
    try:
        if normalized.is_symlink() or not normalized.is_file():
            raise FileAccessError("Select an existing local regular file")
    except OSError as exc:
        raise FileAccessError("Cannot access the file") from exc
    return normalized


def _prepare_destination(destination: str | Path) -> Path:
    """Validate a destination folder path and create it if it is missing."""
    try:
        raw = os.fspath(destination)
    except TypeError as exc:
        raise FileAccessError("The destination must be a string or Path") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise FileAccessError("The destination is empty or contains invalid characters")
    normalized = Path(_validate_local_path_string(raw))
    try:
        if os.name == 'nt':
            from offlook.platforms.windows_files import validate_local_folder

            for ancestor in (normalized, *normalized.parents):
                if _occupied(ancestor):
                    validate_local_folder(ancestor)
                    break
            normalized.mkdir(parents=True, exist_ok=True)
            return normalized
        if normalized.exists():
            if normalized.is_symlink() or not normalized.is_dir():
                raise FileAccessError("The destination must be a local folder")
        else:
            normalized.mkdir(parents=True, exist_ok=True)
    except FileAccessError:
        raise
    except OSError as exc:
        raise FileAccessError(f"Cannot create the destination folder: {exc}") from exc
    return normalized


def _occupied(path: Path) -> bool:
    """A dangling link occupies a name just as an ordinary file does."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _resolve_conflict(source: Path, destination: Path, conflict: str) -> tuple[Path, str]:
    """Choose or validate the destination without passing a directory to shutil."""
    if not _occupied(destination):
        return destination, "proceed"
    if conflict == "skip":
        return destination, "skip"
    if conflict == "overwrite":
        _validate_file_path(destination)
        if source.samefile(destination):
            raise FileAccessError("Source and destination are the same file")
        return destination, "proceed"
    counter = 1
    while True:
        candidate = destination.with_name(f"{destination.stem} ({counter}){destination.suffix}")
        if not _occupied(candidate):
            return candidate, "proceed"
        counter += 1


def _transfer(
    paths: Iterable[str | Path],
    destination: str | Path,
    *,
    operation: str,
    conflict: str,
) -> tuple[TransferResult, ...]:
    """Move or copy each source into ``destination`` with per-file reporting."""
    if conflict not in ("rename", "skip", "overwrite"):
        raise FileAccessError("The conflict policy must be rename, skip, or overwrite")
    dest_dir = _prepare_destination(destination)
    results: list[TransferResult] = []
    for path in paths:
        try:
            source = _validate_file_path(path)
            target, decision = _resolve_conflict(source, dest_dir / source.name, conflict)
            if decision == "skip":
                results.append(TransferResult(source, target, "skipped", "A file with the same name exists"))
                continue
            if operation == "move":
                shutil.move(str(source), str(target))
                status = "moved"
            else:
                shutil.copy2(str(source), str(target))
                status = "copied"
            results.append(TransferResult(source, target, status))
        except FileAccessError as exc:
            results.append(TransferResult(Path(os.fspath(path)), dest_dir, "failed", str(exc)))
        except OSError as exc:
            results.append(TransferResult(Path(os.fspath(path)), dest_dir, "failed", str(exc)))
    return tuple(results)


def list_folder(folder: str | Path, *, filename: str = "") -> tuple[Path, ...]:
    """Return local regular files (not directories) under ``folder`` recursively."""
    root = _validate_folder(folder)
    if not isinstance(filename, str):
        raise FileAccessError("The filename filter must be text")
    return tuple(_iter_files(root, filename.casefold().strip()))


def move_files(
    paths: Iterable[str | Path],
    destination: str | Path,
    *,
    conflict: str = "rename",
) -> tuple[TransferResult, ...]:
    """Move every source file into ``destination``, never overwriting by default."""
    return _transfer(paths, destination, operation="move", conflict=conflict)


def copy_files(
    paths: Iterable[str | Path],
    destination: str | Path,
    *,
    conflict: str = "rename",
) -> tuple[TransferResult, ...]:
    """Copy every source file into ``destination``, never overwriting by default."""
    return _transfer(paths, destination, operation="copy", conflict=conflict)


def organize_by_kind(
    folder: str | Path,
    destination: str | Path,
    *,
    kinds: Iterable[FileKind] = (),
) -> tuple[TransferResult, ...]:
    """Move matching files into per-category subfolders under ``destination``.

    Each ``FileKind`` becomes a subfolder name (e.g. ``pdf``); files are moved
    there, so archiving by type is a single safe operation. The source scan is
    materialized before any move, so a destination nested inside ``folder`` is
    never re-traversed.
    """
    root = _validate_folder(folder)
    normalized_kinds = tuple(kinds)
    for kind in normalized_kinds:
        if not isinstance(kind, FileKind):
            raise FileAccessError("The document type filter is invalid")
    dest_root = _prepare_destination(destination)
    matches: list[tuple[Path, FileKind]] = []
    for path in _iter_files(root, ""):
        kind = _kind_for_extension(path)
        if normalized_kinds and kind not in normalized_kinds:
            continue
        matches.append((path, kind))
    for kind in normalized_kinds:
        _prepare_destination(dest_root / kind.value)
    results: list[TransferResult] = []
    for path, kind in matches:
        results.extend(move_files([path], dest_root / kind.value))
    return tuple(results)


__all__ = [
    "TransferResult",
    "copy_files",
    "list_folder",
    "move_files",
    "organize_by_kind",
]
