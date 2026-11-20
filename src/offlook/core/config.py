"""Validated immutable preview settings and explicit, atomic JSON persistence."""

from dataclasses import asdict, dataclass, fields
import json
import math
import os
from pathlib import Path
import tempfile

from .errors import ConfigError, HotkeyError
from .events import EventBus
from .files import DEFAULT_SUPPORTED_EXTENSIONS
from .hotkeys import parse_hotkey

_LEGACY_SHORTCUT_FIELDS = ('hotkey', 'search_hotkey', 'diff_hotkey', 'convert_hotkey')
_FILTER_SHORTCUTS = ('Ctrl+Alt+F', 'Ctrl+Alt+Shift+F', 'Ctrl+Alt+G', 'Ctrl+Alt+Shift+G', 'Ctrl+Alt+J')


@dataclass(frozen=True)
class PreviewConfig:
    """Frozen per-request settings; invalid constructor values raise ConfigError.

    Sizes are bytes, timeout is seconds, and an empty suffix tuple disables all
    content renderers. Suffixes are deduplicated, lowercased, and dot-prefixed;
    the empty string explicitly enables suffixless files.
    """

    max_file_size_bytes: int = 10485760
    hotkey_enabled: bool = True
    preview_timeout_seconds: float = 5.0
    supported_extensions: tuple[str, ...] = DEFAULT_SUPPORTED_EXTENSIONS
    always_on_top: bool = False
    hotkey: str = "Ctrl+Space"
    search_hotkey: str = "Ctrl+Q"
    diff_hotkey: str = "Ctrl+Alt+D"
    convert_hotkey: str = "Alt+C"
    convert_mode: str = "auto"
    ai_enabled: bool = False
    ai_base_url: str = "https://api.deepseek.com"
    ai_api_key: str = ""
    ai_model: str = "deepseek-chat"
    language: str = "en"
    filter_hotkey: str = _FILTER_SHORTCUTS[0]

    def __post_init__(self) -> None:
        """Validate exact setting types and normalize suffixes without accepting glob patterns."""
        if type(self.max_file_size_bytes) is not int or self.max_file_size_bytes <= 0:
            raise ConfigError("max_file_size_bytes must be a positive integer (bytes)")
        if type(self.hotkey_enabled) is not bool or type(self.always_on_top) is not bool or type(self.ai_enabled) is not bool:
            raise ConfigError("hotkey_enabled, always_on_top, and ai_enabled must be booleans")
        shortcut_names = (*_LEGACY_SHORTCUT_FIELDS, 'filter_hotkey')
        for name in shortcut_names:
            try:
                canonical = parse_hotkey(getattr(self, name)).canonical
            except HotkeyError as exc:
                raise ConfigError(f"Invalid {name} setting: {exc}") from exc
            object.__setattr__(self, name, canonical)
        for index, first in enumerate(shortcut_names):
            for second in shortcut_names[index + 1:]:
                combo = getattr(self, first)
                if combo == getattr(self, second):
                    raise ConfigError(f"Shortcut combinations must be different: {first} and {second} both use {combo}")
        if self.convert_mode not in ("auto", "text", "office"):
            raise ConfigError("convert_mode must be 'auto', 'text', or 'office'")
        if not isinstance(self.ai_base_url, str) or not self.ai_base_url.strip():
            raise ConfigError("ai_base_url must be a nonblank HTTP(S) URL")
        ai_base_url = self.ai_base_url.strip().rstrip("/")
        if not (ai_base_url.startswith("http://") or ai_base_url.startswith("https://")):
            raise ConfigError("ai_base_url must start with http:// or https://")
        object.__setattr__(self, "ai_base_url", ai_base_url)
        if not isinstance(self.ai_api_key, str):
            raise ConfigError("ai_api_key must be a string")
        if not isinstance(self.ai_model, str) or not self.ai_model.strip():
            raise ConfigError("ai_model must be a nonblank string")
        if self.language not in ("en", "zh"):
            raise ConfigError("language must be 'en' or 'zh'")
        timeout = self.preview_timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ConfigError("preview_timeout_seconds must be a finite positive number (seconds)")
        try:
            normalized_timeout = float(timeout)
        except (ValueError, OverflowError) as exc:
            raise ConfigError("preview_timeout_seconds must be a finite positive number (seconds)") from exc
        if not math.isfinite(normalized_timeout) or normalized_timeout <= 0:
            raise ConfigError("preview_timeout_seconds must be a finite positive number (seconds)")
        if not isinstance(self.supported_extensions, tuple):
            raise ConfigError("supported_extensions must be a tuple of suffixes")
        normalized: list[str] = []
        seen: set[str] = set()
        for suffix in self.supported_extensions:
            if not isinstance(suffix, str):
                raise ConfigError("Suffixes in supported_extensions must be strings")
            if any(char in suffix for char in "*?[]/\\:\x00") or any(char.isspace() for char in suffix):
                raise ConfigError("Suffixes cannot contain wildcards, path separators, or whitespace")
            suffix = suffix.lower()
            if suffix and not suffix.startswith("."):
                suffix = "." + suffix
            if suffix == ".":
                raise ConfigError("A suffix cannot be a single dot; use an empty string for files without an extension")
            if suffix not in seen:
                normalized.append(suffix)
                seen.add(suffix)
        object.__setattr__(self, "preview_timeout_seconds", normalized_timeout)
        object.__setattr__(self, "supported_extensions", tuple(normalized))


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting duplicate keys with ConfigError."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"Duplicate configuration key: {key}")
        result[key] = value
    return result


class ConfigManager:
    """Own the current frozen configuration and optional synchronous change events.

    Call load explicitly; construction does not read or write any file. This
    manager is intended to be updated on the application/Tk main thread.
    """

    def __init__(self, path: str | Path | None = None, *, events: EventBus | None = None) -> None:
        """Choose an explicit path or the user's local app-data path; do not create it."""
        self._explicit_path = path is not None
        try:
            self._path = Path(path) if path is not None else (
                Path(os.environ["LOCALAPPDATA"]) / "OffLook" / "config.json"
                if os.environ.get("LOCALAPPDATA")
                else Path.home() / "AppData" / "Local" / "OffLook" / "config.json"
            )
        except (TypeError, ValueError, OSError) as exc:
            raise ConfigError("Invalid configuration file path") from exc
        self._events = events
        self._current = PreviewConfig()

    @property
    def current(self) -> PreviewConfig:
        """Return the current immutable settings, without performing disk I/O."""
        return self._current

    def load(self) -> PreviewConfig:
        """Read at most 64 KiB of UTF-8 JSON, validate it, and return current settings.

        Missing default files yield defaults without writing; missing explicit
        paths and all malformed/unknown values raise ConfigError and keep the
        previous settings. A successful change publishes config.changed.
        """
        try:
            with self._path.open("rb") as stream:
                data = stream.read(65537)
        except FileNotFoundError as exc:
            if self._explicit_path:
                raise ConfigError("The specified configuration file does not exist") from exc
            config = PreviewConfig()
            self.update(config)
            return config
        except (OSError, ValueError) as exc:
            raise ConfigError("Cannot read the configuration file") from exc
        if len(data) > 65536:
            raise ConfigError("The configuration file exceeds the 64 KiB limit")
        try:
            values = json.loads(data.decode("utf-8"), object_pairs_hook=_json_object)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ConfigError("The configuration file must be valid UTF-8 JSON") from exc
        if not isinstance(values, dict):
            raise ConfigError("The top-level configuration JSON value must be an object")
        unknown = set(values) - {field.name for field in fields(PreviewConfig)}
        if unknown:
            raise ConfigError("Unknown configuration keys: " + ", ".join(sorted(unknown)))
        if "supported_extensions" in values:
            suffixes = values["supported_extensions"]
            if not isinstance(suffixes, list):
                raise ConfigError("supported_extensions must be a JSON array")
            values["supported_extensions"] = tuple(suffixes)
        if 'filter_hotkey' not in values:
            # Do not let the new default displace a shortcut saved by an older version.
            try:
                occupied = {parse_hotkey(values.get(name, getattr(PreviewConfig, name))).canonical
                            for name in _LEGACY_SHORTCUT_FIELDS}
            except HotkeyError:
                pass  # PreviewConfig reports the invalid field with its normal validation order.
            else:
                values['filter_hotkey'] = next(combo for combo in _FILTER_SHORTCUTS if combo not in occupied)
        config = PreviewConfig(**values)
        self.update(config)
        return config

    def update(self, config: PreviewConfig, *, persist: bool = False) -> None:
        """Replace settings and publish config.changed with only the config payload.

        With persist=True, atomically replace a UTF-8 JSON file before changing
        memory. Write failure raises ConfigError, retains current settings, and
        removes the temporary file. No implicit startup persistence is performed.
        """
        if not isinstance(config, PreviewConfig):
            raise ConfigError("Configuration must be a PreviewConfig instance")
        if type(persist) is not bool:
            raise ConfigError("persist must be a boolean")
        if persist:
            self._persist(config)
        changed = config != self._current
        self._current = config
        if changed and self._events is not None:
            self._events.publish("config.changed", {"config": config})

    def _persist(self, config: PreviewConfig) -> None:
        """Atomically save config in the destination directory or raise ConfigError."""
        temporary: Path | None = None
        try:
            serialized = json.dumps(asdict(config), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            if len(serialized.encode("utf-8")) > 65536:
                raise ConfigError("The serialized configuration exceeds the 64 KiB limit")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", prefix=".offlook-", suffix=".tmp",
                dir=self._path.parent, delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
            temporary = None
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise ConfigError("Cannot save the configuration atomically; in-memory configuration is unchanged") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    raise ConfigError("Failed to save the configuration and could not clean up the temporary file") from exc
