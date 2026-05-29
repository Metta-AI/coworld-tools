"""Mode selector tests (design §10)."""

from __future__ import annotations

from players.crewrift.crewborg.strategy import RuleBasedStrategy
from players.crewrift.crewborg.types import ActionState, Belief
from players.player_sdk.types import BeliefSnapshot, ModeDirective, SharedMemory


def _select(belief: Belief) -> str:
    memory = SharedMemory(
        belief=belief, action_state=ActionState(), active_directive=ModeDirective(mode="idle")
    )
    directive = RuleBasedStrategy().decide(BeliefSnapshot(tick=1, memory=memory))
    return directive.mode


def test_playing_crewmate_selects_normal() -> None:
    assert _select(Belief(phase="Playing", self_role="crewmate")) == "normal"
    # Role not yet known during early Playing still does tasks.
    assert _select(Belief(phase="Playing", self_role=None)) == "normal"
    # A crewmate ghost keeps doing its own tasks (design §7.3).
    assert _select(Belief(phase="Playing", self_role="dead")) == "normal"


def test_voting_selects_attend_meeting() -> None:
    assert _select(Belief(phase="Voting")) == "attend_meeting"


def test_body_in_view_selects_report_body() -> None:
    from players.crewrift.crewborg.types import BodyEntry

    belief = Belief(phase="Playing", self_role="crewmate", visible_body_ids={2003})
    belief.bodies[2003] = BodyEntry(object_id=2003, color="green", world_x=10, world_y=10, first_seen_tick=1)
    assert _select(belief) == "report_body"


def test_ghost_does_tasks_not_report() -> None:
    from players.crewrift.crewborg.types import BodyEntry

    # A dead crewmate (ghost) can't report; it goes straight to Normal even with a
    # body in view, so it keeps finishing its own tasks (design §7.3).
    belief = Belief(phase="Playing", self_role="dead", visible_body_ids={2003})
    belief.bodies[2003] = BodyEntry(object_id=2003, color="green", world_x=10, world_y=10, first_seen_tick=1)
    assert _select(belief) == "normal"


def test_approaching_believed_imposter_selects_flee() -> None:
    from players.crewrift.crewborg.types import RosterEntry

    belief = Belief(phase="Playing", self_role="crewmate", self_world_x=100, self_world_y=100)
    belief.roster[1004] = RosterEntry(
        object_id=1004, color="red", facing="left", world_x=110, world_y=100, last_seen_tick=1
    )
    belief.believed_imposters = {1004}
    assert _select(belief) == "flee"


def test_non_playing_phases_idle() -> None:
    assert _select(Belief(phase="Lobby")) == "idle"
    assert _select(Belief(phase="RoleReveal")) == "idle"
    assert _select(Belief(phase="GameOver")) == "idle"


def _imposter_with_visible_target(**kwargs) -> Belief:
    from players.crewrift.crewborg.types import RosterEntry

    belief = Belief(phase="Playing", self_role="imposter", last_tick=10, self_world_x=100, self_world_y=100, **kwargs)
    # A lone, isolated, reachable (no nav graph) crewmate — a valid kill opportunity.
    belief.roster[1004] = RosterEntry(
        object_id=1004, color="red", facing="left", world_x=50, world_y=50, last_seen_tick=10
    )
    return belief


def test_imposter_pretends_by_default() -> None:
    # No kill opportunity ⇒ Pretend (which itself follows crew / wanders rooms).
    assert _select(Belief(phase="Playing", self_role="imposter", last_tick=10)) == "pretend"


def test_imposter_hunts_when_kill_ready_with_opportunity() -> None:
    assert _select(_imposter_with_visible_target(self_kill_ready=True)) == "hunt"
    # Kill ready but no target in view ⇒ no opportunity ⇒ pretend.
    no_target = Belief(
        phase="Playing", self_role="imposter", self_kill_ready=True, last_tick=10,
        self_world_x=100, self_world_y=100,
    )
    assert _select(no_target) == "pretend"


def test_imposter_pretends_when_kill_ready_but_no_subtle_opening() -> None:
    from players.crewrift.crewborg.types import RosterEntry

    # Kill ready, but the only crewmate has a witness right beside it and urgency is
    # zero ⇒ keep blending in rather than killing in front of someone.
    belief = Belief(
        phase="Playing", self_role="imposter", self_kill_ready=True, last_tick=10,
        self_world_x=100, self_world_y=100,
    )
    belief.roster[1004] = RosterEntry(
        object_id=1004, color="green", facing="left", world_x=50, world_y=50, last_seen_tick=10
    )
    belief.roster[1005] = RosterEntry(
        object_id=1005, color="blue", facing="left", world_x=58, world_y=50, last_seen_tick=10
    )
    assert _select(belief) == "pretend"


def test_imposter_evades_right_after_a_kill() -> None:
    belief = _imposter_with_visible_target(self_kill_ready=False, last_kill_tick=8)
    assert _select(belief) == "evade"  # last_tick 10 − last_kill_tick 8 < EVADE_TICKS


def test_imposter_pretends_when_only_a_teammate_is_visible() -> None:
    # Kill ready but the only visible player is a teammate ⇒ no target ⇒ pretend.
    belief = _imposter_with_visible_target(self_kill_ready=True)
    belief.teammate_colors = {"red"}  # the visible target is red (see helper)
    assert _select(belief) == "pretend"
