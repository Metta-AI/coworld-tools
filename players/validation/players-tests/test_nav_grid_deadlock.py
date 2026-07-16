"""Scenario tests for players.player_sdk.nav_grid (deadlock).

Ported 1:1 from the embedded smoke test of the original ``swgy_deadlock.py``
(sm-policies SWGY-Nav bundle). The numbered scenario comments and the
``check(label, ...)`` assertion labels are preserved verbatim so failures
map straight back to the origin scenarios.
"""

from __future__ import annotations

from players.player_sdk.nav_grid.core import Coordinate
from players.player_sdk.nav_grid.deadlock import (
    DeadlockConfig,
    DeadlockState,
    pick_backoff_cell,
    update_deadlock_state,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_deadlock_smoke_scenarios() -> None:

    cfg = DeadlockConfig(
        wait_max_ticks=10,
        min_anchor_distance=1,
        backoff_distance=4,
        retry_cooldown=20,
    )
    anchor: Coordinate = (0, 0)

    # 1. Far from anchor: never deadlocks; cooldown stays 0.
    s = DeadlockState()
    triggered = False
    for step in range(30):
        if update_deadlock_state(s, anchor, can_progress=False, my_pos=(20, 20), step=step, cfg=cfg):
            triggered = True
            break
    check("1 far from anchor never triggers", not triggered and s.cooldown_until_step == 0)

    # 2. Adjacent + can_progress True: never triggers regardless of dwell.
    s = DeadlockState()
    triggered = False
    for step in range(30):
        if update_deadlock_state(s, anchor, can_progress=True, my_pos=(0, 1), step=step, cfg=cfg):
            triggered = True
            break
    check("2 adjacent but can_progress => no trigger", not triggered)

    # 3. Adjacent + can_progress False + dwell >= wait_max: triggers and
    #    arms cooldown + backoff_target.
    s = DeadlockState()
    triggered_at = None
    for step in range(30):
        on_cd = update_deadlock_state(s, anchor, can_progress=False, my_pos=(0, 1), step=step, cfg=cfg)
        if on_cd and triggered_at is None:
            triggered_at = step
            break
    check("3 deadlock fires at wait_max", triggered_at == cfg.wait_max_ticks, f"triggered_at={triggered_at}")
    check("3b backoff_target set", s.backoff_target is not None)
    check("3c cooldown set", s.cooldown_until_step == cfg.wait_max_ticks + cfg.retry_cooldown)
    # Backoff direction: my_pos=(0,1) -> sc=+1, sr=0 -> (0, 4).
    check("3d backoff direction asymmetric", s.backoff_target == (0, 4), f"got {s.backoff_target}")

    # 4. Asymmetric scatter: agents on opposite sides go opposite ways.
    backoff_ne = pick_backoff_cell(anchor, my_pos=(-1, 1), distance=4)  # NE
    backoff_sw = pick_backoff_cell(anchor, my_pos=(1, -1), distance=4)  # SW
    check("4 NE agent backs off NE", backoff_ne == (-4, 4))
    check("4b SW agent backs off SW", backoff_sw == (4, -4))

    # 5. Agent literally on anchor: deterministic SE default.
    on = pick_backoff_cell(anchor, my_pos=(0, 0), distance=4)
    check("5 on-anchor SE default", on == (4, 4))

    # 6. distance <= 0 => None.
    none = pick_backoff_cell(anchor, my_pos=(0, 1), distance=0)
    check("6 zero distance None", none is None)

    # 7. Adjacency reset: agent walks away mid-dwell, dwell counter restarts.
    s = DeadlockState()
    # Dwell 5 ticks adjacent.
    for step in range(5):
        update_deadlock_state(s, anchor, can_progress=False, my_pos=(0, 1), step=step, cfg=cfg)
    check("7 adjacency dwell partway", s.at_resource_since_step == 0)
    # Step away.
    update_deadlock_state(s, anchor, can_progress=False, my_pos=(5, 5), step=5, cfg=cfg)
    check("7b adjacency reset after stepping away", s.at_resource_since_step is None)
    # Re-enter adjacency: dwell counter restarts at the new step.
    update_deadlock_state(s, anchor, can_progress=False, my_pos=(0, 1), step=6, cfg=cfg)
    check("7c adjacency dwell restarts", s.at_resource_since_step == 6)

    # 8. anchor=None: returns cooldown state only, doesn't crash.
    s = DeadlockState(cooldown_until_step=15)
    on_cd = update_deadlock_state(s, None, can_progress=False, my_pos=(0, 0), step=10, cfg=cfg)
    check("8 anchor None during cooldown", on_cd)
    on_cd2 = update_deadlock_state(s, None, can_progress=False, my_pos=(0, 0), step=20, cfg=cfg)
    check("8b anchor None after cooldown", not on_cd2)

    # 9. min_anchor_distance respected: with 0, only ON-anchor counts as
    #    adjacent; agent at (0,1) is NOT adjacent.
    cfg_strict = DeadlockConfig(
        wait_max_ticks=5, min_anchor_distance=0, backoff_distance=4, retry_cooldown=10
    )
    s = DeadlockState()
    triggered = False
    for step in range(20):
        if update_deadlock_state(s, anchor, can_progress=False, my_pos=(0, 1), step=step, cfg=cfg_strict):
            triggered = True
            break
    check("9 min_anchor_distance=0 excludes neighbors", not triggered)

    # 10. Cooldown blocks retargeting until expiry.
    s = DeadlockState(cooldown_until_step=50)
    on_cd_during = update_deadlock_state(s, anchor, can_progress=False, my_pos=(20, 20), step=30, cfg=cfg)
    check("10 cooldown blocks during", on_cd_during)
    on_cd_after = update_deadlock_state(s, anchor, can_progress=False, my_pos=(20, 20), step=51, cfg=cfg)
    check("10b cooldown clears after", not on_cd_after)
