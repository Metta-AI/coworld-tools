"""tabu.py — TTL'd target blacklist with failure-strike promotion.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_tabu.py``).

Several policy state patterns share the same primitive:

* a TTL blacklist keyed by a coordinate or resource identifier
* a strike counter that promotes repeated failures into that blacklist
* a success path that clears both the strike counter and any blacklist
  entry for the same key

This module provides a reusable implementation of that pattern.

This module provides:

* ``is_tabu`` / ``add_tabu`` — the simple TTL-blacklist face.
* ``record_failure`` — bump a strike counter; auto-promote to the
  blacklist when the threshold trips.
* ``record_success`` — clear both strike counter and blacklist for a
  key (e.g., when an extractor finally yields).
* ``gc`` — drop expired blacklist entries to keep the dict small over
  long episodes.

The key type is ``Hashable``: callers pass plain ``Coordinate`` or
``(Coordinate, str)`` or ``(Coordinate, role)`` without needing a
second mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable


@dataclass
class TabuConfig:
    default_ttl: int = 300
    """TTL applied by ``add_tabu`` when no per-call override is given,
    and the ceiling for ``record_failure``-driven promotions when
    ``strike_ttl`` isn't set explicitly."""

    strike_threshold: int = 2
    """Number of failures the same key must accumulate before
    ``record_failure`` promotes it into the blacklist."""

    strike_window: int = 0
    """Inter-failure deadline for "consecutive" semantics. A failure
    is *consecutive* if ``step - last_failure_step <= strike_window``;
    otherwise the strike count resets to 1.

    Set to ``0`` to disable the consecutive check (any threshold
    failures over the lifetime of the state promote the key) — useful
    when the caller already enforces consecutivity by other means
    (e.g., the miner is sticky on the target between strike calls).

    Set to ``1`` to require strict tick-by-tick consecutivity."""

    strike_ttl: int = 200
    """TTL of the blacklist entry created by a strike-promotion."""


@dataclass
class TabuState:
    blacklist: dict[Hashable, int] = field(default_factory=dict)
    """key → expiry_step. The key is tabu while ``step < expiry_step``."""

    strikes: dict[Hashable, tuple[int, int]] = field(default_factory=dict)
    """key → (count, last_failure_step). Cleared on promotion or
    ``record_success``."""


def is_tabu(state: TabuState, key: Hashable, step: int) -> bool:
    """True iff ``key`` is currently blacklisted (its expiry step is
    strictly in the future).

    Pickers should filter candidates with ``not is_tabu(...)``. Cheap
    enough to call per-candidate per-tick.
    """
    exp = state.blacklist.get(key)
    return exp is not None and step < exp


def add_tabu(
    state: TabuState,
    key: Hashable,
    step: int,
    ttl: int | None = None,
    cfg: TabuConfig | None = None,
) -> None:
    """Blacklist ``key`` for ``ttl`` ticks (defaults to
    ``cfg.default_ttl``, then to a built-in fallback if neither is
    given).

    Idempotent in the sense that a later call can extend the TTL —
    the new ``expiry_step = step + ttl`` overwrites the previous one
    even if it was further in the future. Callers wanting "extend if
    longer, no shorten" should compare before calling.
    """
    if ttl is None:
        ttl = cfg.default_ttl if cfg is not None else 300
    state.blacklist[key] = step + ttl


def record_failure(
    state: TabuState,
    key: Hashable,
    step: int,
    cfg: TabuConfig,
) -> bool:
    """Increment the strike counter for ``key`` and, if the threshold
    is reached, promote it into the blacklist.

    Returns ``True`` iff this call promoted the key (i.e., the caller
    should now also drop its sticky target / pick a new one). Returns
    ``False`` for "still strikes-only, not yet blacklisted."

    Consecutive-failure semantics are governed by ``cfg.strike_window``:

    * ``strike_window == 0`` — any failures across the lifetime of the
      state count. The counter only resets on ``record_success``.
    * ``strike_window >= 1`` — a failure recorded more than
      ``strike_window`` ticks after the previous one resets the count
      to 1 (this call counts as a fresh first strike).
    """
    prev = state.strikes.get(key)
    if prev is None:
        count = 1
    else:
        prev_count, prev_step = prev
        if cfg.strike_window > 0 and (step - prev_step) > cfg.strike_window:
            count = 1
        else:
            count = prev_count + 1

    if count >= cfg.strike_threshold:
        # Promote to blacklist; clear strike counter so a re-encounter
        # after expiry starts fresh.
        state.blacklist[key] = step + cfg.strike_ttl
        state.strikes.pop(key, None)
        return True

    state.strikes[key] = (count, step)
    return False


def record_success(state: TabuState, key: Hashable) -> None:
    """Clear both the strike counter and the blacklist entry for
    ``key``. Call when the failing condition flips — e.g., an
    extractor that previously yielded zero now yields cargo.
    """
    state.strikes.pop(key, None)
    state.blacklist.pop(key, None)


def gc(state: TabuState, step: int) -> None:
    """Drop expired blacklist entries. Optional housekeeping for long
    episodes — ``is_tabu`` already returns False for expired entries,
    so correctness doesn't depend on calling this.

    Strikes are not GC'd here because their semantics are caller-
    controlled (``cfg.strike_window`` decides when stale strikes
    become irrelevant; old entries with ``strike_window > 0`` will be
    overwritten on the next failure for that key).
    """
    expired = [k for k, exp in state.blacklist.items() if exp <= step]
    for k in expired:
        state.blacklist.pop(k, None)
