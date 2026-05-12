"""Dynamic heart-cap discovery.

Aligners pick up hearts at the hub and deliver them to junctions. An
aligner (or scrambler) doesn't need to know the per-gear heart carry
limit up front — it learns by tapping: if a heart-pickup attempt does not
grow the heart count, the current count is the cap for the current gear
signature. Thereafter the agent stops trying to batch more hearts, saving
one wasted tick per trip.

Mirrors CargoCapTracker but keyed on the single `heart` inventory slot
instead of the summed-element cargo total. Kept as a sibling class (not
a generalization) because the semantics are identical yet the signals
differ, and keeping CargoCapTracker untouched guarantees existing unit
tests and miner behavior remain byte-for-byte the same.
"""

from __future__ import annotations

from typing import Callable


GearSig = tuple[str, ...]


class HeartCapTracker:
    """Tracks observed heart carry caps per gear signature."""

    def __init__(
        self,
        on_discovery: Callable[[GearSig, int], None] | None = None,
    ) -> None:
        self._cap: dict[GearSig, int] = {}
        self._prev_hearts: int | None = None
        self._prev_sig: GearSig | None = None
        self._on_discovery = on_discovery

    def observe(
        self,
        *,
        gear_sig: GearSig,
        hearts: int,
        tried_pickup_last_tick: bool,
    ) -> None:
        if (
            tried_pickup_last_tick
            and self._prev_sig == gear_sig
            and self._prev_hearts is not None
            and hearts == self._prev_hearts
            and hearts > 0
        ):
            existing = self._cap.get(gear_sig)
            # Only upgrade to a larger observed cap; ignore false plateaus
            # smaller than the already-known cap (e.g., adversary disrupting
            # a pickup mid-trip after delivery).
            if existing is None or hearts > existing:
                self._cap[gear_sig] = hearts
                if self._on_discovery is not None:
                    self._on_discovery(gear_sig, hearts)
        self._prev_hearts = hearts
        self._prev_sig = gear_sig

    def known_cap(self, gear_sig: GearSig) -> int | None:
        return self._cap.get(gear_sig)
