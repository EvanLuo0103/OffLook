"""Bounded local ZIP and 7z extraction with path traversal protection."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

from .errors import ConversionError

MAX_MEMBERS = 20_000
MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024  # 2 GiB


def _member_path(root: Path, name: str) -> Path:
    """Resolve an archive member under root; reject absolute/traversal paths."""
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)

    if (
        not normalized
        or normalized.startswith("/")
        or (member.parts and ":" in member.parts[0])
        or any(part in ("..", "") for part in member.parts)
    ):
        raise ConversionError(f"Unsafe archive member path: {name}")

    root_resolved = root.resolve()
    destination = root.joinpath(*member.parts).resolve()

    try:
        destination.relative_to(root_resolved)
    except ValueError as exc:
        raise ConversionError(f"Archive member escapes the output folder: {name}") from exc

    return destination


def _check_limits(member_count: int, total_size: int) -> None:
    if member_count > MAX_MEMBERS:
        raise ConversionError("Archive contains too many entries")
    if total_size > MAX_TOTAL_SIZE:
        raise ConversionError("Archive is too large to extract (maximum is 2 GiB)")


def _collected_outputs(root: Path) -> tuple[Path, ...]:
    """Return extracted regular files, or the folder itself for an empty archive."""
    outputs: list[Path] = []
    root_resolved = root.resolve()

    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConversionError("Archive extraction produced a symbolic link")
        resolved = path.resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ConversionError("Extracted path escaped the output folder") from exc
        if path.is_file():
            outputs.append(path)

    return tuple(outputs) if outputs else (root,)


def _extract_zip(source: Path, root: Path) -> tuple[Path, ...]:
    total_size = 0

    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            total_size = sum(info.file_size for info in members)
            _check_limits(len(members), total_size)

            for info in members:
                destination = _member_path(root, info.filename)
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)

                if file_type == stat.S_IFLNK:
                    raise ConversionError("ZIP archives containing symbolic links are not supported")
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ConversionError("ZIP archives containing special files are not supported")

                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue

                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as input_stream:
                    with destination.open("xb") as output_stream:
                        shutil.copyfileobj(input_stream, output_stream)

    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Cannot extract ZIP archive: {exc}") from exc

    return _collected_outputs(root)


def extract_archive(source: Path, destination: Path) -> tuple[Path, ...]:
    """Extract a ZIP or 7z archive to a new destination folder."""
    source = Path(source)
    destination = Path(destination)

    if destination.exists():
        raise ConversionError(f"Extraction folder already exists: {destination}")

    try:
        destination.mkdir(parents=True)
    except OSError as exc:
        raise ConversionError(f"Cannot create extraction folder: {exc}") from exc

    suffix = source.suffix.lower()
    if source.suffix.lower() == ".zip":
        return _extract_zip(source, destination)

    raise ConversionError("Only ZIP archives can be extracted")
