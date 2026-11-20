"""Public configuration, event, action, context, and bounded file-identification APIs."""

from importlib import import_module
from typing import TYPE_CHECKING

from .config import ConfigManager, PreviewConfig
from .context import AppContext, create_context
from .errors import (
    AiError,
    ConfigError,
    ConversionError,
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

if TYPE_CHECKING:
    from .ai import (
        AiMessageResult, AiProvider, AiRunResult, AiToolRegistry, OpenAiCompatibleProvider,
        ToolCall, ToolStep, default_tools, run_instruction,
    )
    from .conversion import (
        ConversionOutcome, convert_file, convert_files, format_group, format_label, normalize_mode,
        normalize_target, reachable_targets, target_formats,
    )
    from .file_comparison import FileComparison, compare_files
    from .file_ops import TransferResult, copy_files, list_folder, move_files, organize_by_kind
    from .search import SearchResult, filter_files, find_files

# A preview/Shell worker imports core submodules but does not need these features.
_LAZY_EXPORTS: dict[str, str] = {
    'AiMessageResult': '.ai', 'AiProvider': '.ai', 'AiRunResult': '.ai', 'AiToolRegistry': '.ai',
    'OpenAiCompatibleProvider': '.ai', 'ToolCall': '.ai', 'ToolStep': '.ai',
    'default_tools': '.ai', 'run_instruction': '.ai',
    'ConversionOutcome': '.conversion', 'convert_file': '.conversion', 'convert_files': '.conversion',
    'format_group': '.conversion', 'format_label': '.conversion', 'normalize_mode': '.conversion',
    'normalize_target': '.conversion', 'reachable_targets': '.conversion', 'target_formats': '.conversion',
    'FileComparison': '.file_comparison', 'compare_files': '.file_comparison',
    'TransferResult': '.file_ops', 'copy_files': '.file_ops', 'list_folder': '.file_ops',
    'move_files': '.file_ops', 'organize_by_kind': '.file_ops',
    'SearchResult': '.search', 'filter_files': '.search', 'find_files': '.search',
}


def __getattr__(name: str) -> object:
    module = _LAZY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_EXPORTS.keys())


__all__ = [
    "ActionCallback", "ActionRegistry", "ActionRequest", "AiError", "AiMessageResult",
    "AiProvider", "AiRunResult", "AiToolRegistry", "AppContext", "ConfigError",
    "ConfigManager", "ConversionError", "ConversionOutcome", "DEFAULT_SUPPORTED_EXTENSIONS",
    "Event", "EventBus", "ExtensionError", "FileAccessError", "FileInfo", "FileKind",
    "FileTypeDetector", "HotkeyError", "HotkeySpec", "OffLookError", "OpenAiCompatibleProvider",
    "PreviewConfig", "FileComparison", "compare_files", "PreviewError", "SearchResult", "ToolCall", "ToolStep", "TransferResult",
    "convert_file", "convert_files", "copy_files", "create_context", "default_tools",
    "filter_files", "find_files", "format_group", "format_label", "list_folder", "move_files",
    "normalize_mode", "normalize_target", "organize_by_kind", "parse_hotkey", "reachable_targets",
    "run_instruction", "target_formats",
]
