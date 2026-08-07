"""Receive-side dedup for persistent message displays.

A sent message typically stays visible for many frames; naive per-frame
parsing would re-ingest it every frame — re-injecting the same relayed
fact, re-counting the same event, re-triggering the same reaction. The
latch admits each (speaker, text) once, and re-admits only when the
speaker's text CHANGES (a fresh send replaced the display) or when the
display lifetime has passed (the same text sent again later is a new
message, indistinguishable from persistence any earlier).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable


@dataclass
class PersistenceLatch:
    lifetime: int                     # ticks a display object persists
    _live: dict[Hashable, tuple[str, int]] = field(default_factory=dict)

    def fresh(self, speaker: Hashable, text: str, tick: int) -> bool:
        """True exactly once per distinct message per display lifetime."""
        prev = self._live.get(speaker)
        if prev is not None:
            prev_text, first_seen = prev
            if prev_text == text and tick - first_seen < self.lifetime:
                return False
        self._live[speaker] = (text, tick)
        return True

    def prune(self, tick: int) -> None:
        """Optional: drop entries older than a lifetime (bounded memory on
        long games with many speakers)."""
        dead = [k for k, (_, t0) in self._live.items()
                if tick - t0 >= self.lifetime]
        for k in dead:
            del self._live[k]
