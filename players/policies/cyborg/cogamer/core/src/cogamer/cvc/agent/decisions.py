"""Decision pipeline: composable check functions for the CvC engine.

Each check function takes (ctx, role, engine) and returns an (Action, summary)
tuple if it fires, or None to pass to the next check. The pipeline runs checks
in priority order; first non-None result wins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cogamer.cvc.agent.resources import has_role_gear, needs_emergency_mining, team_can_afford_gear
from cogamer.cvc.agent.tick_context import TickContext
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from cogamer.cvc.agent.main import CvcEngine

_ALIGNER_GEAR_DELAY_STEPS = 0
_OSCILLATION_UNSTICK_STEPS = 4
_STALL_UNSTICK_STEPS = 12


def check_hub_camp_heal(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Stay at hub until full HP in early game."""
    if ctx.hp < 100 and ctx.hp > 0 and ctx.hub is not None and ctx.hub_distance <= 3 and ctx.step <= 20:
        return engine._hold(summary="hub_camp_heal", vibe="change_vibe_default")
    return None


def check_early_retreat(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Rush back to hub if low HP in first 150 steps."""
    if ctx.step >= 150 or ctx.hub is None or ctx.hub_distance <= 8:
        return None
    if ctx.hp < 40 or (ctx.hp < 50 and ctx.hub_distance > 15):
        return engine._move_to_known(ctx.state, ctx.hub, summary="survival_retreat")
    return None


def check_wipeout_recovery(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Return to hub area when dead (HP=0)."""
    if ctx.hp != 0 or ctx.hub is None:
        return None
    if ctx.hub_distance > 5:
        return engine._move_to_known(ctx.state, ctx.hub, summary="wipeout_return_hub")
    return engine._miner_action(ctx.state, summary_prefix="wipeout_mine_")


def check_retreat(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Retreat to hub when HP is dangerously low."""
    if not engine._should_retreat(ctx.state, role, ctx.hub):
        return None
    engine._clear_target_claim()
    engine._clear_sticky_target()
    if ctx.hub is not None and ctx.hub_distance > 2:
        return engine._move_to_known(ctx.state, ctx.hub, summary="retreat_to_hub")
    if has_role_gear(ctx.state, role):
        return engine._hold(summary="retreat_hold", vibe="change_vibe_default")
    return None  # Fall through — retreat triggered but no safe action available


def check_oscillation_unstick(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Break out of back-and-forth extractor oscillation."""
    if ctx.oscillation_steps >= _OSCILLATION_UNSTICK_STEPS:
        return engine._unstick_action(ctx.state, role)
    return None


def check_stall_unstick(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Break out of being stuck at one position."""
    if ctx.stalled_steps >= _STALL_UNSTICK_STEPS:
        return engine._unstick_action(ctx.state, role)
    return None


def check_emergency_mine(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Non-miners without gear or hearts help mine when team resources critical."""
    if role == "miner":
        return None
    if not needs_emergency_mining(ctx.state):
        return None
    if has_role_gear(ctx.state, role) or ctx.hearts > 0:
        return None
    return engine._miner_action(ctx.state, summary_prefix="emergency_")


def check_gear_delay(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Delay aligner gear acquisition in very early game."""
    if role != "aligner" or has_role_gear(ctx.state, role):
        return None
    if ctx.step >= _ALIGNER_GEAR_DELAY_STEPS:
        return None
    engine._clear_target_claim()
    engine._clear_sticky_target()
    return engine._miner_action(ctx.state, summary_prefix="delay_gear_")


def check_gear_acquisition(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Acquire role gear, or mine to fund it if team can't afford."""
    if has_role_gear(ctx.state, role):
        return None
    engine._clear_target_claim()
    engine._clear_sticky_target()
    if not team_can_afford_gear(ctx.state, role):
        return engine._miner_action(ctx.state, summary_prefix=f"fund_{role}_gear_")
    return engine._acquire_role_gear(ctx.state, role)


def dispatch_role_action(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str] | None:
    """Execute role-specific action (miner/aligner/scrambler)."""
    if role == "miner":
        return engine._miner_action(ctx.state)
    if role == "aligner":
        return engine._aligner_action(ctx.state)
    if role == "scrambler":
        return engine._scrambler_action(ctx.state)
    return engine._explore_action(ctx.state, role=role, summary="explore")


DECISION_PIPELINE: list = [
    check_hub_camp_heal,
    check_early_retreat,
    check_wipeout_recovery,
    check_retreat,
    check_oscillation_unstick,
    check_stall_unstick,
    check_emergency_mine,
    check_gear_delay,
    check_gear_acquisition,
    dispatch_role_action,
]


def run_pipeline(ctx: TickContext, role: str, engine: CvcEngine) -> tuple[Action, str]:
    """Run decision checks in priority order. First non-None result wins."""
    for check in DECISION_PIPELINE:
        result = check(ctx, role, engine)
        if result is not None:
            return result
    return engine._explore_action(ctx.state, role=role, summary="explore")
