"""Thread-safe outer→inner mode buffer for consume-on-read directives."""

from __future__ import annotations

import threading

from orpheus.mode import ModeDirective


class ModeBuffer:
    """Thread-safe size-1 buffer holding (ModeDirective, dict | None).

    Push overwrites any unconsumed entry. Read consumes (empties).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entry: tuple[ModeDirective, dict | None] | None = None

    def push(self, directive: ModeDirective, inferences: dict | None = None) -> None:
        """Store a mode directive, overwriting any unconsumed entry."""
        with self._lock:
            self._entry = (directive, inferences)

    def consume(self) -> tuple[ModeDirective, dict | None] | None:
        """Return and clear the current entry, or None when empty."""
        with self._lock:
            entry = self._entry
            self._entry = None
            return entry

    def has_entry(self) -> bool:
        """Return True when an entry is waiting to be consumed."""
        with self._lock:
            return self._entry is not None


__all__ = ["ModeBuffer"]
