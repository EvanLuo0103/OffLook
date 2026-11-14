"""Constructor-injected application services without mutable global singletons."""

from dataclasses import dataclass
from pathlib import Path

from .config import ConfigManager
from .events import EventBus
from .extensions import ActionRegistry


@dataclass(frozen=True)
class AppContext:
    """A shared configuration manager, event bus, and initially empty action registry."""

    config: ConfigManager
    events: EventBus
    actions: ActionRegistry


def create_context(config_path: str | Path | None = None) -> AppContext:
    """Construct shared services and load settings; propagate ConfigError on failure.

    Loading never starts Tk, COM, threads, hotkeys, plugin discovery, or previews.
    The supplied path follows ConfigManager's explicit/default missing-file rules.
    """
    events = EventBus()
    config = ConfigManager(config_path, events=events)
    actions = ActionRegistry()
    context = AppContext(config=config, events=events, actions=actions)
    config.load()
    return context
