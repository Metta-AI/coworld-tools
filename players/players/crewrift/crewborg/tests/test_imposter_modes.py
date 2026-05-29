"""Hunt / Pretend / Evade imposter mode tests (design §7.2)."""

from __future__ import annotations

from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, TaskStation, Vent
from players.crewrift.crewborg.modes import EvadeMode, HuntMode, PretendMode
from players.crewrift.crewborg.types import ActionState, Belief, BodyEntry, RosterEntry


def _visible(belief: Belief, object_id: int, xy: tuple[int, int]) -> None:
    belief.roster[object_id] = RosterEntry(
        object_id=object_id, color="red", facing="left", world_x=xy[0], world_y=xy[1],
        last_seen_tick=belief.last_tick,
    )


def test_hunt_targets_nearest_visible_player() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5)
    _visible(belief, 1004, (120, 100))  # near
    _visible(belief, 1007, (600, 600))  # far
    intent = HuntMode().decide(belief, ActionState())
    assert intent.kind == "kill" and intent.target_id == 1004


def test_hunt_idles_with_no_target_in_view() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5)
    # A roster entry from an earlier tick is not "in view" now.
    belief.roster[1004] = RosterEntry(
        object_id=1004, color="red", facing="left", world_x=120, world_y=100, last_seen_tick=1
    )
    assert HuntMode().decide(belief, ActionState()).kind == "idle"


def _map_with_task() -> MapData:
    return MapData(
        width=1000, height=1000,
        tasks=(TaskStation(name="t", x=200, y=200, w=20, h=20),),  # center (210, 210)
        vents=(), rooms=(), button=MapRect(x=0, y=0, w=28, h=34), home=MapPoint(x=0, y=0),
    )


def test_pretend_loiters_toward_then_at_a_task_station() -> None:
    far = Belief(map=_map_with_task(), self_world_x=0, self_world_y=0)
    moving = PretendMode().decide(far, ActionState())
    assert moving.kind == "navigate_to" and moving.point == (210, 210)

    at_station = Belief(map=_map_with_task(), self_world_x=210, self_world_y=210)
    assert PretendMode().decide(at_station, ActionState()).kind == "idle"


def test_evade_vents_when_a_vent_exists() -> None:
    map_data = MapData(
        width=1000, height=1000, tasks=(),
        vents=(Vent(x=300, y=300, w=14, h=14, group="1", group_index=1),),
        rooms=(), button=MapRect(x=0, y=0, w=28, h=34), home=MapPoint(x=0, y=0),
    )
    belief = Belief(map=map_data, self_world_x=100, self_world_y=100)
    assert EvadeMode().decide(belief, ActionState()).kind == "vent"


def test_evade_moves_away_from_body_when_no_vents() -> None:
    map_data = MapData(
        width=1000, height=1000, tasks=(), vents=(), rooms=(),
        button=MapRect(x=0, y=0, w=28, h=34), home=MapPoint(x=0, y=0),
    )
    belief = Belief(map=map_data, self_world_x=100, self_world_y=100)
    belief.bodies[2003] = BodyEntry(object_id=2003, color="green", world_x=110, world_y=100, first_seen_tick=1)
    intent = EvadeMode().decide(belief, ActionState())
    # Away from the body at (110, 100): reflect through self ⇒ (90, 100), to our left.
    assert intent.kind == "navigate_to" and intent.point == (90, 100)
