"""Crewborg's SDK type parameters and the three pure perception functions.

Crewborg supplies the six ``AgentRuntime`` type parameters
(``Observation``/``Percept``/``Belief``/``ActionState``/``Intent``/``Command``)
plus ``perceive``/``update_belief`` here, and ``resolve_action`` in
:mod:`players.crewrift.crewborg.action`. See ``design.md`` §2.

Style (design §2): SDK-facing types are pydantic models — frozen where the value
is immutable (``Percept``/``Intent``/``Command``), mutable where the loop folds
state in place (``Belief``/``ActionState``). ``SceneState`` is the lone exception:
a plain dataclass owned by the bridge (see :mod:`.coworld.policy_player`) holding
raw buffers that never reach the strategy.

**P0 scope.** This phase wires the idle policy end-to-end. The percept/belief
carry only the bookkeeping needed to prove the loop runs; the entity arrays, map,
roster, voting, etc. described in design §4–§5 land in P1+.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from players.crewrift.crewborg.coworld.scene import SceneState

# The shared intent vocabulary (design §8). One vocabulary serves both roles;
# modes differ only in which kinds they emit. P0 only emits/handles ``idle``.
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


class Observation(BaseModel):
    """Thin frozen wrapper holding a reference to the bridge's live scene + tick.

    Byte-level decoding happens in the bridge; ``perceive`` does interpretation
    only (design §3). ``arbitrary_types_allowed`` lets us hold the plain-dataclass
    ``SceneState`` by reference without copying its buffers.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scene: SceneState
    tick: int


class Percept(BaseModel):
    """Resolved per-tick view of the scene (design §4).

    P0 carries only loop bookkeeping. Entity arrays, HUD, and phase signals are
    added in P1 once the Sprite-v1 decoder exists.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tick: int
    scene_tick: int
    messages_applied: int


class Belief(BaseModel):
    """Persistent world model — the only interface the strategy and modes see.

    P0 carries only loop bookkeeping. The self/map/roster/tasks/phase/voting
    sections in design §5 are added in later phases.
    """

    model_config = ConfigDict(extra="forbid")

    last_tick: int = 0
    ticks_observed: int = 0
    messages_applied: int = 0


class ActionState(BaseModel):
    """Action-layer execution state, mutated in place across ticks (design §9).

    P0 only tracks the last desired button mask; the nav route, A-press FSM, and
    chat buffer arrive with the action layer in P2+.
    """

    model_config = ConfigDict(extra="forbid")

    held_mask: int = 0


class Intent(BaseModel):
    """Symbolic "what to do now" (design §8).

    A single frozen shape carries every intent kind; unused carry fields stay
    ``None``. P0 only ever emits ``idle``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: IntentKind = "idle"
    point: tuple[int, int] | None = None
    target_id: int | None = None
    task_index: int | None = None
    text: str | None = None
    reason: str = ""


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


def perceive(observation: Observation, tick: int) -> Percept:
    """Interpret the live scene into a frozen per-tick percept.

    P0 reads only the bridge's bookkeeping counters. P1 replaces this with the
    Sprite-v1 object/label/coordinate resolution described in design §4.
    """

    scene = observation.scene
    return Percept(
        tick=tick,
        scene_tick=scene.tick,
        messages_applied=scene.messages_applied,
    )


def update_belief(belief: Belief, percept: Percept) -> None:
    """Fold the percept into belief in place (design §5)."""

    belief.last_tick = percept.tick
    belief.ticks_observed += 1
    belief.messages_applied = percept.messages_applied
