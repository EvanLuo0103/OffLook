"""Parse portable descriptions of supported Windows global shortcuts without I/O."""

from dataclasses import dataclass

from .errors import HotkeyError


@dataclass(frozen=True)
class HotkeySpec:
    """A canonical shortcut and its RegisterHotKey modifier and virtual-key values."""

    canonical: str
    modifiers: int
    virtual_key: int


def parse_hotkey(value: str) -> HotkeySpec:
    """Normalize a supported Ctrl/Alt shortcut or raise HotkeyError without OS calls."""
    if not isinstance(value, str) or not value.strip():
        raise HotkeyError("The hotkey must be a nonblank key combination string")
    tokens = [token.strip().upper() for token in value.split("+")]
    if any(not token for token in tokens):
        raise HotkeyError("The hotkey cannot contain empty keys")
    modifier_values = {"CTRL": 0x0002, "ALT": 0x0001, "SHIFT": 0x0004}
    modifiers = 0
    key: str | None = None
    for token in tokens:
        if token in {"WIN", "WINDOWS", "META", "SUPER", "LWIN", "RWIN"}:
            raise HotkeyError("Windows key combinations are reserved by the system; use Ctrl or Alt instead")
        if token in modifier_values:
            flag = modifier_values[token]
            if modifiers & flag:
                raise HotkeyError("The hotkey cannot repeat modifier keys")
            modifiers |= flag
        elif key is not None:
            raise HotkeyError("The hotkey must contain exactly one primary key")
        else:
            key = token
    if not modifiers & (0x0002 | 0x0001):
        raise HotkeyError("The hotkey must include Ctrl or Alt")
    if key is None:
        raise HotkeyError("Add Space, a letter, a digit, or F1–F11")
    if key == "F12":
        raise HotkeyError("F12 is reserved by the Windows debugger and cannot be used as a hotkey")
    if key == "SPACE":
        canonical_key, virtual_key = "Space", 0x20
    elif len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        canonical_key, virtual_key = key, ord(key)
    elif key in {f"F{number}" for number in range(1, 12)}:
        canonical_key, virtual_key = key, 0x70 + int(key[1:]) - 1
    else:
        raise HotkeyError("Only Space, A–Z, 0–9, and F1–F11 are supported")
    if modifiers == 0x0001 and key in {"F4", "SPACE"}:
        raise HotkeyError("Alt+F4 and Alt+Space are system actions; choose another combination")
    names = [name for name, flag in (("Ctrl", 2), ("Alt", 1), ("Shift", 4)) if modifiers & flag]
    return HotkeySpec("+".join((*names, canonical_key)), modifiers, virtual_key)
