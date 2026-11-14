"""Domain exceptions exposed by OffLook's local preview framework."""


class OffLookError(Exception):
    """Base exception for an expected framework failure; carries a user-facing message."""


class ConfigError(OffLookError):
    """Report invalid configuration or a failed configuration read/write operation."""


class FileAccessError(OffLookError):
    """Report an unsafe, missing, changed, or unreadable local file."""


class PreviewError(OffLookError):
    """Report a preview decoding, rendering, or renderer-registration failure."""


class HotkeyError(OffLookError):
    """Report an operating-system hotkey registration or message-loop failure."""


class ExtensionError(OffLookError):
    """Report invalid action registration, lookup, or execution."""
