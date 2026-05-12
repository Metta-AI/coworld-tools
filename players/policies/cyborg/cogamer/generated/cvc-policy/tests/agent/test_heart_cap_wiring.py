"""Tests that the heart-cap tracker is wired into CogletAgentPolicy and
GameState alongside the existing cargo-cap tracker."""

from __future__ import annotations

from cvc_policy.agent.heart_cap import HeartCapTracker


def test_game_state_has_heart_cap_tracker():
    from cvc_policy.game_state import GameState
    from tests.conftest import _fake_policy_env_info

    gs = GameState(_fake_policy_env_info(), agent_id=0)
    assert gs.engine._heart_cap is not None
    assert isinstance(gs.engine._heart_cap, HeartCapTracker)


def test_game_state_forwards_on_heart_cap_discovery():
    """GameState should plumb on_heart_cap_discovery into the HeartCapTracker."""
    from cvc_policy.game_state import GameState
    from tests.conftest import _fake_policy_env_info

    seen: list[tuple[tuple[str, ...], int]] = []
    gs = GameState(
        _fake_policy_env_info(),
        agent_id=0,
        on_heart_cap_discovery=lambda sig, cap: seen.append((sig, cap)),
    )
    for i, h in enumerate([0, 1, 2, 3, 3]):
        gs.engine._heart_cap.observe(
            gear_sig=("aligner",), hearts=h, tried_pickup_last_tick=i > 0
        )
    assert seen == [(("aligner",), 3)]


def test_engine_tracks_prev_summary_was_heart_pickup():
    """finalize_step should set _prev_summary_was_heart_pickup based on the
    summary string emitted by the role action."""
    from cvc_policy.game_state import GameState
    from tests.conftest import _fake_policy_env_info

    gs = GameState(_fake_policy_env_info(), agent_id=0)

    # Ensure finalize_step is a no-op without mg_state — it returns early.
    gs.mg_state = None
    gs.finalize_step("acquire_heart")
    assert gs.engine._prev_summary_was_heart_pickup is False  # untouched

    # Drive the flag directly via an mg_state stub.
    class _SelfState:
        inventory: dict = {}
        attributes: dict = {}

    class _MgState:
        self_state = _SelfState()

    gs.mg_state = _MgState()  # type: ignore[assignment]
    # Patch the navigation observation to a no-op so we don't need a real
    # world model wired up for this micro-test.
    gs.engine._record_navigation_observation = lambda *a, **kw: None  # type: ignore[method-assign]
    gs.engine._last_global_pos = (0, 0)

    gs.finalize_step("acquire_heart")
    assert gs.engine._prev_summary_was_heart_pickup is True

    gs.finalize_step("batch_hearts")
    assert gs.engine._prev_summary_was_heart_pickup is True

    gs.finalize_step("mine_carbon")
    assert gs.engine._prev_summary_was_heart_pickup is False
