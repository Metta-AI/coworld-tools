"""emergency.py — Emergency-resource role-pivot helper.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_emergency.py``).

When the team's hub stock of any tracked resource cratters, every
non-specialist that can contribute should pivot to filling the
bottleneck. If the dedicated specialist (e.g. miner) is already
working on it, a moderate threshold is enough — we want backup, not
panic. If the specialist is dead or absent, the pipeline broke; raise
the threshold so non-specialists pivot earlier and harder.

Tom (``policy_tom.py:644-687``) and the dedicated stack
(``dedicated_common.py:767-844``) independently shipped near-identical
versions of this. The dual-threshold variant is the real lesson —
single-threshold designs either miss the pre-collapse window or panic
during normal operation.

The abstraction is *not* mining-specific. It applies to any
specialist/resource pair: a builder pipeline whose component-supplier
specialist is down; a foraging team whose hauler died and packs are
piling up at sites; etc. The caller supplies ``stocks`` and
``specialist_alive``; this module answers *which resource* to pivot
toward, and the caller handles the mission-specific action.

Defaults: ``enabled=False`` (matches the bundle-1 ``pacing_window=0``
precedent — opinionated team behavior is opt-in).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class EmergencyConfig:
    enabled: bool = False
    threshold: int = 20
    no_specialist_threshold: int = 10


def pick_threshold(specialist_alive: bool, cfg: EmergencyConfig) -> int:
    """Return the threshold to use given specialist liveness.

    Exposed so callers can use it for their own logging / branching
    (mirrors ``dedicated_common._emergency_threshold_with_miner`` /
    ``_without_miner``). ``cfg.enabled=False`` returns 0 (which
    short-circuits any deficiency check by ``worst_deficient_resource``).
    """
    if not cfg.enabled:
        return 0
    return cfg.threshold if specialist_alive else cfg.no_specialist_threshold


def worst_deficient_resource(
    stocks: dict[str, int],
    resources: Sequence[str],
    threshold: int,
) -> str | None:
    """Return the resource in ``resources`` with the lowest stock if
    that minimum is at or below ``threshold``; else None.

    Ties broken by iteration order over ``resources`` — caller
    controls priority by ordering the sequence (e.g. cheapest crafting
    component first, or most-bottlenecked first).

    A ``threshold`` of 0 disables the check (no resource ever
    "qualifies" with stock <= 0 unless it's literally empty, and
    callers that want to disable should pass 0 explicitly).
    """
    if threshold <= 0:
        return None
    worst_name: str | None = None
    worst_stock: int | None = None
    for name in resources:
        stock = stocks.get(name, 0)
        if stock > threshold:
            continue
        if worst_stock is None or stock < worst_stock:
            worst_stock = stock
            worst_name = name
    return worst_name


def should_pivot(
    stocks: dict[str, int],
    resources: Sequence[str],
    specialist_alive: bool,
    cfg: EmergencyConfig,
) -> str | None:
    """Composite: returns the deficient resource to pivot toward, or
    None to indicate no pivot is needed.

    Short-circuits to None when ``cfg.enabled=False``. Otherwise
    selects the appropriate threshold via ``pick_threshold`` and
    delegates to ``worst_deficient_resource``.
    """
    if not cfg.enabled:
        return None
    threshold = pick_threshold(specialist_alive, cfg)
    return worst_deficient_resource(stocks, resources, threshold)
