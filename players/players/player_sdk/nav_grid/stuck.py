"""stuck.py — Stuck detection for navigation pursuits.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_stuck.py``).

Three flavors of "no progress for too long":

* **Position-stuck**: agent's position hasn't changed for N ticks
  (mirrors ``policy_base.py:102`` ``STUCK_THRESHOLD = 8``).
* **Axial-stuck**: projecting the agent's recent motion onto the
  start->target vector yields less than ``min_progress`` cells of
  forward motion within a sliding window. Reverse motion is capped at
  zero so a single backstep doesn't false-trigger (mirrors
  ``policy_scout.py:769-824``).
* **Pacing-stuck**: agent has been confined to <= N unique cells over
  the last M ticks. Catches oscillation loops (A->B->A->B) that
  position_stuck (single-cell) and axial_stuck (directional progress)
  miss. Disabled by default (``pacing_window=0``); opt in per role.

Cargo / inventory stagnation (``policy_miner.py:147-149``) is
intentionally excluded: it depends on miner-specific cargo state and
doesn't generalize.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Literal

from .tabu import TabuState, add_tabu

Coordinate = tuple[int, int]


@dataclass
class StuckConfig:
    position_window: int = 8           # ticks without position change => stuck
    axial_window: int = 5              # axial-progress sliding window (ticks)
    axial_min_progress: int = 2        # cells of forward motion required
    pacing_window: int = 0             # 0 = disabled. Otherwise: lookback ticks.
    pacing_unique_threshold: int = 6   # confined to <= this many unique cells => stuck

    # Recommended TTLs for the abandoned-target tabu write that callers
    # typically want to do on a stuck trigger. Position-stuck is the
    # more severe condition (frozen, not just oscillating) so its tabu
    # lives longer by default.
    position_stuck_tabu_ttl: int = 600
    pacing_stuck_tabu_ttl: int = 300


@dataclass
class StuckState:
    last_position: Coordinate | None = None
    last_progress_step: int = 0
    history: list[tuple[int, Coordinate]] = field(default_factory=list)
    recent_positions: Deque[Coordinate] = field(default_factory=deque)


def position_stuck(
    state: StuckState,
    position: Coordinate,
    step: int,
    cfg: StuckConfig,
) -> bool:
    """True if ``position`` has been the same for at least
    ``cfg.position_window`` ticks.

    Updates ``state.last_position`` and ``state.last_progress_step``
    in-place. The first call primes the state and returns False.
    """
    if state.last_position != position:
        state.last_position = position
        state.last_progress_step = step
        return False
    return (step - state.last_progress_step) >= cfg.position_window


def axial_stuck(
    state: StuckState,
    position: Coordinate,
    target: Coordinate,
    step: int,
    cfg: StuckConfig,
) -> bool:
    """True if forward axial progress over the last
    ``cfg.axial_window`` ticks is below ``cfg.axial_min_progress``.

    "Forward axial progress" = the cumulative dot product of step
    deltas onto the (start->target) unit vector, with each per-step
    contribution clamped at 0 (so reverse motion contributes 0, not a
    negative). The "start" of the projection is the oldest entry in
    the window.

    Appends ``(step, position)`` to ``state.history`` and trims to the
    window length. Returns False until the window is full.
    """
    state.history.append((step, position))
    # Trim to (window + 1) entries: we need start + window ticks of motion.
    cap = cfg.axial_window + 1
    if len(state.history) > cap:
        del state.history[: len(state.history) - cap]

    if len(state.history) < cap:
        return False  # not enough data yet

    start_step, start_pos = state.history[0]
    if (step - start_step) < cfg.axial_window:
        return False  # window is shorter than configured (gaps in stepping)

    # Direction unit vector from start to target (manhattan-style: each
    # axis normalized independently is fine for 4-connected grids).
    tdr = target[0] - start_pos[0]
    tdc = target[1] - start_pos[1]
    if tdr == 0 and tdc == 0:
        # Already at target; not stuck.
        return False
    mag = (tdr * tdr + tdc * tdc) ** 0.5
    if mag <= 0:
        return False
    ur = tdr / mag
    uc = tdc / mag

    progress = 0.0
    for i in range(1, len(state.history)):
        _, prev = state.history[i - 1]
        _, cur = state.history[i]
        dr = cur[0] - prev[0]
        dc = cur[1] - prev[1]
        contrib = dr * ur + dc * uc
        if contrib > 0:
            progress += contrib
        # else: clamp at 0, don't penalize backsteps

    return progress < float(cfg.axial_min_progress)


def pacing_stuck(
    state: StuckState,
    position: Coordinate,
    step: int,
    cfg: StuckConfig,
) -> bool:
    """True if the agent has been confined to ``<= pacing_unique_threshold``
    unique cells over the last ``pacing_window`` ticks.

    Distinct from ``position_stuck`` (single-cell freeze) and
    ``axial_stuck`` (directional progress). Catches oscillation between
    a small set of cells, e.g. A->B->A->B or the four corners of a
    pocket.

    Disabled when ``cfg.pacing_window == 0``. Otherwise appends to a
    bounded deque sized to the window and returns True iff the deque is
    full and the unique-cell count fits the threshold.
    """
    if cfg.pacing_window <= 0:
        return False

    window = state.recent_positions
    # Resize lazily if the caller changes the window mid-episode.
    if window.maxlen != cfg.pacing_window:
        new_window: Deque[Coordinate] = deque(window, maxlen=cfg.pacing_window)
        state.recent_positions = new_window
        window = new_window

    window.append(position)
    if len(window) < cfg.pacing_window:
        return False
    return len(set(window)) <= cfg.pacing_unique_threshold


def reset(state: StuckState) -> None:
    """Clear all stuck-tracking state. Call when the agent abandons a
    target or successfully arrives so the next pursuit starts clean.
    """
    state.last_position = None
    state.last_progress_step = 0
    state.history.clear()
    state.recent_positions.clear()


# ---------------------------------------------------------------------
# Structured stuck outcome (recovery-aware API)
# ---------------------------------------------------------------------
#
# The detector and the recovery action are tightly coupled in typical
# callers: if a stuck condition fires, the abandoned target usually
# needs a tabu write at the same time. This section bundles the two so
# callers do not have to repeat that wiring at each call site.

@dataclass(frozen=True)
class StuckOutcome:
    """Returned by ``check_and_resolve`` when a stuck condition trips.

    ``kind`` distinguishes the detector that fired; the policy may
    branch on this (e.g., pacing-stuck typically wants to also block
    the recent-positions cells, which the detector cannot do without
    knowing the policy's nav state). ``abandoned_target`` is the cell
    the caller had been pursuing — passed back so the policy can
    target_clear / current_target=None without recomputing it.
    ``suggested_tabu_ttl`` is the TTL that ``check_and_resolve`` used
    if it wrote a tabu entry; useful for logging.
    """
    kind: Literal["position", "pacing"]
    triggered_at: int
    abandoned_target: Coordinate | None
    suggested_tabu_ttl: int


def check_and_resolve(
    state: StuckState,
    position: Coordinate,
    target: Coordinate | None,
    step: int,
    cfg: StuckConfig,
    tabu: TabuState | None = None,
) -> StuckOutcome | None:
    """Run position-stuck then pacing-stuck and (optionally) write the
    abandoned target into ``tabu`` on a trigger.

    Returns ``None`` when neither detector fires — caller proceeds
    normally. Returns a ``StuckOutcome`` when one fires; caller is
    still responsible for the policy-side cleanup (``target_clear``,
    ``stuck.reset(state)``, blocking-cells additions, etc.) but the
    tabu write is structurally tied to detection.

    Position-stuck takes priority over pacing-stuck because a frozen
    agent (single-cell freeze) is the strictly more severe condition;
    pacing-stuck is *also* triggering will be re-examined on the next
    tick after recovery anyway.

    ``tabu=None`` makes this purely diagnostic (no tabu write); useful
    for tests and for callers that manage tabu themselves.

    Axial-stuck is intentionally NOT checked here — its
    "directional progress" semantic is target-shaped and several
    callers want to handle it separately (e.g., re-route without
    abandoning the target). Use ``axial_stuck`` directly when needed.
    """
    if position_stuck(state, position, step, cfg):
        ttl = cfg.position_stuck_tabu_ttl
        if tabu is not None and target is not None:
            add_tabu(tabu, target, step, ttl=ttl)
        return StuckOutcome(
            kind="position",
            triggered_at=step,
            abandoned_target=target,
            suggested_tabu_ttl=ttl,
        )
    if pacing_stuck(state, position, step, cfg):
        ttl = cfg.pacing_stuck_tabu_ttl
        if tabu is not None and target is not None:
            add_tabu(tabu, target, step, ttl=ttl)
        return StuckOutcome(
            kind="pacing",
            triggered_at=step,
            abandoned_target=target,
            suggested_tabu_ttl=ttl,
        )
    return None
