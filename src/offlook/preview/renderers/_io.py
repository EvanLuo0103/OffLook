"""Local-file checks shared by bounded renderers, without UI or network I/O."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, BinaryIO

from offlook.core.errors import FileAccessError
from offlook.core.files import FileInfo
from offlook.platforms.windows_files import validate_local_file


def check_unchanged(info: FileInfo) -> None:
    """Revalidate local attributes/stat; raise FileAccessError on replacement/change."""
    try:
        path = validate_local_file(info.path)
        stat = path.stat()
        if stat.st_size != info.size_bytes or stat.st_mtime_ns != info.modified_time_ns:
            raise FileAccessError("The file changed during preview; reopen it")
    except FileAccessError:
        raise
    except OSError as exc:
        raise FileAccessError(f"Cannot access the file: {exc}") from exc


@contextmanager
def open_checked(info: FileInfo) -> Iterator[BinaryIO]:
    """Yield a binary file after local validation and verify metadata after reading."""
    check_unchanged(info)
    try:
        stream = info.path.open("rb")
    except OSError as exc:
        raise FileAccessError(f"Cannot open the file: {exc}") from exc
    # Decoder failures belong to the renderer, not the file-opening boundary.
    with stream:
        yield stream
    check_unchanged(info)
