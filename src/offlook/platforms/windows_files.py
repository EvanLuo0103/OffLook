"""Conservative Windows local-path validation before any preview or folder access.

This rejects common network/cloud redirections, but is not a security sandbox:
path replacement races and third-party filesystem drivers remain outside it.
"""

import ntpath
import os
from pathlib import Path
import re

from offlook.core.errors import FileAccessError

_REJECT_ATTRIBUTES = 0x400 | 0x1000 | 0x40000 | 0x400000
_DIRECTORY = 0x10
_DEVICE = 0x40


def _validate_local_path(path: str | Path, *, directory: bool) -> Path:
    """Validate ordinary local paths without following links or opening content."""
    subject = "folder" if directory else "file"
    try:
        raw = os.fspath(path)
    except TypeError as exc:
        raise FileAccessError(f"The {subject} path must be a string or Path") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise FileAccessError(f"The {subject} path is empty or contains invalid characters")
    raw = raw.replace("/", "\\")
    if raw.startswith("\\\\"):
        raise FileAccessError("Network UNC, device, and extended namespace paths are not allowed")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) and not re.match(r"^[A-Za-z]:", raw):
        raise FileAccessError("URLs and nonstandard drive-letter paths are not allowed")
    if ":" in raw[2:] or (":" in raw and not re.match(r"^[A-Za-z]:", raw)):
        raise FileAccessError("NTFS alternate data streams and nonstandard drive-letter paths are not allowed")
    try:
        normalized = ntpath.abspath(raw)
    except (OSError, ValueError) as exc:
        raise FileAccessError(f"Cannot normalize the {subject} path") from exc
    drive, tail = ntpath.splitdrive(normalized)
    if not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\"):
        raise FileAccessError("Only local standard drive-letter paths are allowed")
    if os.name != "nt":
        raise FileAccessError(f"OffLook currently supports only local Windows {subject}s")
    try:
        import pywintypes
        import win32api
        import win32file

        root = drive + "\\"
        if win32file.GetDriveType(root) not in (2, 3, 5, 6):
            raise FileAccessError("Network, unknown, or unavailable drives are rejected")
        components = [root]
        current = root
        for component in tail.split("\\"):
            if component:
                current = ntpath.join(current, component)
                components.append(current)
        final_attributes = 0
        for index, component_path in enumerate(components):
            try:
                attributes = win32file.GetFileAttributes(component_path)
            except pywintypes.error as exc:
                if directory and exc.winerror in (2, 3):
                    raise FileAccessError("Select an existing folder") from exc
                raise
            if attributes == -1 or attributes == 0xFFFFFFFF:
                if directory and win32api.GetLastError() in (2, 3):
                    raise FileAccessError("Select an existing folder")
                raise FileAccessError(f"Cannot read {subject} path attributes")
            if attributes & _REJECT_ATTRIBUTES:
                raise FileAccessError("Reparse points, offline files, and paths requiring cloud recall are rejected")
            if attributes & _DEVICE:
                raise FileAccessError("Device files are not allowed")
            if index < len(components) - 1 and not attributes & _DIRECTORY:
                raise FileAccessError(f"An intermediate {subject} path component is not a directory")
            final_attributes = attributes
        if directory:
            if not final_attributes & _DIRECTORY:
                raise FileAccessError("Select a local folder; regular files cannot be searched as folders")
        elif final_attributes & _DIRECTORY:
            raise FileAccessError("Select a regular file; directories cannot be previewed")
    except FileAccessError:
        raise
    except ImportError as exc:
        raise FileAccessError("The Windows file access dependency pywin32 is missing") from exc
    except Exception as exc:
        raise FileAccessError(f"The {subject} does not exist, is inaccessible, or is in use by another program") from exc
    return Path(normalized)


def validate_local_file(path: str | Path) -> Path:
    """Return a normalized Windows local ordinary-file path or raise FileAccessError.

    Reject UNC/device paths, URLs, alternate data streams, remote drives, and
    reparse/offline/recall-marked components without resolving filesystem links.
    """
    return _validate_local_path(path, directory=False)


def validate_local_folder(path: str | Path) -> Path:
    """Return an ordinary local directory using the same conservative file boundary."""
    return _validate_local_path(path, directory=True)
