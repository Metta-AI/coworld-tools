"""Kill-opportunity helper tests (design §10)."""

from __future__ import annotations

from players.crewrift.crewborg.strategy.opportunity import (
    URGENCY_FULL_TICKS,
    kill_opportunity,
    kill_urgency_ticks,
)
from players.crewrift.crewborg.types import Belief, RosterEntry


def _crew(belief: Belief, object_id: int, xy: tuple[int, int], color: str, tick: int) -> None:
    belief.roster[object_id] = RosterEntry(
        object_id=object_id, color=color, facing="left", world_x=xy[0], world_y=xy[1], last_seen_tick=tick
    )


def test_kill_urgency_is_zero_until_kill_ready() -> None:
    assert kill_urgency_ticks(Belief(last_tick=100)) == 0
    # Ready but the becoming-ready tick is unknown ⇒ no urgency yet.
    assert kill_urgency_ticks(Belief(last_tick=100, self_kill_ready=True)) == 0
    assert kill_urgency_ticks(Belief(last_tick=100, self_kill_ready=True, kill_ready_since_tick=70)) == 30


def test_no_opportunity_without_a_self_position() -> None:
    belief = Belief(last_tick=5)
    _crew(belief, 1, (50, 50), "green", 5)
    assert kill_opportunity(belief) is None


def test_lone_visible_crewmate_is_an_opportunity() -> None:
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=5)
    _crew(belief, 1, (50, 50), "green", 5)
    target = kill_opportunity(belief)
    assert target is not None and target.object_id == 1


def test_a_recent_nearby_witness_vetoes_the_kill() -> None:
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=5)
    _crew(belief, 1, (50, 50), "green", 5)
    _crew(belief, 2, (60, 50), "blue", 5)  # 10px away, seen now ⇒ witness
    assert kill_opportunity(belief) is None


def test_a_stale_witness_no_longer_vetoes_the_kill() -> None:
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=500)
    _crew(belief, 1, (50, 50), "green", 500)
    _crew(belief, 2, (60, 50), "blue", 100)  # last seen 400 ticks ago ⇒ ignored as a witness
    target = kill_opportunity(belief)
    assert target is not None and target.object_id == 1


def test_full_urgency_takes_a_witnessed_target() -> None:
    belief = Belief(
        self_world_x=0, self_world_y=0, last_tick=URGENCY_FULL_TICKS,
        self_kill_ready=True, kill_ready_since_tick=0,
    )
    _crew(belief, 1, (50, 50), "green", URGENCY_FULL_TICKS)
    _crew(belief, 2, (60, 50), "blue", URGENCY_FULL_TICKS)  # witness ignored at full urgency
    target = kill_opportunity(belief)
    assert target is not None and target.object_id == 1
