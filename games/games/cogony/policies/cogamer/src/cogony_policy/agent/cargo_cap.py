"""Dynamic cargo-cap discovery.

A miner doesn't have to know its inventory limit up front. It learns by
tapping: if a mine attempt doesn't grow cargo, the current cargo is the
cap for the current gear signature. Thereafter the agent stops mining
once cargo hits the known cap, saving one wasted tick per trip.

Caps are per gear signature (tuple of gear items held) so different gear
combinations have independent limits.
"""

from __future__ import annotations

from typing import Callable


GearSig = tuple[str, ...]


class CargoCapTracker:
    """Tracks observed cargo caps per gear signature."""

    def __init__(
        self,
        on_discovery: Callable[[GearSig, int], None] | None = None,
    ) -> None:
        self._cap: dict[GearSig, int] = {}
        self._prev_cargo: int | None = None
        self._prev_sig: GearSig | None = None
        self._on_discovery = on_discovery

    def observe(self, *, gear_sig: GearSig, cargo: int, mined_last_tick: bool) -> None:
        if (
            mined_last_tick
            and self._prev_sig == gear_sig
            and self._prev_cargo is not None
            and cargo == self._prev_cargo
            and cargo > 0
        ):
            existing = self._cap.get(gear_sig)
            # Only upgrade to a larger observed cap; ignore false plateaus
            # that are smaller than the already-known cap (e.g., adversary
            # blocking a mine attempt mid-trip after deposit).
            if existing is None or cargo > existing:
                self._cap[gear_sig] = cargo
                if self._on_discovery is not None:
                    self._on_discovery(gear_sig, cargo)
        self._prev_cargo = cargo
        self._prev_sig = gear_sig

    def known_cap(self, gear_sig: GearSig) -> int | None:
        return self._cap.get(gear_sig)
