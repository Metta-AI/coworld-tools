"""targets.py — Sticky target with progress-based invalidation.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_targets.py``).

Without sticky targets, a pursuer (miner heading to an extractor,
aligner heading to a junction) can oscillate between two equidistant
options every tick — the next tick's re-rank flips the selection back
and forth and the agent makes no forward progress. The sticky-target
pattern fixes this by holding a target across ticks so the pursuer
commits to one path until either it arrives or it stops making
progress.

The "stops making progress" check is the half that matters: a sticky
target without progress invalidation traps the agent forever when the
target is unreachable (blocked by a teammate, walled off, etc.).
``update_target_progress`` tracks the closest distance achieved so far
and the step at which we last got closer; if no improvement happens
within ``cfg.progress_window`` ticks, the function returns False and
the caller drops the sticky.

This module is purely geometric — it knows nothing about POI kinds,
tag membership, or whether the target is "still in memory." Those are
mission-specific concerns; the caller composes them with this
primitive. ``mapping.is_stale`` covers age-based invalidation if
the caller wants to add it.

Source: ``dedicated_common.py:873-915`` (``sticky_target_still_valid``,
``set_sticky``); reset hooks at ``dedicated_runtime.py:788-794``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

Coordinate = tuple[int, int]


@dataclass
class TargetConfig:
    progress_window: int = 12   # ticks without forward progress => sticky drops


@dataclass
class TargetState:
    target: Coordinate | None = None
    target_kind: str | None = None      # caller-defined label ("extractor:carbon", "junction", ...)
    best_distance: int | None = None
    last_progress_step: int = 0


def set_target(
    state: TargetState,
    target: Coordinate,
    position: Coordinate,
    step: int,
    distance: Callable[[Coordinate, Coordinate], int],
    kind: str | None = None,
) -> None:
    """Adopt a new sticky target. Initializes the progress trace from
    the current position so ``update_target_progress`` measures motion
    relative to where we were when the commitment was made.
    """
    state.target = target
    state.target_kind = kind
    state.best_distance = distance(position, target)
    state.last_progress_step = step


def update_target_progress(
    state: TargetState,
    position: Coordinate,
    step: int,
    distance: Callable[[Coordinate, Coordinate], int],
    cfg: TargetConfig,
) -> bool:
    """Returns True if the sticky target is still viable, False
    otherwise.

    Side-effects ``state.best_distance`` and ``state.last_progress_step``:
    a strictly-closer distance counts as forward progress; equal-or-
    farther leaves the trace unchanged. When the elapsed window since
    the last forward progress reaches ``cfg.progress_window``, returns
    False and the caller should call ``clear_target``.

    No-op (returns False) when no target is set — useful so callers can
    blanket-call this each tick.
    """
    if state.target is None or state.best_distance is None:
        return False

    d = distance(position, state.target)
    if d < state.best_distance:
        state.best_distance = d
        state.last_progress_step = step

    return (step - state.last_progress_step) < cfg.progress_window


def clear_target(state: TargetState) -> None:
    """Drop the sticky target. Use on arrival, role change, or any
    other explicit abandonment so the next ``set_target`` starts
    cleanly."""
    state.target = None
    state.target_kind = None
    state.best_distance = None
    state.last_progress_step = 0


def check_arrival(
    state: TargetState,
    position: Coordinate,
    distance: Callable[[Coordinate, Coordinate], int],
    threshold: int = 0,
    objective_satisfied: Callable[[], bool] | None = None,
) -> bool:
    """True iff ``position`` is within ``threshold`` cells of the
    sticky target AND (``objective_satisfied`` is None or returns
    True).

    Many arrival conditions share the shape "geometric arrival AND
    objective satisfied," differing only in the metric and the
    predicate. ``nav_grid.core.arrived`` handles the geometry-only case;
    this helper adds the semantic layer so the picker does not loiter
    at a bump target whose objective is still incomplete.

    The metric is caller-supplied (no implicit Manhattan). For bump
    targets pass ``manhattan`` — the env is 4-connected so a bump
    fires only from orthogonal neighbors (Manhattan=1). The
    historical ``chebyshev`` default was a long-standing bug that
    accepted diagonal cells (Cheb=1 / Manhattan=2) as "arrived" even
    though they cannot bump on the same tick. Use ``euclidean_sq``
    for radial AOE / lane checks.

    Returns ``False`` when no sticky target is set so callers can
    blanket-call this each tick (mirrors ``update_target_progress``).
    """
    if state.target is None:
        return False
    if distance(position, state.target) > threshold:
        return False
    if objective_satisfied is not None and not objective_satisfied():
        return False
    return True
