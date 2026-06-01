"""Victim-selection + witness logic tests (design §7.2, §10)."""

from __future__ import annotations

from players.crewrift.crewborg.strategy.opportunity import (
    TRACK_WINDOW_TICKS,
    URGENCY_FULL_TICKS,
    has_trackable_victim,
    kill_urgency_ticks,
    select_victim,
    unwitnessed,
)
from players.crewrift.crewborg.types import Belief, RosterEntry


def _crew(belief: Belief, object_id: int, xy: tuple[int, int], color: str, tick: int) -> None:
    belief.roster[object_id] = RosterEntry(
        object_id=object_id, color=color, facing="left", world_x=xy[0], world_y=xy[1], last_seen_tick=tick
    )


# --- urgency ----------------------------------------------------------------


def test_kill_urgency_is_zero_until_kill_ready() -> None:
    assert kill_urgency_ticks(Belief(last_tick=100)) == 0
    assert kill_urgency_ticks(Belief(last_tick=100, self_kill_ready=True)) == 0  # since-tick unknown
    assert kill_urgency_ticks(Belief(last_tick=100, self_kill_ready=True, kill_ready_since_tick=70)) == 30


# --- has_trackable_victim (selector gate) -----------------------------------


def test_trackable_when_a_crewmate_was_seen_recently() -> None:
    belief = Belief(last_tick=200)
    _crew(belief, 1, (50, 50), "green", 200 - (TRACK_WINDOW_TICKS - 1))  # within the window
    assert has_trackable_victim(belief)


def test_not_trackable_when_only_stale_or_teammates() -> None:
    belief = Belief(last_tick=500, teammate_colors={"red"})
    _crew(belief, 1, (50, 50), "green", 500 - (TRACK_WINDOW_TICKS + 50))  # too stale
    _crew(belief, 2, (60, 50), "red", 500)  # a teammate, never a victim
    assert not has_trackable_victim(belief)


# --- select_victim ----------------------------------------------------------


def test_select_victim_needs_a_self_position() -> None:
    belief = Belief(last_tick=5)
    _crew(belief, 1, (50, 50), "green", 5)
    assert select_victim(belief) is None


def test_select_victim_takes_a_lone_visible_crewmate() -> None:
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=5)
    _crew(belief, 1, (50, 50), "green", 5)
    v = select_victim(belief)
    assert v is not None and v.object_id == 1


def test_select_victim_prefers_the_isolated_straggler() -> None:
    # Two clustered crewmates and one straggler far from everyone ⇒ pick the straggler
    # (easiest to finish off unwitnessed), even though it's farther from us.
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=5)
    _crew(belief, 1, (40, 0), "green", 5)  # clustered pair...
    _crew(belief, 2, (50, 0), "blue", 5)  # ...10px apart
    _crew(belief, 3, (300, 0), "white", 5)  # the straggler, far from the others
    v = select_victim(belief)
    assert v is not None and v.object_id == 3


# --- unwitnessed ------------------------------------------------------------


def test_unwitnessed_true_for_a_lone_target() -> None:
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=5)
    _crew(belief, 1, (50, 50), "green", 5)
    assert unwitnessed(belief, belief.roster[1])


def test_unwitnessed_false_with_a_recent_nearby_witness() -> None:
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=5)
    _crew(belief, 1, (50, 50), "green", 5)
    _crew(belief, 2, (60, 50), "blue", 5)  # 10px away, seen now ⇒ witness
    assert not unwitnessed(belief, belief.roster[1])


def test_unwitnessed_ignores_a_stale_witness() -> None:
    belief = Belief(self_world_x=0, self_world_y=0, last_tick=500)
    _crew(belief, 1, (50, 50), "green", 500)
    _crew(belief, 2, (60, 50), "blue", 100)  # last seen 400 ticks ago ⇒ ignored
    assert unwitnessed(belief, belief.roster[1])


def test_full_urgency_strikes_through_a_witness() -> None:
    belief = Belief(
        self_world_x=0, self_world_y=0, last_tick=URGENCY_FULL_TICKS,
        self_kill_ready=True, kill_ready_since_tick=0,
    )
    _crew(belief, 1, (50, 50), "green", URGENCY_FULL_TICKS)
    _crew(belief, 2, (60, 50), "blue", URGENCY_FULL_TICKS)  # witness ignored at full urgency
    assert unwitnessed(belief, belief.roster[1])
