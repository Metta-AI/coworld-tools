"""Resolve the scene tables into a structured :class:`ResolvedScene` (design §4).

Joins each object to its sprite's label, converts camera-relative coordinates to
world coordinates, and classifies entities by ``(label, object-id range)``. No
pixels are read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from players.crewrift.crewborg.perception.constants import (
    BODY_OBJECT_BASE,
    LABEL_GHOST_ICON,
    LABEL_IMPOSTER_ICON,
    LABEL_IMPOSTER_ICON_COOLDOWN,
    LABEL_TASK_ARROW,
    LABEL_TASK_BUBBLE,
    LABEL_VOTE_CURSOR,
    LABEL_VOTE_SKIP_CURSOR,
    LABEL_VOTE_TIMER,
    MAX_PLAYERS,
    PHASE_TEXTS,
    PLAYER_OBJECT_BASE,
    VOTE_SKIP_DOT_OBJECT_BASE,
    PREFIX_BODY,
    PREFIX_PLAYER,
    PREFIX_PROGRESS_BAR,
    PREFIX_TASK_COUNTER,
    PREFIX_VOTE_DOT,
    PREFIX_VOTE_SELF_MARKER,
    TASK_ARROW_OBJECT_BASE,
    TASK_BUBBLE_OBJECT_BASE,
    VOTE_DOT_OBJECT_BASE,
)
from players.crewrift.crewborg.perception.entities import (
    SKIP_VOTE_TARGET,
    ResolvedScene,
    TaskSignal,
    VisibleBody,
    VisiblePlayer,
    VoteDot,
    VotingState,
)

if TYPE_CHECKING:
    from players.crewrift.crewborg.coworld.scene import SceneState


def _parse_color_and_facing(text: str) -> tuple[str, str]:
    """Split ``"<color> left|right"`` into ``(color, facing)``."""

    color, _, facing = text.rpartition(" ")
    return color, facing


def _parse_trailing_int(text: str) -> int | None:
    """Parse the trailing run of digits from a label suffix (e.g. ``"45%"``)."""

    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


def resolve_scene(scene: SceneState, tick: int) -> ResolvedScene:
    """Build the resolved view for this tick from the current scene tables."""

    camera_x = scene.camera_x
    camera_y = scene.camera_y

    self_role: str | None = None
    self_kill_ready: bool | None = None
    players: list[VisiblePlayer] = []
    bodies: list[VisibleBody] = []
    tasks: list[TaskSignal] = []
    dots: list[VoteDot] = []
    active_progress: int | None = None
    crew_remaining: int | None = None
    phase_texts: set[str] = set()
    cursor = skip_cursor = timer = False
    self_marker_color: str | None = None

    for object_id, obj in scene.objects.items():
        sprite = scene.sprites.get(obj.sprite_id)
        if sprite is None:
            continue
        label = sprite.label
        world_x = obj.x + camera_x
        world_y = obj.y + camera_y

        # HUD self-role icons (their object ids are not in the entity ranges).
        if label == LABEL_IMPOSTER_ICON:
            self_role, self_kill_ready = "imposter", True
            continue
        if label == LABEL_IMPOSTER_ICON_COOLDOWN:
            self_role, self_kill_ready = "imposter", False
            continue
        if label == LABEL_GHOST_ICON:
            self_role = "dead"
            continue

        if label == LABEL_VOTE_CURSOR:
            cursor = True
        elif label == LABEL_VOTE_SKIP_CURSOR:
            skip_cursor = True
        elif label == LABEL_VOTE_TIMER:
            timer = True
        elif label.startswith(PREFIX_VOTE_SELF_MARKER):
            self_marker_color = label[len(PREFIX_VOTE_SELF_MARKER) :]
        elif label.startswith(PREFIX_PROGRESS_BAR):
            active_progress = _parse_trailing_int(label[len(PREFIX_PROGRESS_BAR) :])
        elif label.startswith(PREFIX_TASK_COUNTER):
            crew_remaining = _parse_trailing_int(label[len(PREFIX_TASK_COUNTER) :])
        elif label in PHASE_TEXTS:
            phase_texts.add(label)

        # Entities, classified by both id range and label.
        if PLAYER_OBJECT_BASE <= object_id < BODY_OBJECT_BASE and label.startswith(PREFIX_PLAYER):
            color, facing = _parse_color_and_facing(label[len(PREFIX_PLAYER) :])
            if facing in ("left", "right"):
                players.append(
                    VisiblePlayer(
                        object_id=object_id, color=color, facing=facing, world_x=world_x, world_y=world_y
                    )
                )
        elif BODY_OBJECT_BASE <= object_id < TASK_BUBBLE_OBJECT_BASE and label.startswith(PREFIX_BODY):
            bodies.append(
                VisibleBody(
                    object_id=object_id, color=label[len(PREFIX_BODY) :], world_x=world_x, world_y=world_y
                )
            )
        elif TASK_BUBBLE_OBJECT_BASE <= object_id < TASK_ARROW_OBJECT_BASE and label == LABEL_TASK_BUBBLE:
            tasks.append(
                TaskSignal(
                    task_index=object_id - TASK_BUBBLE_OBJECT_BASE,
                    kind="bubble",
                    world=(world_x, world_y),
                    screen=(obj.x, obj.y),
                )
            )
        elif TASK_ARROW_OBJECT_BASE <= object_id < VOTE_DOT_OBJECT_BASE and label == LABEL_TASK_ARROW:
            tasks.append(
                TaskSignal(
                    task_index=object_id - TASK_ARROW_OBJECT_BASE,
                    kind="arrow",
                    world=None,
                    screen=(obj.x, obj.y),
                )
            )
        elif (
            VOTE_DOT_OBJECT_BASE <= object_id < VOTE_DOT_OBJECT_BASE + MAX_PLAYERS * MAX_PLAYERS
            and label.startswith(PREFIX_VOTE_DOT)
        ):
            rel = object_id - VOTE_DOT_OBJECT_BASE
            dots.append(VoteDot(target=rel // MAX_PLAYERS, voter=rel % MAX_PLAYERS))
        elif (
            VOTE_SKIP_DOT_OBJECT_BASE <= object_id < VOTE_SKIP_DOT_OBJECT_BASE + MAX_PLAYERS
            and label.startswith(PREFIX_VOTE_DOT)
        ):
            # Skip votes share the "vote dot" sprite but a separate id range.
            dots.append(VoteDot(target=SKIP_VOTE_TARGET, voter=object_id - VOTE_SKIP_DOT_OBJECT_BASE))

    return ResolvedScene(
        tick=tick,
        camera_ready=scene.camera_ready,
        camera_x=camera_x,
        camera_y=camera_y,
        self_role=self_role,
        self_kill_ready=self_kill_ready,
        visible_players=tuple(players),
        visible_bodies=tuple(bodies),
        task_signals=tuple(tasks),
        active_task_progress_pct=active_progress,
        crew_tasks_remaining=crew_remaining,
        voting=VotingState(
            cursor_present=cursor,
            skip_cursor_present=skip_cursor,
            timer_present=timer,
            self_marker_color=self_marker_color,
            dots=tuple(dots),
        ),
        phase_texts=frozenset(phase_texts),
    )
