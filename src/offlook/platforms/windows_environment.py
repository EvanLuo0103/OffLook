"""Explicit, per-user PATH integration for the current installed OffLook command."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from importlib import metadata
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType

from offlook.core.errors import OffLookError


@dataclass(frozen=True)
class PathUpdateResult:
    """Report registry persistence, bounded notification, and command precedence."""

    scripts_dir: Path
    changed: bool
    broadcast_ok: bool
    conflicting_executable: Path | None


_INSTALL_HINT = "Reinstall using the current Python: py -m pip install --user --only-binary=:all: -e ."


def resolve_offlook_scripts_dir() -> Path:
    """Resolve the unique existing offlook.exe from this interpreter's package record.

    No guessed user Scripts directory or executable from PATH is accepted.
    Missing, ambiguous, or stale installation metadata raises OffLookError.
    """
    try:
        distribution = metadata.distribution("offlook")
        records = distribution.files
        if records is None:
            raise OffLookError(f"OffLook installation metadata has no file records. {_INSTALL_HINT}")
        executables: set[Path] = set()
        for record in records:
            if record.name.casefold() != "offlook.exe":
                continue
            executable = Path(distribution.locate_file(record)).resolve(strict=True)
            if not executable.is_file():
                raise OffLookError(f"The offlook.exe in the installation records is not a file. {_INSTALL_HINT}")
            executables.add(executable)
        if len(executables) != 1:
            raise OffLookError(f"Cannot identify a unique offlook.exe in the installation records. {_INSTALL_HINT}")
        return next(iter(executables)).parent
    except (metadata.PackageNotFoundError, OSError, ValueError, RuntimeError) as exc:
        raise OffLookError(f"Cannot locate the currently installed offlook.exe. {_INSTALL_HINT}") from exc


def _registry() -> ModuleType:
    """Import the registry only for an explicitly requested Windows operation."""
    if sys.platform != "win32":
        raise OffLookError("Adding to PATH is supported only on Windows")
    import winreg

    return winreg


def _normalized_entry(value: str) -> str:
    """Normalize only for comparison; never serialize the normalized original PATH."""
    value = value.strip().strip('"').strip()
    return os.path.normcase(os.path.normpath(os.path.expandvars(value))) if value else ""


def _merge_path(value: str, scripts_dir: Path) -> tuple[str, bool]:
    """Append once while preserving original characters, order, and empty entries."""
    if not isinstance(value, str) or "\x00" in value:
        raise OffLookError("PATH must be a string without null characters")
    directory = str(scripts_dir)
    normalized = _normalized_entry(directory)
    if any(_normalized_entry(entry) == normalized for entry in value.split(";")):
        merged, changed = value, False
    else:
        # Keep trailing empty entries too; an existing separator is not ours to remove.
        merged, changed = value + (";" if value else "") + directory, True
    if len(merged.encode("utf-16-le")) // 2 > 32767:
        raise OffLookError("The resulting PATH exceeds the 32767-character limit; settings were not written")
    return merged, changed


def _read_path(registry: ModuleType, key: object) -> tuple[str, int]:
    """Read a string PATH with its exact registry type, or supply the missing default."""
    try:
        value, value_type = registry.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return "", registry.REG_EXPAND_SZ
    if value_type not in (registry.REG_SZ, registry.REG_EXPAND_SZ) or not isinstance(value, str):
        raise OffLookError("The user PATH is not a REG_SZ or REG_EXPAND_SZ string; settings were not changed")
    return value, value_type


def _broadcast_environment_change() -> bool:
    """Notify windows synchronously with a bounded wait; persistence never depends on it."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        send = user32.SendMessageTimeoutW
        send.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        )
        send.restype = ctypes.c_ssize_t
        result = ctypes.c_size_t()
        # A live UTF-16 buffer avoids pywin32's version-dependent lParam conversion.
        environment = ctypes.create_unicode_buffer("Environment")
        return bool(send(
            0xFFFF, 0x001A, 0, ctypes.addressof(environment),
            0x0002 | 0x0020, 1000, ctypes.byref(result),
        ))
    except (OSError, AttributeError):
        return False


def add_offlook_to_user_path(*, registry_path: str = "Environment") -> PathUpdateResult:
    """Append this installation to HKCU PATH on explicit request and update this process.

    Existing text and REG_SZ/REG_EXPAND_SZ types are preserved. The latest value
    is re-read immediately before writing. No machine PATH, command precedence,
    shell process, or other installation is modified. Registry errors raise
    OffLookError; a failed broadcast is returned without rolling back a write.
    ``registry_path`` supports disposable integration-test keys.
    """
    registry = _registry()
    scripts_dir = resolve_offlook_scripts_dir()
    try:
        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER, registry_path, 0, registry.KEY_QUERY_VALUE,
            ) as key:
                original, _ = _read_path(registry, key)
        except FileNotFoundError:
            original = ""
        _merge_path(original, scripts_dir)
        _merge_path(os.environ.get("PATH", ""), scripts_dir)
        with registry.CreateKeyEx(
            registry.HKEY_CURRENT_USER, registry_path, 0,
            registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE,
        ) as key:
            # Another process may have edited PATH since the initial read.
            latest, value_type = _read_path(registry, key)
            merged, changed = _merge_path(latest, scripts_dir)
            if changed:
                registry.SetValueEx(key, "Path", 0, value_type, merged)
        process_path, process_changed = _merge_path(os.environ.get("PATH", ""), scripts_dir)
        if process_changed:
            os.environ["PATH"] = process_path
    except (OSError, ValueError) as exc:
        raise OffLookError("Cannot change the user PATH; check registry access permissions") from exc
    broadcast_ok = _broadcast_environment_change()
    resolved = shutil.which("offlook")
    conflicting_executable = None
    if resolved is not None and _normalized_entry(resolved) != _normalized_entry(str(scripts_dir / "offlook.exe")):
        conflicting_executable = Path(resolved)
    return PathUpdateResult(scripts_dir, changed, broadcast_ok, conflicting_executable)
