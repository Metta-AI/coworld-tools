"""Crewborg's SDK type parameters and the three pure perception functions.

Crewborg supplies the six ``AgentRuntime`` type parameters
(``Observation``/``Percept``/``Belief``/``ActionState``/``Intent``/``Command``)
plus ``perceive``/``update_belief`` here, and ``resolve_action`` in
:mod:`players.crewrift.crewborg.action`. See ``design.md`` §2.

Style (design §2): SDK-facing types are pydantic models — frozen where the value
is immutable (``Percept``/``Intent``/``Command``), mutable where the loop folds
state in place (``Belief``/``ActionState``). ``SceneState`` is the lone exception:
a plain dataclass owned by the bridge holding raw buffers that never reach the
strategy.

**P2 scope.** ``perceive`` resolves the scene into a structured
:class:`~.perception.entities.ResolvedScene` (including self world position), and
``update_belief`` folds it into belief's self / roster / bodies / tasks / phase /
voting sections and builds the nav grid once from the walkability mask
(design §4-§6). The crewmate Normal mode + action layer drive task completion;
meetings/report/flee (P3) and imposter behaviour (P4) are still to come.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from players.crewrift.crewborg.coworld.scene import SceneState
from players.crewrift.crewborg.map.types import MapData
from players.crewrift.crewborg.nav import NavGrid, build_nav_grid
from players.crewrift.crewborg.perception.entities import ResolvedScene, VotingState
from players.crewrift.crewborg.perception.resolve import resolve_scene

# The shared intent vocabulary (design §8). One vocabulary serves both roles;
# modes differ only in which they emit. P1 still only emits/handles ``idle``.
IntentKind = Literal[
    "idle",
    "loiter",
    "navigate_to",
    "flee_from",
    "complete_task",
    "report",
    "vote",
    "chat",
    "kill",
    "vent",
]

# Game phases (sim.nim phase machine). ``unknown`` until the first phase signal.
Phase = Literal["unknown", "Lobby", "RoleReveal", "Playing", "Voting", "VoteResult", "GameOver"]


class Observation(BaseModel):
    """Thin frozen wrapper holding a reference to the bridge's live scene + tick.

    Byte-level decoding happens in the bridge; ``perceive`` does interpretation
    only (design §3).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scene: SceneState
    tick: int


class Percept(BaseModel):
    """Resolved per-tick view of the scene (design §4).

    ``walkability`` is the decoded mask held by reference (not copied): it is
    static for the episode, so ``update_belief`` builds the nav grid from it once.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    tick: int
    messages_applied: int
    resolved: ResolvedScene
    walkability: np.ndarray | None = None


class RosterEntry(BaseModel):
    """Last-known state of one player object (design §5 roster)."""

    model_config = ConfigDict(extra="forbid")

    object_id: int
    color: str
    facing: str
    world_x: int
    world_y: int
    last_seen_tick: int


class BodyEntry(BaseModel):
    """A dead body the agent has seen (design §5 bodies)."""

    model_config = ConfigDict(extra="forbid")

    object_id: int
    color: str
    world_x: int
    world_y: int
    first_seen_tick: int


class Belief(BaseModel):
    """Persistent world model — the only interface the strategy and modes see."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # Loop bookkeeping.
    last_tick: int = 0
    ticks_observed: int = 0
    messages_applied: int = 0

    # Static map, baked once at startup (design §6).
    map: MapData | None = None
    # Navigation grid over the streamed walkability mask, built once (design §6).
    nav: NavGrid | None = None

    # Self / camera (design §5 self).
    camera_ready: bool = False
    camera_x: int = 0
    camera_y: int = 0
    self_role: str | None = None
    self_kill_ready: bool | None = None
    self_world_x: int | None = None
    self_world_y: int | None = None

    # Tasks (design §5 tasks).
    assigned_task_indices: set[int] = Field(default_factory=set)
    visible_task_indices: set[int] = Field(default_factory=set)
    completed_task_indices: set[int] = Field(default_factory=set)
    crew_tasks_remaining: int | None = None
    active_task_progress_pct: int | None = None

    # Roster + bodies (design §5).
    roster: dict[int, RosterEntry] = Field(default_factory=dict)
    total_player_count: int = 0
    bodies: dict[int, BodyEntry] = Field(default_factory=dict)

    # Phase machine (design §5 phase).
    phase: Phase = "unknown"
    phase_start_tick: int = 0

    # Voting (design §5 voting).
    voting: VotingState = Field(default_factory=VotingState)


class Intent(BaseModel):
    """Symbolic "what to do now" (design §8). P2 emits idle/navigate_to/complete_task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: IntentKind = "idle"
    point: tuple[int, int] | None = None
    target_id: int | None = None
    task_index: int | None = None
    text: str | None = None
    reason: str = ""


class ActionState(BaseModel):
    """Action-layer execution state, mutated in place across ticks (design §9)."""

    model_config = ConfigDict(extra="forbid")

    held_mask: int = 0
    # The intent currently being executed, for diffing against the next tick's.
    current_intent: Intent | None = None
    # Active nav route (world waypoints) + cursor to the next unreached waypoint.
    route: list[tuple[int, int]] = Field(default_factory=list)
    route_cursor: int = 0
    route_goal: tuple[int, int] | None = None
    # Last observed self world position, for estimating velocity (predictive stop).
    last_self_x: int | None = None
    last_self_y: int | None = None


class Command(BaseModel):
    """Per-tick wire payload (design §9).

    ``held_mask`` is the button bitmask the action layer wants held this tick; the
    bridge owns the last-sent mask and the send-only-on-change comparison
    (design §3.3). ``chat`` is reserved for meeting speech (emitted only during
    Voting); chat emission lands in P3.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    held_mask: int = 0
    chat: str | None = None


def derive_phase(resolved: ResolvedScene, current: Phase) -> Phase:
    """Advance the phase machine from interstitial text + voting + scene signals.

    Explicit interstitial text and the voting UI pin the transitional phases. The
    subtlety (design §5) is ``Playing``: during ordinary play there is usually *no*
    interstitial and no voting UI, so the machine must infer ``Playing`` from a
    live scene once a reveal/meeting clears — otherwise belief stays stuck at
    ``RoleReveal`` and P2's Normal mode (keyed on ``Playing``) never activates.
    """

    texts = resolved.phase_texts
    if texts & {"DRAW", "CREW WINS", "IMPS WIN"}:
        return "GameOver"
    if texts & {"IMPS", "CREWMATE"}:
        return "RoleReveal"
    if texts & {"WAITING", "NEED MORE!", "STARTING"}:
        return "Lobby"
    if texts & {"NO ONE", "WAS KILLED"}:
        return "VoteResult"
    if resolved.voting.active or "SKIP" in texts:
        return "Voting"

    # No transitional signal. Infer Playing from a live scene: when a reveal /
    # meeting has just cleared, or (for a mid-game join) when Playing-specific
    # signals — the crew task counter or task bubbles — are present.
    if not resolved.camera_ready:
        return current
    if current in ("RoleReveal", "VoteResult", "Voting", "Playing"):
        return "Playing"
    if resolved.crew_tasks_remaining is not None or resolved.task_signals:
        return "Playing"
    return current


def perceive(observation: Observation, tick: int) -> Percept:
    """Resolve the live scene into a frozen per-tick percept (design §4)."""

    scene = observation.scene
    return Percept(
        tick=tick,
        messages_applied=scene.messages_applied,
        resolved=resolve_scene(scene, tick),
        walkability=scene.walkability,
    )


def update_belief(belief: Belief, percept: Percept) -> None:
    """Fold the percept into belief in place (design §5)."""

    resolved = percept.resolved
    belief.last_tick = percept.tick
    belief.ticks_observed += 1
    belief.messages_applied = percept.messages_applied

    belief.camera_ready = resolved.camera_ready
    belief.camera_x = resolved.camera_x
    belief.camera_y = resolved.camera_y
    belief.self_world_x = resolved.self_world_x
    belief.self_world_y = resolved.self_world_y

    # Build the navigation grid once from the static walkability mask (design §6).
    if belief.nav is None and percept.walkability is not None:
        width = belief.map.width if belief.map is not None else None
        height = belief.map.height if belief.map is not None else None
        belief.nav = build_nav_grid(percept.walkability, map_width=width, map_height=height)

    # Tasks. The renderer emits a signal per incomplete assigned task. We only
    # accumulate which tasks are assigned and which are visible this tick;
    # completion is concluded by Normal mode (which knows the task it is standing
    # on), since a task also leaves the visible set merely by going off-screen.
    belief.visible_task_indices = {signal.task_index for signal in resolved.task_signals}
    belief.assigned_task_indices |= belief.visible_task_indices
    if resolved.crew_tasks_remaining is not None:
        belief.crew_tasks_remaining = resolved.crew_tasks_remaining
    belief.active_task_progress_pct = resolved.active_task_progress_pct

    for player in resolved.visible_players:
        belief.roster[player.object_id] = RosterEntry(
            object_id=player.object_id,
            color=player.color,
            facing=player.facing,
            world_x=player.world_x,
            world_y=player.world_y,
            last_seen_tick=percept.tick,
        )
    # The roster spawns co-located at the first Playing tick, so the distinct
    # ids seen so far estimate the full player count (design §5).
    belief.total_player_count = max(belief.total_player_count, len(belief.roster))

    for body in resolved.visible_bodies:
        if body.object_id not in belief.bodies:
            belief.bodies[body.object_id] = BodyEntry(
                object_id=body.object_id,
                color=body.color,
                world_x=body.world_x,
                world_y=body.world_y,
                first_seen_tick=percept.tick,
            )

    phase = derive_phase(resolved, belief.phase)
    if phase != belief.phase:
        belief.phase = phase
        belief.phase_start_tick = percept.tick

    # Self role/state (design §4-§5). The HUD shows an imposter/ghost icon for
    # those roles; an alive crewmate has neither, so once we know we are Playing
    # and no such marker is present, the role is crewmate. Role is fixed for the
    # game (a crewmate only changes to "dead" on death, via the ghost icon).
    if resolved.self_role is not None:
        belief.self_role = resolved.self_role
        belief.self_kill_ready = resolved.self_kill_ready
    elif belief.self_role is None and belief.phase == "Playing":
        belief.self_role = "crewmate"

    belief.voting = resolved.voting
