"""Public configuration, event, action, context, and bounded file-identification APIs."""

from .ai import (
    AiMessageResult,
    AiProvider,
    AiRunResult,
    AiToolRegistry,
    OpenAiCompatibleProvider,
    ToolCall,
    ToolStep,
    default_tools,
    run_instruction,
)
from .config import ConfigManager, PreviewConfig
from .context import AppContext, create_context
from .conversion import (
    ConversionOutcome,
    convert_file,
    convert_files,
    format_group,
    format_label,
    normalize_mode,
    normalize_target,
    reachable_targets,
    target_formats,
)
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
from .file_ops import TransferResult, copy_files, list_folder, move_files, organize_by_kind
from .files import DEFAULT_SUPPORTED_EXTENSIONS, FileInfo, FileKind, FileTypeDetector
from .hotkeys import HotkeySpec, parse_hotkey
from .git_diff import FileComparison, GitComparison, compare_files
from .search import SearchResult, filter_files, find_files

__all__ = [
    "ActionCallback", "ActionRegistry", "ActionRequest", "AiError", "AiMessageResult",
    "AiProvider", "AiRunResult", "AiToolRegistry", "AppContext", "ConfigError",
    "ConfigManager", "ConversionError", "ConversionOutcome", "DEFAULT_SUPPORTED_EXTENSIONS",
    "Event", "EventBus", "ExtensionError", "FileAccessError", "FileInfo", "FileKind",
    "FileTypeDetector", "HotkeyError", "HotkeySpec", "OffLookError", "OpenAiCompatibleProvider",
    "PreviewConfig", "FileComparison", "GitComparison", "compare_files", "PreviewError", "SearchResult", "ToolCall", "ToolStep", "TransferResult",
    "convert_file", "convert_files", "copy_files", "create_context", "default_tools",
    "filter_files", "find_files", "format_group", "format_label", "list_folder", "move_files",
    "normalize_mode", "normalize_target", "organize_by_kind", "parse_hotkey", "reachable_targets",
    "run_instruction", "target_formats",
]
