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


def test_imposter_idles_until_p4() -> None:
    # Imposter behaviour lands in P4; until then it falls through to idle.
    assert _select(Belief(phase="Playing", self_role="imposter")) == "idle"
