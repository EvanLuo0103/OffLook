"""Public configuration, event, action, context, and bounded file-identification APIs."""

from .config import ConfigManager, PreviewConfig
from .context import AppContext, create_context
from .errors import (
    ConfigError,
    ExtensionError,
    FileAccessError,
    HotkeyError,
    OffLookError,
    PreviewError,
)
from .events import Event, EventBus
from .extensions import ActionCallback, ActionRegistry, ActionRequest
from .files import DEFAULT_SUPPORTED_EXTENSIONS, FileInfo, FileKind, FileTypeDetector
from .hotkeys import HotkeySpec, parse_hotkey

__all__ = [
    "ActionCallback", "ActionRegistry", "ActionRequest", "AppContext", "ConfigError",
    "ConfigManager", "DEFAULT_SUPPORTED_EXTENSIONS", "Event", "EventBus", "ExtensionError",
    "FileAccessError", "FileInfo", "FileKind", "FileTypeDetector", "HotkeyError", "OffLookError",
    "HotkeySpec", "PreviewConfig", "PreviewError", "create_context", "parse_hotkey",
]
