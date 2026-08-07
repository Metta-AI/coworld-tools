"""Decaying spatial evidence accumulator ("where has activity been?").

Feed point events (heard impacts, sightings, message origins — anything
positioned); read back decayed heat: totals, mass near a point, or the
fraction of ALL current heat near a point. The classic consumer question
is "is the action near X or elsewhere?" — e.g. an objective is provably
under-defended when the map is LOUD overall while almost none of the
heat sits near it. That is a positive-evidence test; contrast it with
absence-of-observation tests, which fog makes systematically unsafe.

Implementation notes:
- sparse dict of cells (stdlib only; unbounded worlds welcome);
- exponential half-life decay applied lazily on read/write, so idle maps
  cost nothing;
- one shared clock: feed monotone ticks. Same-tick reads after writes are
  exact; the structure never rewinds.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DecayingHeatmap:
    cell: int = 128
    halflife: int = 96
    _cells: dict[tuple[int, int], float] = field(default_factory=dict)
    _total: float = 0.0
    _tick: int = 0

    def _decay_to(self, tick: int) -> None:
        dt = tick - self._tick
        if dt <= 0:
            return
        f = 0.5 ** (dt / self.halflife)
        if f < 1e-9:
            self._cells.clear()
            self._total = 0.0
        else:
            dead = []
            for k in self._cells:
                v = self._cells[k] * f
                if v < 1e-9:
                    dead.append(k)
                else:
                    self._cells[k] = v
            for k in dead:
                del self._cells[k]
            self._total *= f
        self._tick = tick

    def _key(self, xy) -> tuple[int, int]:
        return (int(xy[0]) // self.cell, int(xy[1]) // self.cell)

    def add(self, xy, tick: int, w: float = 1.0) -> None:
        self._decay_to(tick)
        k = self._key(xy)
        self._cells[k] = self._cells.get(k, 0.0) + w
        self._total += w

    def total(self, tick: int) -> float:
        self._decay_to(tick)
        return self._total

    def near(self, xy, radius_px: float, tick: int) -> float:
        """Heat mass within radius_px of xy (cell-granular)."""
        self._decay_to(tick)
        cx, cy = self._key(xy)
        r = max(0, int(radius_px) // self.cell)
        acc = 0.0
        for (kx, ky), v in self._cells.items():
            if abs(kx - cx) <= r and abs(ky - cy) <= r:
                acc += v
        return acc

    def frac_near(self, xy, radius_px: float, tick: int) -> float:
        """Share of ALL current heat within radius_px of xy. Returns 0 on a
        quiet map — check total() first; low-frac-near only means
        "elsewhere" when there is a somewhere."""
        t = self.total(tick)
        if t <= 1e-9:
            return 0.0
        return self.near(xy, radius_px, tick) / t
