"""Synchronous, ordered application events without background callback execution."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import sys
from threading import RLock
from types import MappingProxyType


@dataclass(frozen=True)
class Event:
    """An event topic and a shallow read-only copy of its payload mapping."""

    topic: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        """Copy the payload so publishers cannot mutate the delivered mapping."""
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


class EventBus:
    """Dispatch callbacks synchronously in registration order on the publishing thread."""

    def __init__(self) -> None:
        """Create an empty bus with lock-protected subscription snapshots."""
        self._subscriptions: dict[str, list[tuple[object, Callable[[Event], None]]]] = {}
        self._lock = RLock()

    def subscribe(self, topic: str, callback: Callable[[Event], None]) -> Callable[[], None]:
        """Register a callback and return an idempotent unsubscribe function.

        A publication uses a snapshot: cancellation during a callback affects the
        next publication, not callbacks already present in the current snapshot.
        Raise TypeError for a non-string topic or non-callable callback.
        """
        if not isinstance(topic, str):
            raise TypeError("The event name must be a string")
        if not callable(callback):
            raise TypeError("Event subscribers must be callable")
        token = object()
        with self._lock:
            self._subscriptions.setdefault(topic, []).append((token, callback))

        def unsubscribe() -> None:
            """Remove this registration, doing nothing after the first removal."""
            with self._lock:
                subscribers = self._subscriptions.get(topic)
                if subscribers is None:
                    return
                subscribers[:] = [entry for entry in subscribers if entry[0] is not token]
                if not subscribers:
                    del self._subscriptions[topic]

        return unsubscribe

    def publish(self, topic: str, payload: Mapping[str, object] | None = None) -> None:
        """Deliver a copied payload synchronously; isolate subscriber Exceptions.

        Errors are reported to stderr using only the topic and exception type;
        exception messages and payload values are deliberately not logged.
        """
        if not isinstance(topic, str):
            raise TypeError("The event name must be a string")
        event = Event(topic, {} if payload is None else payload)
        with self._lock:
            subscribers = tuple(self._subscriptions.get(topic, ()))
        for _, callback in subscribers:
            try:
                callback(event)
            except Exception as exc:
                safe_topic = ascii(topic)
                print(f"OffLook event {safe_topic}: {type(exc).__name__}", file=sys.stderr)
