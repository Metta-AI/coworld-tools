"""Anti-phantom rules for teammate-relayed position fixes.

When teammates broadcast "enemy at X" fixes over a shared channel, naive
ingestion poisons the world model in three measured ways:

1. ECHO LOOPS: an agent re-broadcasts a fix it heard, a third agent
   re-ingests it as new evidence, and a ghost contact stays permanently
   fresh while every real observer moved on.
2. EYES-VS-EARS INVERSION: a relayed fix treated as fresh outranks the
   receiver's own (slightly older) direct sighting, and the better
   evidence loses.
3. DUPLICATE SPLITTING: a relay landing near an existing contact spawns a
   second contact, doubling the apparent enemy count.

The counter-rules, each mapping to one failure:

- PRE-AGE every relayed fix by `age` ticks, so direct observation always
  outranks hearsay of the same vintage.
- NEVER let a relay refresh an existing fix (relays create, sightings
  update). A refreshed synthetic is exactly the echo-loop ghost.
- DUP-GATE: a relay within `dup_radius` of ANY existing same-identity
  contact is a duplicate — drop it entirely.
- CONFIRM-ON-SIGHT: when a direct observation associates with a synthetic
  contact, it stops being synthetic; relay bookkeeping (fake age) must not
  pollute derived state like velocity.

This module is deliberately store-agnostic: `RelayPolicy` answers
"should this fix be injected, and at what effective age?" against the
positions the caller already tracks. Consumers keep their own contact
structures and mark synthetics however they like (the one hard rule:
synthetic contacts steer navigation and awareness but are never direct
fire targets — shooting at a plus-or-minus-jitter neighborhood wastes
the shot cycle).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RelayPolicy:
    age: int = 6            # pre-age: own eyes outrank hearsay
    dup_radius: float = 70  # a relay this close to a known contact is a dup

    def admit(self, fix_xy: Sequence[float],
              existing_xy: Iterable[Sequence[float]]) -> bool:
        """True when the relayed fix should create a NEW contact.

        `existing_xy`: positions of already-tracked contacts of the same
        identity class (same team/color/kind as the relayed fix claims).
        A relay never refreshes — an admit=False result means DROP, not
        update.
        """
        fx, fy = float(fix_xy[0]), float(fix_xy[1])
        r = self.dup_radius
        for ex in existing_xy:
            if abs(float(ex[0]) - fx) <= r and abs(float(ex[1]) - fy) <= r:
                return False
        return True

    def effective_last_seen(self, tick: int) -> int:
        """The last-seen stamp an admitted fix should carry."""
        return tick - self.age
