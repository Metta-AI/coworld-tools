"""Tests for the decision pipeline check functions."""

from __future__ import annotations

from unittest.mock import MagicMock

from cvc_policy.agent.decisions import (
    DECISION_PIPELINE,
    check_early_retreat,
    check_emergency_mine,
    check_gear_acquisition,
    check_hub_camp_heal,
    check_oscillation_unstick,
    check_retreat,
    check_stall_unstick,
    check_wipeout_recovery,
    dispatch_role_action,
    run_pipeline,
)
from cvc_policy.agent.tick_context import TickContext
from cvc_policy.agent.types import KnownEntity


def _make_hub(x=44, y=44):
    return KnownEntity(
        entity_type="hub",
        global_x=x,
        global_y=y,
        labels=(),
        team="team_0",
        owner="team_0",
        last_seen_step=100,
        attributes={},
    )


def _make_ctx(
    *,
    hp=100,
    step=500,
    hub_distance=0,
    hub=None,
    hearts=0,
    cargo=0,
    stalled_steps=0,
    oscillation_steps=0,
    in_enemy_aoe=False,
    near_enemy_territory=False,
    state=None,
):
    """Minimal TickContext for decision check tests."""
    if hub is None:
        hub = _make_hub()
    if state is None:
        state = MagicMock()
        state.self_state.inventory = {"hp": hp, "heart": hearts}
        state.step = step
    return TickContext(
        state=state,
        position=(44, 44),
        hp=hp,
        step=step,
        team="team_0",
        resource_bias="carbon",
        hearts=hearts,
        cargo=cargo,
        hub=hub,
        hub_distance=hub_distance,
        in_enemy_aoe=in_enemy_aoe,
        near_enemy_territory=near_enemy_territory,
        friendly_junctions=[],
        enemy_junctions=[],
        neutral_junctions=[],
        network_sources=[],
        stalled_steps=stalled_steps,
        oscillation_steps=oscillation_steps,
        teammate_aligner_positions=[],
    )


def _make_engine():
    engine = MagicMock()
    engine._hold.return_value = (MagicMock(), "hold")
    engine._move_to_known.return_value = (MagicMock(), "move")
    engine._miner_action.return_value = (MagicMock(), "mine")
    engine._aligner_action.return_value = (MagicMock(), "align")
    engine._scrambler_action.return_value = (MagicMock(), "scramble")
    engine._unstick_action.return_value = (MagicMock(), "unstick")
    engine._explore_action.return_value = (MagicMock(), "explore")
    engine._acquire_role_gear.return_value = (MagicMock(), "gear")
    engine._should_retreat.return_value = False
    return engine


class TestCheckHubCampHeal:
    def test_fires_early_game_low_hp_near_hub(self):
        ctx = _make_ctx(hp=50, step=10, hub_distance=2)
        engine = _make_engine()
        result = check_hub_camp_heal(ctx, "miner", engine)
        assert result is not None
        engine._hold.assert_called_once()

    def test_skips_full_hp(self):
        ctx = _make_ctx(hp=100, step=10, hub_distance=2)
        assert check_hub_camp_heal(ctx, "miner", _make_engine()) is None

    def test_skips_after_step_20(self):
        ctx = _make_ctx(hp=50, step=25, hub_distance=2)
        assert check_hub_camp_heal(ctx, "miner", _make_engine()) is None

    def test_skips_far_from_hub(self):
        ctx = _make_ctx(hp=50, step=10, hub_distance=5)
        assert check_hub_camp_heal(ctx, "miner", _make_engine()) is None

    def test_skips_dead(self):
        ctx = _make_ctx(hp=0, step=10, hub_distance=2)
        assert check_hub_camp_heal(ctx, "miner", _make_engine()) is None


class TestCheckEarlyRetreat:
    def test_fires_low_hp_far_from_hub(self):
        ctx = _make_ctx(hp=30, step=100, hub_distance=12)
        engine = _make_engine()
        result = check_early_retreat(ctx, "miner", engine)
        assert result is not None
        engine._move_to_known.assert_called_once()

    def test_fires_medium_hp_very_far(self):
        ctx = _make_ctx(hp=45, step=100, hub_distance=20)
        assert check_early_retreat(ctx, "miner", _make_engine()) is not None

    def test_skips_after_step_150(self):
        ctx = _make_ctx(hp=30, step=200, hub_distance=12)
        assert check_early_retreat(ctx, "miner", _make_engine()) is None

    def test_skips_close_to_hub(self):
        ctx = _make_ctx(hp=30, step=100, hub_distance=5)
        assert check_early_retreat(ctx, "miner", _make_engine()) is None

    def test_skips_high_hp(self):
        ctx = _make_ctx(hp=80, step=100, hub_distance=12)
        assert check_early_retreat(ctx, "miner", _make_engine()) is None


class TestCheckWipeoutRecovery:
    def test_fires_dead_far_from_hub(self):
        ctx = _make_ctx(hp=0, hub_distance=10)
        engine = _make_engine()
        result = check_wipeout_recovery(ctx, "miner", engine)
        assert result is not None
        engine._move_to_known.assert_called_once()

    def test_mines_when_dead_near_hub(self):
        ctx = _make_ctx(hp=0, hub_distance=3)
        engine = _make_engine()
        result = check_wipeout_recovery(ctx, "miner", engine)
        assert result is not None
        engine._miner_action.assert_called_once()

    def test_skips_alive(self):
        ctx = _make_ctx(hp=50)
        assert check_wipeout_recovery(ctx, "miner", _make_engine()) is None

    def test_skips_no_hub(self):
        ctx = _make_ctx(hp=0, hub=None)
        ctx = TickContext(
            state=ctx.state,
            position=ctx.position,
            hp=0,
            step=ctx.step,
            team=ctx.team,
            resource_bias=ctx.resource_bias,
            hearts=ctx.hearts,
            cargo=ctx.cargo,
            hub=None,
            hub_distance=0,
            in_enemy_aoe=False,
            near_enemy_territory=False,
            friendly_junctions=[],
            enemy_junctions=[],
            neutral_junctions=[],
            network_sources=[],
            stalled_steps=0,
            oscillation_steps=0,
            teammate_aligner_positions=[],
        )
        assert check_wipeout_recovery(ctx, "miner", _make_engine()) is None


class TestCheckRetreat:
    def test_fires_when_should_retreat(self):
        ctx = _make_ctx(hub_distance=10)
        engine = _make_engine()
        engine._should_retreat.return_value = True
        result = check_retreat(ctx, "miner", engine)
        assert result is not None
        engine._clear_sticky_target.assert_called_once()

    def test_skips_when_safe(self):
        ctx = _make_ctx()
        engine = _make_engine()
        engine._should_retreat.return_value = False
        assert check_retreat(ctx, "miner", engine) is None


class TestCheckOscillationUnstick:
    def test_fires_at_threshold(self):
        ctx = _make_ctx(oscillation_steps=4)
        engine = _make_engine()
        result = check_oscillation_unstick(ctx, "miner", engine)
        assert result is not None
        engine._unstick_action.assert_called_once()

    def test_skips_below_threshold(self):
        ctx = _make_ctx(oscillation_steps=3)
        assert check_oscillation_unstick(ctx, "miner", _make_engine()) is None


class TestCheckStallUnstick:
    def test_fires_at_threshold(self):
        ctx = _make_ctx(stalled_steps=12)
        engine = _make_engine()
        result = check_stall_unstick(ctx, "miner", engine)
        assert result is not None

    def test_skips_below_threshold(self):
        ctx = _make_ctx(stalled_steps=11)
        assert check_stall_unstick(ctx, "miner", _make_engine()) is None


class TestCheckEmergencyMine:
    def test_skips_for_miners(self):
        ctx = _make_ctx()
        assert check_emergency_mine(ctx, "miner", _make_engine()) is None

    def test_fires_for_ungeared_aligner_without_hearts(self, make_state):
        state = make_state(shared_inventory={"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0, "heart": 0})
        ctx = _make_ctx(state=state, hearts=0)
        engine = _make_engine()
        result = check_emergency_mine(ctx, "aligner", engine)
        assert result is not None

    def test_skips_if_has_hearts(self, make_state):
        state = make_state(shared_inventory={"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0})
        ctx = _make_ctx(state=state, hearts=2)
        assert check_emergency_mine(ctx, "aligner", _make_engine()) is None


class TestCheckGearAcquisition:
    def test_fires_when_no_gear(self, make_state):
        state = make_state(inventory={"aligner": 0})
        ctx = _make_ctx(state=state)
        engine = _make_engine()
        result = check_gear_acquisition(ctx, "aligner", engine)
        assert result is not None

    def test_skips_when_has_gear(self, make_state):
        state = make_state(inventory={"aligner": 1})
        ctx = _make_ctx(state=state)
        assert check_gear_acquisition(ctx, "aligner", _make_engine()) is None


class TestDispatchRoleAction:
    def test_dispatches_miner(self):
        ctx = _make_ctx()
        engine = _make_engine()
        dispatch_role_action(ctx, "miner", engine)
        engine._miner_action.assert_called_once()

    def test_dispatches_aligner(self):
        ctx = _make_ctx()
        engine = _make_engine()
        dispatch_role_action(ctx, "aligner", engine)
        engine._aligner_action.assert_called_once()

    def test_dispatches_scrambler(self):
        ctx = _make_ctx()
        engine = _make_engine()
        dispatch_role_action(ctx, "scrambler", engine)
        engine._scrambler_action.assert_called_once()

    def test_unknown_role_explores(self):
        ctx = _make_ctx()
        engine = _make_engine()
        dispatch_role_action(ctx, "scout", engine)
        engine._explore_action.assert_called_once()


class TestRunPipeline:
    def test_returns_first_match(self):
        ctx = _make_ctx(hp=50, step=10, hub_distance=2)
        engine = _make_engine()
        result = run_pipeline(ctx, "miner", engine)
        # hub_camp_heal should fire (hp<100, step<=20, hub_distance<=3)
        assert result is not None
        engine._hold.assert_called_once()

    def test_falls_through_to_role_dispatch(self):
        ctx = _make_ctx(hp=100, step=500)
        engine = _make_engine()
        result = run_pipeline(ctx, "miner", engine)
        assert result is not None
        engine._miner_action.assert_called_once()

    def test_pipeline_has_10_checks(self):
        assert len(DECISION_PIPELINE) == 10
