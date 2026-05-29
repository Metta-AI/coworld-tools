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


def test_non_playing_phases_idle() -> None:
    assert _select(Belief(phase="Lobby")) == "idle"
    assert _select(Belief(phase="RoleReveal")) == "idle"
    assert _select(Belief(phase="Voting")) == "idle"  # Attend Meeting is P3
    assert _select(Belief(phase="GameOver")) == "idle"


def test_imposter_idles_until_p4() -> None:
    # Imposter behaviour lands in P4; until then it falls through to idle.
    assert _select(Belief(phase="Playing", self_role="imposter")) == "idle"
