"""Pretend mode: the imposter's default blending behaviour (design §7.2).

A small four-state FSM that keeps the imposter doing crewmate-like things and never
standing still. It carries no notion of a "victim" — it just looks busy and stays
among the crew so Hunt (which preempts it via the selector) gets openings.

    DISPATCH (transient): crewmate visible? → FOLLOW(nearest) ; else → GOTO_ROOM(next)

    FOLLOW(target)    navigate to the target's live position
        • same room as target, room non-start with a station → DO_TASK
        • target not visible                                  → RECOVER
    RECOVER(target)   navigate to the target's last-seen position
        • target visible again                                → FOLLOW(target)
        • arrived, target still not visible                   → DISPATCH
    GOTO_ROOM(R)      wander to room R (round-robin, R ≠ current room); never idles
        • any crewmate visible                                → DISPATCH
        • arrived, still no crew                              → next room
    DO_TASK(station)  go to the station, then hold TASK_TICKS (a fake task) → DISPATCH

"Random" crewmate/room choices are arbitrary-but-deterministic (nearest crewmate,
round-robin rooms) so runs are reproducible. The starting room never triggers a fake
task (every player spawns there, and anchoring a task there stranded the imposter
when the crew dispersed). The mode keeps its state across ticks: the runtime
preserves one Pretend instance while the directive stays ``pretend``.
"""

from __future__ import annotations

from players.crewrift.crewborg.modes import imposter_common as ic
from players.crewrift.crewborg.map.types import Room
from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode, ModeParams

# Within this distance² (world px) of a station / waypoint we count as "arrived".
ARRIVE_RADIUS_SQ = 24**2
# One task-time hold (≈ the 72-tick task progress in sim.nim).
TASK_TICKS = 72


class PretendMode(Mode[Belief, ActionState, Intent]):
    name = "pretend"
    params_type = EmptyModeParams

    def __init__(self, params: ModeParams | None = None) -> None:
        super().__init__(params)
        self._state: str | None = None  # None ⇒ needs DISPATCH
        self._target_id: int | None = None  # the crewmate being followed / recovered
        self._goto_point: ic.Point | None = None  # current wander destination
        self._room_cursor: int = 0  # round-robin index over rooms
        self._task_station: ic.Point | None = None
        self._hold_until: int | None = None

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        self_xy = ic.self_xy(belief)
        if self_xy is None:
            return Intent(kind="idle", reason="no self position")  # camera not up yet
        if self._state is None:
            self._dispatch(belief, self_xy)
        return self._act(belief, self_xy)

    # --- state routing --------------------------------------------------------

    def _act(self, belief: Belief, self_xy: ic.Point) -> Intent:
        if self._state == "follow":
            return self._follow(belief, self_xy)
        if self._state == "recover":
            return self._recover(belief, self_xy)
        if self._state == "goto_room":
            return self._goto_room(belief, self_xy)
        if self._state == "do_task":
            return self._do_task(belief, self_xy)
        return Intent(kind="idle", reason="no behaviour")  # degenerate (no map)

    def _dispatch(self, belief: Belief, self_xy: ic.Point) -> None:
        """Choose the next behaviour: follow the nearest visible crewmate, else wander."""

        visible = ic.visible_crew(belief)
        if visible:
            target = min(visible, key=lambda e: ic.dist2(self_xy, (e.world_x, e.world_y)))
            self._state, self._target_id = "follow", target.object_id
        else:
            self._state, self._goto_point = "goto_room", None

    # --- states ---------------------------------------------------------------

    def _follow(self, belief: Belief, self_xy: ic.Point) -> Intent:
        target = belief.roster.get(self._target_id) if self._target_id is not None else None
        if target is None or target.last_seen_tick != belief.last_tick:
            self._state = "recover"  # lost sight — go to the last-seen spot
            return self._recover(belief, self_xy)

        target_xy = (target.world_x, target.world_y)
        room = ic.room_containing(belief, self_xy)
        if room is not None and ic.room_containing(belief, target_xy) is room:
            station = _station_in_room(belief, room, self_xy)
            if station is not None:  # non-start room with a station ⇒ fake a task
                self._state, self._task_station, self._hold_until = "do_task", station, None
                return self._do_task(belief, self_xy)
        return Intent(kind="navigate_to", point=target_xy, reason="following a crewmate")

    def _recover(self, belief: Belief, self_xy: ic.Point) -> Intent:
        target = belief.roster.get(self._target_id) if self._target_id is not None else None
        if target is None:
            self._state = None
            self._dispatch(belief, self_xy)
            return self._act(belief, self_xy)
        if target.last_seen_tick == belief.last_tick:  # re-acquired
            self._state = "follow"
            return self._follow(belief, self_xy)
        last_seen = (target.world_x, target.world_y)
        if ic.dist2(self_xy, last_seen) <= ARRIVE_RADIUS_SQ:  # arrived, still gone
            self._state = None
            self._dispatch(belief, self_xy)
            return self._act(belief, self_xy)
        return Intent(kind="navigate_to", point=last_seen, reason="recovering: heading to last-seen spot")

    def _goto_room(self, belief: Belief, self_xy: ic.Point) -> Intent:
        if ic.visible_crew(belief):  # encountered the crew — follow them
            self._state = None
            self._dispatch(belief, self_xy)
            return self._act(belief, self_xy)
        if self._goto_point is None or ic.dist2(self_xy, self._goto_point) <= ARRIVE_RADIUS_SQ:
            self._goto_point = self._next_room_point(belief, self_xy)
        if self._goto_point is None:
            return Intent(kind="idle", reason="no rooms to wander")  # degenerate
        return Intent(kind="navigate_to", point=self._goto_point, reason="wandering to a room")

    def _do_task(self, belief: Belief, self_xy: ic.Point) -> Intent:
        if self._task_station is None:
            self._state = None
            self._dispatch(belief, self_xy)
            return self._act(belief, self_xy)
        if ic.dist2(self_xy, self._task_station) > ARRIVE_RADIUS_SQ:
            return Intent(kind="navigate_to", point=self._task_station, reason="heading to a task station")
        if self._hold_until is None:
            self._hold_until = belief.last_tick + TASK_TICKS
        if belief.last_tick < self._hold_until:
            return Intent(kind="idle", reason="faking a task")
        self._state = None  # hold complete — re-dispatch
        self._dispatch(belief, self_xy)
        return self._act(belief, self_xy)

    def _next_room_point(self, belief: Belief, self_xy: ic.Point) -> ic.Point | None:
        """Round-robin to the next room that isn't the one we're standing in."""

        rooms = belief.map.rooms if belief.map is not None else ()
        if not rooms:
            return None
        current = ic.room_containing(belief, self_xy)
        for _ in range(len(rooms)):
            self._room_cursor = (self._room_cursor + 1) % len(rooms)
            room = rooms[self._room_cursor]
            if current is None or room.name != current.name:
                return ic.reachable_point(belief, (room.center.x, room.center.y))
        return None  # only one room, and we are in it


def _station_in_room(belief: Belief, room: Room, self_xy: ic.Point) -> ic.Point | None:
    """The nearest task station inside ``room``, or ``None`` if the start room / none."""

    start = ic.starting_room(belief)
    if start is not None and room.name == start.name:
        return None
    tasks = belief.map.tasks if belief.map is not None else ()
    indices = [i for i in range(len(tasks)) if ic.in_rect((tasks[i].center.x, tasks[i].center.y), room)]
    if not indices:
        return None
    nearest = min(indices, key=lambda i: ic.dist2(self_xy, (tasks[i].center.x, tasks[i].center.y)))
    return ic.task_point(belief, nearest)
