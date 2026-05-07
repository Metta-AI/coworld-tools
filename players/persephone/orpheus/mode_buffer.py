"""Outer→inner mode buffer (Stage 6 single-threaded version)."""

from __future__ import annotations

from orpheus.mode import ModeDirective


class ModeBuffer:
    """Size-1 consume-on-read buffer holding (ModeDirective, dict | None).

    Push overwrites any unconsumed entry. Read consumes (empties).
    Stage 7 will replace this with a thread-safe variant.
    """

    def __init__(self) -> None:
        self._entry: tuple[ModeDirective, dict | None] | None = None

    def push(self, directive: ModeDirective, inferences: dict | None = None) -> None:
        """Store a mode directive, overwriting any unconsumed entry."""
        self._entry = (directive, inferences)

    def consume(self) -> tuple[ModeDirective, dict | None] | None:
        """Return and clear the current entry, or None when empty."""
        entry = self._entry
        self._entry = None
        return entry

    def has_entry(self) -> bool:
        """Return True when an entry is waiting to be consumed."""
        return self._entry is not None


__all__ = ["ModeBuffer"]
