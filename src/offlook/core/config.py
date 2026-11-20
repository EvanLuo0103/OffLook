"""Validated immutable preview settings and secret-free JSON persistence."""

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid
from typing import Literal

from ..platforms import windows_credentials
from .errors import ConfigError, HotkeyError
from .events import EventBus
from .files import DEFAULT_SUPPORTED_EXTENSIONS
from .hotkeys import parse_hotkey

_LEGACY_SHORTCUT_FIELDS = ('hotkey', 'search_hotkey', 'diff_hotkey', 'convert_hotkey')
_FILTER_SHORTCUTS = ('Ctrl+Alt+F', 'Ctrl+Alt+Shift+F', 'Ctrl+Alt+G', 'Ctrl+Alt+Shift+G',
                     'Ctrl+Alt+J', 'Ctrl+Alt+Shift+J')
_AI_SHORTCUTS = ('Ctrl+Alt+Shift+A', 'Ctrl+Alt+A', 'Ctrl+Alt+Shift+I', 'Ctrl+Alt+I',
                 'Ctrl+Alt+Shift+K', 'Ctrl+Alt+K')
_SHORTCUT_FIELDS = (*_LEGACY_SHORTCUT_FIELDS, 'filter_hotkey', 'ai_hotkey')
_CREDENTIAL_ID = re.compile(r"[0-9a-f]{32}")
_MAX_CONFIG_BYTES = 65536


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
    ai_model: str = "deepseek-chat"
    language: str = "en"
    filter_hotkey: str = _FILTER_SHORTCUTS[0]
    ai_hotkey: str = _AI_SHORTCUTS[0]

    def __post_init__(self) -> None:
        """Validate exact setting types and normalize suffixes without accepting glob patterns."""
        if type(self.max_file_size_bytes) is not int or self.max_file_size_bytes <= 0:
            raise ConfigError("max_file_size_bytes must be a positive integer (bytes)")
        if type(self.hotkey_enabled) is not bool or type(self.always_on_top) is not bool or type(self.ai_enabled) is not bool:
            raise ConfigError("hotkey_enabled, always_on_top, and ai_enabled must be booleans")
        shortcut_names = _SHORTCUT_FIELDS
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


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ConfigManager:
    """Own settings and keep API keys outside the JSON configuration file."""

    def __init__(self, path: str | Path | None = None, *, events: EventBus | None = None) -> None:
        """Choose and resolve an explicit/default path without reading or creating it."""
        self._explicit_path = path is not None
        try:
            raw_path = Path(path) if path is not None else (
                Path(os.environ["LOCALAPPDATA"]) / "OffLook" / "config.json"
                if os.environ.get("LOCALAPPDATA")
                else Path.home() / "AppData" / "Local" / "OffLook" / "config.json"
            )
            self._path = raw_path.expanduser().resolve(strict=False)
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            raise ConfigError("Invalid configuration file path") from exc
        self._events = events
        self._current = PreviewConfig()
        self._loaded = False
        self._loaded_bytes: bytes | None = None
        self._credential_id: str | None = None
        self._credential_endpoint: str | None = None
        self._legacy_ai_key: str | None = None
        self._credential_warning: str | None = None

    @property
    def path(self) -> Path:
        """The absolute, fixed path used for every configuration I/O operation."""
        return self._path

    @property
    def current(self) -> PreviewConfig:
        """Return current immutable settings without performing disk I/O."""
        return self._current

    @property
    def has_legacy_ai_key(self) -> bool:
        """Whether a non-empty plaintext key still needs to be migrated."""
        return self._legacy_ai_key is not None

    @property
    def credential_warning(self) -> str | None:
        """The latest commit's warning about an unreferenced old credential."""
        return self._credential_warning

    @property
    def ai_credential_target(self) -> str | None:
        """Derive a target for the current endpoint without accessing the vault."""
        if self._credential_id is None:
            return None
        return self._target(self._current.ai_base_url, self._credential_id)

    def _target(self, endpoint: str, credential_id: str) -> str:
        try:
            profile = _digest(os.path.normcase(str(self._path)))
            endpoint_digest = _digest(endpoint)
        except UnicodeError:
            raise ConfigError("Cannot bind the credential to this configuration path and endpoint") from None
        return f"OffLook:ai-api-key:v1:{profile}:{endpoint_digest}:{credential_id}"

    def _publish_if_changed(self, previous: PreviewConfig) -> None:
        if self._current != previous and self._events is not None:
            self._events.publish("config.changed", {"config": self._current})

    def load(self) -> PreviewConfig:
        """Load and validate the file without writing it or accessing the vault."""
        data = self._disk_bytes()
        if data is None:
            if self._explicit_path:
                raise ConfigError("The specified configuration file does not exist")
            values = {}
        else:
            if len(data) > _MAX_CONFIG_BYTES:
                raise ConfigError("The configuration file exceeds the 64 KiB limit")
            try:
                values = json.loads(data.decode("utf-8"), object_pairs_hook=_json_object)
            except (UnicodeError, ValueError, RecursionError):
                raise ConfigError("The configuration file must be valid UTF-8 JSON") from None
            if not isinstance(values, dict):
                raise ConfigError("The top-level configuration JSON value must be an object")

        legacy: str | None = None
        has_legacy = "ai_api_key" in values
        if has_legacy:
            legacy_value = values.pop("ai_api_key")
            if not isinstance(legacy_value, str):
                raise ConfigError("ai_api_key must be a string")
            if legacy_value:
                legacy = legacy_value
        credential_id: str | None = None
        if "ai_credential_id" in values:
            if has_legacy:
                raise ConfigError("ai_api_key and ai_credential_id cannot both be configured")
            credential_id = values.pop("ai_credential_id")
            if not isinstance(credential_id, str) or not _CREDENTIAL_ID.fullmatch(credential_id):
                raise ConfigError("ai_credential_id must be 32 lowercase hexadecimal characters")

        unknown = set(values) - {field.name for field in fields(PreviewConfig)}
        if unknown:
            raise ConfigError("Unknown configuration keys: " + ", ".join(sorted(unknown)))
        if "supported_extensions" in values:
            suffixes = values["supported_extensions"]
            if not isinstance(suffixes, list):
                raise ConfigError("supported_extensions must be a JSON array")
            values["supported_extensions"] = tuple(suffixes)
        # Fill newer shortcuts without displacing any configured combination.
        for field, choices in (("filter_hotkey", _FILTER_SHORTCUTS), ("ai_hotkey", _AI_SHORTCUTS)):
            if field in values:
                continue
            try:
                occupied = {parse_hotkey(values.get(name, getattr(PreviewConfig, name))).canonical
                            for name in _SHORTCUT_FIELDS if name != field
                            and (name in values or name in _LEGACY_SHORTCUT_FIELDS)}
            except HotkeyError:
                break  # PreviewConfig reports the invalid field in its normal validation order.
            values[field] = next(combo for combo in choices if combo not in occupied)
        config = PreviewConfig(**values)
        previous = self._current
        self._loaded = True
        self._loaded_bytes = data
        self._credential_id = credential_id
        self._credential_endpoint = config.ai_base_url if credential_id or legacy is not None else None
        self._legacy_ai_key = legacy
        self._credential_warning = None
        self._current = config
        self._publish_if_changed(previous)
        return config

    def update(
        self,
        config: PreviewConfig,
        *,
        persist: bool = False,
        ai_key_action: Literal["keep", "replace", "clear"] = "keep",
        ai_key: str | None = None,
    ) -> None:
        """Replace settings, optionally committing a staged credential transaction."""
        if not isinstance(config, PreviewConfig):
            raise ConfigError("Configuration must be a PreviewConfig instance")
        if type(persist) is not bool:
            raise ConfigError("persist must be a boolean")
        if type(ai_key_action) is not str or ai_key_action not in ("keep", "replace", "clear"):
            raise ConfigError("ai_key_action must be 'keep', 'replace', or 'clear'")
        if not persist and ai_key_action != "keep":
            raise ConfigError("Credential changes require persist=True")
        if ai_key_action == "replace":
            windows_credentials._encode_key(ai_key)
        elif ai_key is not None:
            raise ConfigError("ai_key is only accepted with ai_key_action='replace'")
        previous = self._current
        if persist:
            self._persist(config, ai_key_action=ai_key_action, ai_key=ai_key)
        else:
            self._current = config
        self._publish_if_changed(previous)

    def migrate_legacy_ai_key(self) -> None:
        """Move a non-empty legacy JSON key into Credential Manager exactly once."""
        if self._legacy_ai_key is not None:
            self.update(self._current, persist=True, ai_key_action="keep")

    def _disk_bytes(self) -> bytes | None:
        try:
            with self._path.open("rb") as stream:
                return stream.read(_MAX_CONFIG_BYTES + 1)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise ConfigError("Cannot read the configuration file") from exc

    def _check_revision(self) -> None:
        disk = self._disk_bytes()
        if not self._loaded and disk is not None:
            raise ConfigError("Load the configuration before saving it")
        if disk != self._loaded_bytes:
            raise ConfigError("Configuration changed on disk; restart OffLook and try again.")

    def _serialize(self, config: PreviewConfig, credential_id: str | None) -> bytes:
        try:
            values = asdict(config)
            if credential_id is not None:
                values["ai_credential_id"] = credential_id
            serialized = (json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise ConfigError("Cannot serialize the configuration") from None
        if len(serialized) > _MAX_CONFIG_BYTES:
            raise ConfigError("The serialized configuration exceeds the 64 KiB limit")
        return serialized

    def _commit_json(self, serialized: bytes, *, target: str | None, key: str | None) -> None:
        """Prepare and flush JSON, stage a credential if needed, then commit."""
        temporary: Path | None = None
        attempted_target: str | None = None
        failure = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".offlook-", suffix=".tmp", dir=self._path.parent, delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            if target is not None and key is not None:
                attempted_target = target  # CredWrite may raise after creating the entry.
                try:
                    windows_credentials.write_api_key(target, key)
                    verified = windows_credentials.read_api_key(target) == key
                except Exception:
                    failure = "Could not save or verify the Windows credential"
                    raise
                if not verified:
                    failure = "Windows credential verification failed"
                    raise ConfigError(failure)
            os.replace(temporary, self._path)
        except Exception:
            if failure is None:
                failure = "Cannot save the configuration atomically; in-memory configuration is unchanged"
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    failure += "; the temporary configuration could not be removed"
            if attempted_target is not None:
                try:
                    windows_credentials.delete_api_key(attempted_target)
                except Exception:
                    failure += f"; unreferenced credential could not be removed: {attempted_target}"
            raise ConfigError(failure) from None

    def _persist(self, config: PreviewConfig, *, ai_key_action: str, ai_key: str | None) -> None:
        if os.name == "nt":
            self._persist_windows(config, ai_key_action=ai_key_action, ai_key=ai_key)
        else:
            self._persist_transaction(config, ai_key_action=ai_key_action, ai_key=ai_key)

    def _persist_windows(self, config: PreviewConfig, *, ai_key_action: str, ai_key: str | None) -> None:
        try:
            import msvcrt
        except ImportError:
            raise ConfigError("Windows configuration locking is unavailable") from None
        lock_stream = None
        locked = False
        lock_path = self._path.with_name(self._path.name + ".offlook.lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_stream = lock_path.open("a+b")
            if lock_stream.seek(0, os.SEEK_END) == 0:
                lock_stream.write(b"\0")
                lock_stream.flush()
            lock_stream.seek(0)
            try:
                msvcrt.locking(lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as exc:
                raise ConfigError("Configuration is currently in use") from exc
            self._persist_transaction(config, ai_key_action=ai_key_action, ai_key=ai_key)
        except OSError as exc:
            raise ConfigError("Could not open or initialize the configuration lock") from exc
        finally:
            if lock_stream is not None:
                if locked:
                    try:
                        lock_stream.seek(0)
                        msvcrt.locking(lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                try:
                    lock_stream.close()
                except OSError:
                    pass

    def _persist_transaction(self, config: PreviewConfig, *, ai_key_action: str, ai_key: str | None) -> None:
        self._check_revision()
        old_id = self._credential_id
        legacy = self._legacy_ai_key
        old_endpoint = self._credential_endpoint
        if ai_key_action == "keep" and (old_id is not None or legacy is not None):
            if old_endpoint != config.ai_base_url:
                raise ConfigError("Saved API key belongs to a different endpoint; save a new key or remove the old one.")

        key = None
        if ai_key_action == "replace":
            key = ai_key
        elif ai_key_action == "keep":
            key = legacy
        cleanup_old = old_id is not None and ai_key_action != "keep"
        if (key is not None or cleanup_old) and os.name != "nt":
            raise ConfigError("Credential storage is available only on Windows")
        if key is not None:
            if ai_key_action == "keep":
                windows_credentials._encode_key(key)
            new_id = uuid.uuid4().hex
            if new_id == old_id:
                raise ConfigError("Could not allocate a fresh credential ID")
        else:
            new_id = old_id if ai_key_action == "keep" else None

        serialized = self._serialize(config, new_id)
        new_endpoint = config.ai_base_url if new_id is not None else None
        new_target = None
        if key is not None and new_endpoint is not None and new_id is not None:
            new_target = self._target(new_endpoint, new_id)
        old_target = None
        if cleanup_old and old_endpoint is not None and old_id is not None:
            old_target = self._target(old_endpoint, old_id)
        self._commit_json(serialized, target=new_target, key=key)

        self._current = config
        self._loaded = True
        self._loaded_bytes = serialized
        self._credential_id = new_id
        self._credential_endpoint = new_endpoint
        self._legacy_ai_key = None
        self._credential_warning = None
        if old_target is not None:
            try:
                windows_credentials.delete_api_key(old_target)
            except Exception:
                self._credential_warning = f"Settings saved; old credential could not be removed: {old_target}"
