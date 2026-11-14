"""Explicit trusted-Python action callbacks; no plugin discovery or business actions."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from .errors import ExtensionError

if TYPE_CHECKING:
    from .context import AppContext


@dataclass(frozen=True)
class ActionRequest:
    """Paths and shallow read-only options passed to an explicitly registered action.

    Actions are trusted Python code, not sandboxed or automatically offline.
    Registration does not grant any built-in conversion/search/AI behavior.
    """

    paths: tuple[Path, ...]
    options: Mapping[str, object]

    def __post_init__(self) -> None:
        """Freeze the outer containers without reading or resolving supplied paths."""
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


ActionCallback = Callable[[ActionRequest, "AppContext"], object]


class ActionRegistry:
    """Store named callbacks and invoke them synchronously on the caller's thread."""

    def __init__(self) -> None:
        """Create an empty registry; no external modules or callbacks are loaded."""
        self._callbacks: dict[str, ActionCallback] = {}

    @staticmethod
    def _validate_name(name: str) -> None:
        """Raise ExtensionError for non-string, empty, or whitespace-only names."""
        if not isinstance(name, str) or not name.strip():
            raise ExtensionError("The action name must be a nonempty string")

    def register(self, name: str, callback: ActionCallback) -> None:
        """Register a callable under a unique name or raise ExtensionError."""
        self._validate_name(name)
        if not callable(callback):
            raise ExtensionError("The action callback must be callable")
        if name in self._callbacks:
            raise ExtensionError(f"Action already registered: {name}")
        self._callbacks[name] = callback

    def unregister(self, name: str) -> None:
        """Remove a named action; a valid but missing name is an idempotent no-op."""
        self._validate_name(name)
        self._callbacks.pop(name, None)

    def invoke(self, name: str, request: ActionRequest, context: "AppContext") -> object:
        """Return callback(request, context); wrap callback failures with their cause.

        Raise ExtensionError for an unknown/invalid name or any callback Exception.
        Callers own thread selection and must not block the Tk main loop with
        slow actions. No background scheduling or automatic validation is added.
        """
        self._validate_name(name)
        try:
            callback = self._callbacks[name]
        except KeyError as exc:
            raise ExtensionError(f"Action not registered: {name}") from exc
        try:
            return callback(request, context)
        except Exception as exc:
            raise ExtensionError(f"Action execution failed: {name} ({type(exc).__name__})") from exc
