"""Safe, bounded local file-management operations shared by the UI and AI port.

Every operation restricts itself to validated local drive-letter paths: UNC,
alternate data streams, network drives, and symlinks/reparse points are not
followed. Move/copy are blocking disk operations; callers own thread selection
and must not run them inside a Tk callback. Results are returned per file so a
batch never loses individual failures.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat

from offlook.platforms.windows_files import validate_local_folder

from .errors import FileAccessError
from .files import FileKind
from .search import _iter_files, _kind_for_extension, _validate_folder

_MAX_AI_WRITE_ITEMS = 200
_AI_WRITE_TOOLS = ("move_files", "copy_files", "organize_by_kind")
_AI_FILES_CHANGED = "Files changed since preview; run the instruction again."
_RESERVED_WINDOWS_NAME = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])", re.I)


@dataclass(frozen=True)
class TransferResult:
    """One source file's move/copy outcome with a stable status token."""

    source: Path
    destination: Path
    status: str  # "moved" | "copied" | "skipped" | "failed"
    message: str = ""


@dataclass(frozen=True)
class AiWriteItem:
    """One exact source/target pair as shown in the approval preview."""

    source: Path
    destination: Path
    source_stamp: tuple[int, int, int, int]
    skip: bool


@dataclass(frozen=True)
class AiWritePlan:
    """An immutable batch of file changes and the new directories it needs."""

    tool: str
    items: tuple[AiWriteItem, ...]
    directories: tuple[Path, ...]


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


def _ai_path(value: object) -> str:
    if not isinstance(value, str):
        raise FileAccessError("AI file changes require absolute local drive-letter paths")
    drive, tail = ntpath.splitdrive(value.replace("/", "\\"))
    if not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\"):
        raise FileAccessError("AI file changes require absolute local drive-letter paths")
    for component in tail.split("\\"):
        if component in ("", ".", ".."):
            continue
        if (
            component.endswith((".", " "))
            or _RESERVED_WINDOWS_NAME.fullmatch(component.partition(".")[0].rstrip(" "))
            or any(char in '<>:"|?*' or ord(char) < 32 for char in component)
        ):
            raise FileAccessError("AI file changes require ordinary Windows file and folder names")
    return _validate_local_path_string(value)


def _source_stamp(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _ai_organize_sources(root: Path, kinds: frozenset[FileKind]) -> Iterable[tuple[Path, FileKind]]:
    for path in _iter_files(root, ""):
        kind = _kind_for_extension(path)
        if not kinds or kind in kinds:
            yield path, kind


def _ai_target(source: Path, folder: Path, conflict: str, reserved: set[str]) -> tuple[Path, bool]:
    target = folder / source.name
    counter = 0
    while True:
        key = ntpath.normcase(str(target))
        if key not in reserved and not _occupied(target):
            reserved.add(key)
            return target, False
        if conflict == "skip":
            return target, True
        counter += 1
        target = folder / f"{source.stem} ({counter}){source.suffix}"


def prepare_ai_write(tool: str, arguments: Mapping[str, object]) -> AiWritePlan:
    """Validate and freeze a default AI tool's exact write set without writing."""
    if tool not in _AI_WRITE_TOOLS:
        raise FileAccessError("Unsupported AI file change tool")
    conflict = arguments.get("conflict", "rename")
    if not isinstance(conflict, str) or conflict not in ("rename", "skip"):
        raise FileAccessError("The AI conflict policy must be rename or skip")
    destination = validate_local_folder(_ai_path(arguments.get("destination")))
    candidates: Iterable[tuple[str | Path, FileKind | None]]
    if tool == "organize_by_kind":
        raw_kinds = arguments.get("kinds", [])
        if not isinstance(raw_kinds, list) or not all(isinstance(kind, str) for kind in raw_kinds):
            raise FileAccessError("Document kinds must be a list of strings")
        try:
            kinds = frozenset(FileKind(kind) for kind in raw_kinds)
        except ValueError:
            raise FileAccessError("Unsupported document kind") from None
        root = validate_local_folder(_ai_path(arguments.get("folder")))
        try:
            # Compare identities as well as names: short Windows names and drive
            # aliases must not let an archive destination sit in its own source tree.
            if destination.is_relative_to(root) or any(
                root.samefile(folder) for folder in (destination, *destination.parents)
            ):
                raise FileAccessError("The organize destination must be outside the source folder")
        except OSError:
            raise FileAccessError("Cannot verify that the organize destination is outside the source folder") from None
        candidates = _ai_organize_sources(root, kinds)
    else:
        paths = arguments.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
            raise FileAccessError("Source paths must be a nonempty list of strings")
        if len(paths) > _MAX_AI_WRITE_ITEMS:
            raise FileAccessError(f"AI file changes are limited to {_MAX_AI_WRITE_ITEMS} files")
        candidates = ((path, None) for path in paths)

    seen: set[str] = set()
    reserved: set[str] = set()
    categories: dict[Path, bool] = {}
    directories: dict[Path, None] = {}
    items: list[AiWriteItem] = []
    try:
        for path, kind in candidates:
            if len(items) == _MAX_AI_WRITE_ITEMS:
                raise FileAccessError(f"AI file changes are limited to {_MAX_AI_WRITE_ITEMS} files")
            source = _validate_file_path(_ai_path(str(path)))
            key = ntpath.normcase(str(source))
            if key in seen:
                raise FileAccessError("Duplicate source files are not allowed in an AI write plan")
            seen.add(key)
            if tool != "copy_files" and source.drive.lower() != destination.drive.lower():
                raise FileAccessError("AI moves require the same drive; use copy to transfer across drives")

            folder = destination if kind is None else destination / kind.value
            if kind is not None and folder not in categories:
                categories[folder] = _occupied(folder)
                if categories[folder]:
                    validate_local_folder(folder)
            target, skip = _ai_target(source, folder, conflict, reserved)
            if not skip and kind is not None and not categories[folder]:
                directories[folder] = None
            items.append(AiWriteItem(source, target, _source_stamp(source), skip))
    except (OSError, ValueError):
        raise FileAccessError("Cannot inspect files or folders for the AI write preview") from None
    return AiWritePlan(tool, tuple(items), tuple(directories))


def _check_ai_source(item: AiWriteItem) -> None:
    if _source_stamp(_validate_file_path(item.source)) != item.source_stamp:
        raise FileAccessError(_AI_FILES_CHANGED)


def _ai_destination_root(tool: str, item: AiWriteItem) -> Path:
    parent = item.destination.parent
    return parent.parent if tool == "organize_by_kind" else parent


def _check_ai_target(item: AiWriteItem) -> None:
    if _occupied(item.destination):
        raise FileAccessError(_AI_FILES_CHANGED)


def _copy_ai_item(item: AiWriteItem) -> None:
    identity = None
    try:
        with item.source.open("rb") as reader, item.destination.open("xb") as writer:
            info = os.fstat(writer.fileno())
            if info.st_ino:
                identity = info.st_dev, info.st_ino
            shutil.copyfileobj(reader, writer)
    except BaseException:
        if identity is not None:
            try:
                _validate_file_path(item.destination)
                info = item.destination.lstat()
                if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity:
                    item.destination.unlink()
            except (FileAccessError, OSError):
                pass  # Never remove a name we cannot identify as our own partial copy.
        raise


def execute_ai_write(plan: AiWritePlan) -> tuple[TransferResult, ...]:
    """Execute an approved plan exactly; never overwrite or reselect a name.

    These checks cover common changes during approval, not adversarial races
    replacing local directories between a check and a filesystem operation.
    """
    if plan.tool not in _AI_WRITE_TOOLS:
        raise FileAccessError("Unsupported AI file change tool")
    new_dirs = set(plan.directories)
    checked_dirs: set[Path] = set()
    try:
        for item in plan.items:
            if item.skip:
                continue
            _check_ai_source(item)
            root = _ai_destination_root(plan.tool, item)
            if root not in checked_dirs:
                validate_local_folder(root)
                checked_dirs.add(root)
            parent = item.destination.parent
            if parent not in checked_dirs:
                if parent in new_dirs:
                    if _occupied(parent):
                        raise FileAccessError(_AI_FILES_CHANGED)
                else:
                    validate_local_folder(parent)
                checked_dirs.add(parent)
            _check_ai_target(item)
    except (FileAccessError, OSError, ValueError):
        raise FileAccessError(_AI_FILES_CHANGED) from None

    mkdir_error = ""
    for folder in plan.directories:
        try:
            validate_local_folder(folder.parent)
            folder.mkdir()
        except (FileAccessError, FileExistsError, FileNotFoundError, NotADirectoryError):
            mkdir_error = _AI_FILES_CHANGED
            break
        except OSError:
            mkdir_error = "Could not create the approved destination folder."
            break

    results: list[TransferResult] = []
    for item in plan.items:
        if item.skip:
            status, message = "skipped", "A file with the same name exists or was reserved in the plan"
        elif mkdir_error:
            status, message = "failed", mkdir_error
        else:
            try:
                _check_ai_source(item)
                validate_local_folder(item.destination.parent)
                _check_ai_target(item)
                if plan.tool == "copy_files":
                    _copy_ai_item(item)
                    status = "copied"
                else:
                    os.rename(item.source, item.destination)  # Windows fails if the target exists.
                    status = "moved"
                message = ""
            except (FileAccessError, FileExistsError, FileNotFoundError, NotADirectoryError):
                status, message = "failed", _AI_FILES_CHANGED
            except OSError:
                status, message = "failed", "Could not transfer the file to the approved destination."
        results.append(TransferResult(item.source, item.destination, status, message))
    return tuple(results)


__all__ = [
    "AiWriteItem",
    "AiWritePlan",
    "TransferResult",
    "copy_files",
    "execute_ai_write",
    "list_folder",
    "move_files",
    "organize_by_kind",
    "prepare_ai_write",
]
