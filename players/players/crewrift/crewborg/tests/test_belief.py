"""Belief-folding tests: phase machine + self-role derivation (design §5)."""

from __future__ import annotations

from players.crewrift.crewborg.perception.entities import ResolvedScene
from players.crewrift.crewborg.types import Belief, Percept, update_belief


def _fold(belief: Belief, tick: int, **resolved_fields) -> None:
    resolved = ResolvedScene(tick=tick, camera_ready=True, camera_x=0, camera_y=0, **resolved_fields)
    update_belief(belief, Percept(tick=tick, messages_applied=tick, resolved=resolved))


def test_phase_transitions_role_reveal_into_playing() -> None:
    belief = Belief()

    _fold(belief, 1, phase_texts=frozenset({"IMPS"}))
    assert belief.phase == "RoleReveal"

    # Reveal text clears; an ordinary playing scene (task counter, no meeting)
    # must advance the machine to Playing rather than sticking at RoleReveal.
    _fold(belief, 2, crew_tasks_remaining=5)
    assert belief.phase == "Playing"
    assert belief.phase_start_tick == 2


def test_alive_crewmate_role_is_derived_during_play() -> None:
    belief = Belief()
    # A plain playing scene with no imposter/ghost HUD marker.
    _fold(belief, 1, crew_tasks_remaining=5)
    assert belief.phase == "Playing"
    assert belief.self_role == "crewmate"


def test_imposter_hud_sets_role_and_kill_ready() -> None:
    belief = Belief()
    _fold(belief, 1, crew_tasks_remaining=5, self_role="imposter", self_kill_ready=True)
    assert belief.self_role == "imposter"
    assert belief.self_kill_ready is True


def test_phase_stays_unknown_before_any_signal() -> None:
    belief = Belief()
    # Camera not yet ready and no signals: phase remains unknown, role unset.
    resolved = ResolvedScene(tick=1, camera_ready=False, camera_x=0, camera_y=0)
    update_belief(belief, Percept(tick=1, messages_applied=1, resolved=resolved))
    assert belief.phase == "unknown"
    assert belief.self_role is None
