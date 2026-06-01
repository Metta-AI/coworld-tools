"""Hunt / Pretend / Evade imposter mode tests (design §7.2)."""

from __future__ import annotations

import numpy as np

from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, Room, TaskStation
from players.crewrift.crewborg.modes import EvadeMode, HuntMode, PretendMode
from players.crewrift.crewborg.nav import build_nav_graph
from players.crewrift.crewborg.types import ActionState, Belief, BodyEntry, RosterEntry


def _visible(belief: Belief, object_id: int, xy: tuple[int, int], color: str = "red", tick: int | None = None) -> None:
    belief.roster[object_id] = RosterEntry(
        object_id=object_id, color=color, facing="left", world_x=xy[0], world_y=xy[1],
        last_seen_tick=belief.last_tick if tick is None else tick,
    )


# --------------------------------------------------------------------------- #
# Hunt — drives off the shared kill-opportunity helper                        #
# --------------------------------------------------------------------------- #


def test_hunt_strikes_a_victim_in_range_and_unwitnessed() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5)
    _visible(belief, 1004, (108, 100), color="green")  # 8px away (<KillRange), alone
    intent = HuntMode().decide(belief, ActionState())
    assert intent.kind == "kill" and intent.target_id == 1004


def test_hunt_stalks_a_distant_victim() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5)
    _visible(belief, 1004, (300, 100), color="green")  # far ⇒ close in, don't kill
    intent = HuntMode().decide(belief, ActionState())
    assert intent.kind == "navigate_to" and intent.point[0] > 100  # heading toward the victim


def test_hunt_idles_with_no_victim_in_view() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5)
    _visible(belief, 1004, (120, 100), tick=1)  # earlier-tick sighting only ⇒ nothing to commit to
    assert HuntMode().decide(belief, ActionState()).kind == "idle"


def test_hunt_skips_teammates() -> None:
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5)
    belief.teammate_colors = {"red"}
    _visible(belief, 1004, (108, 100), color="red")  # teammate — never a victim
    assert HuntMode().decide(belief, ActionState()).kind == "idle"

    _visible(belief, 1007, (108, 100), color="green")  # an in-range crewmate is killable
    intent = HuntMode().decide(belief, ActionState())
    assert intent.kind == "kill" and intent.target_id == 1007


def test_hunt_lies_in_wait_when_a_witness_is_near() -> None:
    # Victim in range but a witness beside it (zero urgency) ⇒ shadow, don't fire.
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5, self_kill_ready=True)
    _visible(belief, 1004, (108, 100), color="green")
    _visible(belief, 1005, (110, 100), color="blue")  # witness next to the victim
    intent = HuntMode().decide(belief, ActionState())
    assert intent.kind == "navigate_to"  # lying in wait, not killing


def test_hunt_strikes_a_witnessed_victim_under_full_urgency() -> None:
    belief = Belief(
        self_world_x=100, self_world_y=100, last_tick=300, self_kill_ready=True, kill_ready_since_tick=0,
    )
    _visible(belief, 1004, (108, 100), color="green")
    _visible(belief, 1005, (110, 100), color="blue")  # witness ignored at full urgency
    intent = HuntMode().decide(belief, ActionState())
    assert intent.kind == "kill" and intent.target_id == 1004


def test_hunt_commits_to_one_victim_across_ticks() -> None:
    # Once committed, Hunt keeps the same victim even as another comes closer.
    mode = HuntMode()
    belief = Belief(self_world_x=100, self_world_y=100, last_tick=5)
    _visible(belief, 1004, (300, 100), color="green")
    mode.decide(belief, ActionState())  # commits to 1004
    assert mode._victim_id == 1004
    _visible(belief, 1009, (140, 100), color="white")  # a nearer crewmate appears
    mode.decide(belief, ActionState())
    assert mode._victim_id == 1004  # still committed to the first victim


def test_hunt_prefers_reachable_victim() -> None:
    mask = np.ones((24, 120), dtype=bool)
    mask[:, 56:64] = False  # wall splits the map; right side is unreachable from the left
    belief = Belief(self_world_x=8, self_world_y=12, last_tick=5)
    belief.nav = build_nav_graph(mask, cell_size=8)
    _visible(belief, 1001, (110, 12), color="green")  # right side: UNREACHABLE
    _visible(belief, 1002, (10, 12), color="blue")  # left: reachable
    mode = HuntMode()
    mode.decide(belief, ActionState())
    assert mode._victim_id == 1002  # committed to the reachable one, not 1001


# --------------------------------------------------------------------------- #
# Pretend — shadow the crew, fake tasks at real stations in their room        #
# --------------------------------------------------------------------------- #


def _shadow_map() -> MapData:
    # A dedicated starting room (holds home) plus two task rooms with one station each.
    return MapData(
        width=200, height=120,
        tasks=(
            TaskStation(name="a", x=70, y=40, w=20, h=20),  # in room A, center (80, 50)
            TaskStation(name="b", x=150, y=40, w=20, h=20),  # in room B, center (160, 50)
        ),
        vents=(),
        rooms=(
            Room(name="Start", x=0, y=0, w=40, h=120),
            Room(name="A", x=40, y=0, w=80, h=120),
            Room(name="B", x=120, y=0, w=80, h=120),
        ),
        button=MapRect(x=0, y=100, w=10, h=10), home=MapPoint(x=10, y=10),
    )


def _belief(map_data: MapData, nav, self_xy: tuple[int, int], tick: int) -> Belief:
    return Belief(map=map_data, nav=nav, self_world_x=self_xy[0], self_world_y=self_xy[1], last_tick=tick)


def _see(belief: Belief, object_id: int, xy: tuple[int, int], tick: int | None = None, color: str = "green") -> None:
    belief.roster[object_id] = RosterEntry(
        object_id=object_id, color=color, facing="left", world_x=xy[0], world_y=xy[1],
        last_seen_tick=belief.last_tick if tick is None else tick,
    )


def test_pretend_idles_only_without_a_self_position() -> None:
    # The one unavoidable idle: camera not up yet (no self position).
    belief = Belief(map=_shadow_map(), last_tick=0)
    assert PretendMode().decide(belief, ActionState()).kind == "idle"


def test_pretend_follows_the_nearest_visible_crewmate() -> None:
    map_data = _shadow_map()
    nav = build_nav_graph(np.ones((120, 200), dtype=bool), map_data=map_data)
    belief = _belief(map_data, nav, (10, 10), tick=5)  # we are in the start room
    _see(belief, 1001, (80, 60))  # a crewmate over in room A
    intent = PretendMode().decide(belief, ActionState())
    assert intent.kind == "navigate_to" and intent.point == (80, 60)  # toward the crewmate


def test_pretend_fakes_a_task_when_in_a_room_with_the_target() -> None:
    map_data = _shadow_map()
    nav = build_nav_graph(np.ones((120, 200), dtype=bool), map_data=map_data)
    # We and the target are both inside room A (non-start, has a station).
    belief = _belief(map_data, nav, (110, 60), tick=5)
    _see(belief, 1001, (100, 60))
    moving = PretendMode().decide(belief, ActionState())
    assert moving.kind == "navigate_to"
    assert 70 <= moving.point[0] < 90 and 40 <= moving.point[1] < 60  # room A's station rect


def test_pretend_does_not_fake_a_task_in_the_starting_room() -> None:
    map_data = _shadow_map()
    nav = build_nav_graph(np.ones((120, 200), dtype=bool), map_data=map_data)
    # Both of us in the *starting* room ⇒ no fake task here, just keep following.
    belief = _belief(map_data, nav, (10, 60), tick=5)
    _see(belief, 1001, (25, 60))
    intent = PretendMode().decide(belief, ActionState())
    assert intent.kind == "navigate_to" and intent.point == (25, 60)  # following, not a station


def test_pretend_recovers_to_the_targets_last_seen_spot_when_lost() -> None:
    map_data = _shadow_map()
    nav = build_nav_graph(np.ones((120, 200), dtype=bool), map_data=map_data)
    belief = _belief(map_data, nav, (10, 10), tick=200)
    _see(belief, 1001, (160, 60), tick=100)  # last seen a while ago, not visible now
    mode = PretendMode()
    mode._state, mode._target_id = "follow", 1001  # we had been following it
    intent = mode.decide(belief, ActionState())
    assert intent.kind == "navigate_to" and intent.point == (160, 60)  # to the last-seen spot


def test_pretend_wanders_rooms_when_no_crew_is_in_sight() -> None:
    map_data = _shadow_map()
    nav = build_nav_graph(np.ones((120, 200), dtype=bool), map_data=map_data)
    belief = _belief(map_data, nav, (10, 10), tick=5)  # nobody known/visible
    intent = PretendMode().decide(belief, ActionState())
    assert intent.kind == "navigate_to"  # wandering, never idle
    assert intent.point[0] >= 40  # heading out of the start room toward another room


def test_pretend_wandering_switches_to_follow_on_sighting_a_crewmate() -> None:
    map_data = _shadow_map()
    nav = build_nav_graph(np.ones((120, 200), dtype=bool), map_data=map_data)
    belief = _belief(map_data, nav, (10, 10), tick=5)
    _see(belief, 1001, (80, 60))  # a crewmate appears
    mode = PretendMode()
    mode._state, mode._goto_point = "goto_room", (160, 60)  # mid-wander
    intent = mode.decide(belief, ActionState())
    assert intent.kind == "navigate_to" and intent.point == (80, 60)  # dropped the wander to follow


# --------------------------------------------------------------------------- #
# Evade — escape far from the body (venting only if it is on the fast route)   #
# --------------------------------------------------------------------------- #


def test_evade_leaves_the_immediate_vicinity_but_stays_local() -> None:
    from players.crewrift.crewborg.modes.evade import EVADE_RADIUS

    # A large open map so a node near the EVADE_RADIUS ring around the body exists.
    map_data = MapData(
        width=600, height=600, tasks=(), vents=(), rooms=(),
        button=MapRect(x=0, y=590, w=8, h=8), home=MapPoint(x=300, y=300),
    )
    nav = build_nav_graph(np.ones((600, 600), dtype=bool), map_data=map_data)
    belief = Belief(map=map_data, nav=nav, self_world_x=300, self_world_y=300, last_tick=10)
    belief.bodies[2003] = BodyEntry(object_id=2003, color="green", world_x=300, world_y=300, first_seen_tick=8)

    intent = EvadeMode().decide(belief, ActionState())
    assert intent.kind == "escape"
    dist = ((intent.point[0] - 300) ** 2 + (intent.point[1] - 300) ** 2) ** 0.5
    # Left the immediate vicinity, but stayed ~EVADE_RADIUS away — not a far corner.
    assert abs(dist - EVADE_RADIUS) <= 16


def test_evade_moves_away_from_body_before_the_nav_graph_exists() -> None:
    map_data = MapData(
        width=1000, height=1000, tasks=(), vents=(), rooms=(),
        button=MapRect(x=0, y=0, w=28, h=34), home=MapPoint(x=0, y=0),
    )
    belief = Belief(map=map_data, self_world_x=100, self_world_y=100, last_tick=10)
    belief.bodies[2003] = BodyEntry(object_id=2003, color="green", world_x=110, world_y=100, first_seen_tick=1)
    intent = EvadeMode().decide(belief, ActionState())
    # No graph: reflect the body at (110,100) through self ⇒ (90,100), to our left.
    assert intent.kind == "escape" and intent.point == (90, 100)
