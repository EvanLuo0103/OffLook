"""Windows Credential Manager storage for OffLook API keys.

The module intentionally imports pywin32 only when an operation is requested so
configuration parsing and non-Windows installations remain usable.
"""

from __future__ import annotations

import sys
from typing import Any

from ..core.errors import ConfigError

_MAX_KEY_BYTES = 2560
_MISSING_ERROR = 1168


def _win32cred() -> Any:
    if sys.platform != "win32":
        raise ConfigError("Credential storage is available only on Windows")
    try:
        import win32cred  # type: ignore[import-not-found]
    except (ImportError, OSError):
        raise ConfigError("Windows Credential Manager is unavailable") from None
    return win32cred


def _target(target: str) -> str:
    if not isinstance(target, str) or not target:
        raise ConfigError("Credential target must be a non-empty string")
    if "\x00" in target:
        raise ConfigError("Credential target is invalid")
    return target


def _encode_key(key: object) -> bytes:
    if not isinstance(key, str) or not key or "\x00" in key:
        raise ConfigError("API key must be a non-empty string without NUL characters")
    try:
        blob = key.encode("utf-16-le", "strict")
    except UnicodeError:
        raise ConfigError("API key is not valid UTF-16 text") from None
    if len(blob) > _MAX_KEY_BYTES:
        raise ConfigError("API key exceeds the 2560-byte limit")
    return blob


def read_api_key(target: str) -> str | None:
    """Read a UTF-16LE Generic credential, returning ``None`` when absent."""
    win32cred = _win32cred()
    target = _target(target)
    try:
        record = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception as exc:  # pywin32 exposes a platform-specific exception
        if getattr(exc, "winerror", None) == _MISSING_ERROR:
            return None
        raise ConfigError("Could not read the Windows credential") from None
    try:
        blob = record.get("CredentialBlob")
    except AttributeError:
        raise ConfigError("Windows credential data is invalid") from None
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise ConfigError("Windows credential data is invalid")
    raw = bytes(blob)
    if len(raw) > _MAX_KEY_BYTES:
        raise ConfigError("Windows credential data is invalid")
    try:
        value = raw.decode("utf-16-le", "strict")
    except UnicodeError:
        raise ConfigError("Windows credential data is invalid") from None
    if not value or "\x00" in value:
        raise ConfigError("Windows credential data is invalid")
    return value


def write_api_key(target: str, key: str) -> None:
    """Write a machine-persistent Generic credential."""
    win32cred = _win32cred()
    target = _target(target)
    _encode_key(key)  # Check the size before pywin32 encodes the Unicode string.
    record = {
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": target,
        "CredentialBlob": key,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "UserName": "OffLook",
    }
    try:
        win32cred.CredWrite(record, 0)
    except Exception:
        raise ConfigError("Could not save the Windows credential") from None


def delete_api_key(target: str) -> None:
    """Delete a credential; a missing entry is already in the desired state."""
    win32cred = _win32cred()
    target = _target(target)
    try:
        win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception as exc:  # pywin32 exposes a platform-specific exception
        if getattr(exc, "winerror", None) != _MISSING_ERROR:
            raise ConfigError("Could not delete the Windows credential") from None


__all__ = ["delete_api_key", "read_api_key", "write_api_key"]
