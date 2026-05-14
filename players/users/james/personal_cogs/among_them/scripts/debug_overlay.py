"""Deprecated visual debug overlay for modulabot perception.

This script belongs to the deprecated local modulabot. Do not use it for
active guided_bot work unless James explicitly asks for modulabot.

Runs the full :mod:`modulabot.perception.pixel_pipeline` on captured
frames (``.npy`` array of ``(N, 128, 128)`` uint8 frames) and shows
both the raw frame and what the agent *believes* about it:

- Detected crewmate / body / ghost / task-icon / radar sprite matches
  (colour-coded outlines).
- **Projected task positions** from ``game_map.tasks`` via the current
  camera lock — this is the diagnostic for world→screen projection
  bugs. A task with an expected on-screen position but no icon match
  shows as a dim yellow box; matched ones are solid green.
- **Voting-screen slots** with colour-tint labels and cursor highlight
  when the parser thinks we're on the voting screen.
- **Velocity arrow** from screen centre so you can see whether the
  motion tracker is reading actual camera drift.
- **Info panel** with every relevant field from ``bot.percep``,
  ``bot.motion``, ``bot.voting`` — the same numbers the policy layer
  consumes.

Usage:

    # Interactive scrubber (←/→ or j/k to step, g<N> jumps to frame)
    PYTHONPATH=. python scripts/debug_overlay.py fixtures.npy --watch

    # Static render of one frame
    PYTHONPATH=. python scripts/debug_overlay.py fixtures.npy \\
        --frame 150 --save /tmp/overlay.png

    # Render a range to PNGs
    PYTHONPATH=. python scripts/debug_overlay.py fixtures.npy \\
        --range 120:180 --outdir /tmp/overlay_range

    # Plain text summary for the whole capture
    PYTHONPATH=. python scripts/debug_overlay.py fixtures.npy --summary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from _lib import setup_pythonpath

setup_pythonpath()

from modulabot.bot import BotCore  # noqa: E402
from modulabot.data import (  # noqa: E402
    PICO8_PALETTE,
    PLAYER_COLORS,
    PLAYER_COLOR_NAMES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPRITE_SIZE,
    load_reference_data,
)
from modulabot.frame import looks_like_interstitial  # noqa: E402
from modulabot.geometry import (  # noqa: E402
    PLAYER_SCREEN_X,
    PLAYER_SCREEN_Y,
    player_world_x,
    player_world_y,
)
from modulabot.localize import Localizer  # noqa: E402
from modulabot.state import Bot, Phase, Role  # noqa: E402
from modulabot.voting import VOTE_CELL_H, VOTE_CELL_W, vote_cell_origin  # noqa: E402


# ---------------------------------------------------------------------------
# Colour palette for overlay annotations (distinct from PICO-8 for clarity).
# ---------------------------------------------------------------------------

C_CREWMATE = (32, 128, 255)  # detected other-player sprite
C_BODY = (255, 32, 32)
C_GHOST = (32, 255, 96)
C_TASK_ICON_MATCHED = (96, 255, 96)  # icon in view AND matched by scan
C_TASK_ICON_EXPECTED = (255, 224, 0)  # projected but unmatched ("we should see an icon here")
C_TASK_ARROW = (255, 160, 32)  # off-screen task, drawn as edge arrow
C_RADAR = (255, 64, 255)
C_PLAYER_CENTRE = (0, 224, 255)
C_VELOCITY = (0, 255, 200)
C_VOTE_CURSOR = (255, 255, 255)
C_VOTE_SELF = (255, 200, 0)
C_GOAL = (255, 96, 255)
C_GOAL_WORLD = (255, 64, 200)  # goal projected from world coords
C_PATH = (64, 224, 255)  # A* path waypoints
C_INFO_BG = (24, 24, 32)
C_INFO_FG = (220, 220, 220)
C_INFO_HEAD = (255, 255, 140)
C_INFO_DIM = (140, 140, 160)


# ---------------------------------------------------------------------------
# Perception drivers
# ---------------------------------------------------------------------------


class Scrubber:
    """Replays a frame sequence through the **full** BotCore pipeline.

    Holds one :class:`~modulabot.bot.BotCore` across the whole
    sequence — same as a live agent — so perception, motion tracking,
    policy dispatch, goal setting, A\\* pathfinding, and trace state
    all evolve exactly the way they did (or would) during live play.

    Earlier versions only ran perception + motion here; the overlay
    couldn't render goals or pathfinding because nothing was calling
    the policies. Using ``BotCore.step`` guarantees the overlay
    reflects the same decisions the live bot would make on this
    frame sequence.

    Stepping backward re-seeds from frame 0 and replays forward to
    the target frame so later frames always see a plausibly-past
    perception, not a random reset. Cached per-frame so scrubbing
    back and forth is O(1) after the first visit.
    """

    def __init__(self, frames: np.ndarray, data) -> None:
        self.frames = frames
        self.data = data
        self._replay_cache: dict[int, "FrameSnapshot"] = {}
        self._reset()

    def _reset(self) -> None:
        self.core = BotCore(agent_id=0, reference_data=self.data)
        self._next_index = 0

    @property
    def bot(self) -> Bot:
        # Surface the underlying bot for callers that still want read-only
        # access (tests, future instrumentation).
        return self.core.bot

    @property
    def localizer(self) -> Localizer:
        return self.core._localizer  # type: ignore[attr-defined]

    def snapshot_for(self, index: int) -> "FrameSnapshot":
        """Return the FrameSnapshot for frame ``index``.

        Replays forward from the current state if possible; resets and
        replays from zero otherwise. Cached so scrubbing backward is
        O(1) once a frame has been rendered.
        """
        if index < 0 or index >= len(self.frames):
            raise IndexError(index)
        if index in self._replay_cache:
            return self._replay_cache[index]
        if index < self._next_index:
            self._reset()
        while self._next_index <= index:
            snap = self._step_once(self._next_index)
            self._replay_cache[self._next_index] = snap
            self._next_index += 1
        return self._replay_cache[index]

    def _step_once(self, index: int) -> "FrameSnapshot":
        frame = self.frames[index]
        # Feed the frame as a stacked observation (frame_stack=4) —
        # BotCore.step expects the same shape cogames delivers. We
        # broadcast the single captured frame to fill the stack; the
        # pipeline only ever reads the most recent frame anyway.
        observation = np.broadcast_to(frame, (4, *frame.shape)).astype(np.uint8)
        self.core.step(observation)
        # Snapshot post-step: goal, path, motion, decision are all
        # populated at this point.
        return FrameSnapshot.from_bot(self.core.bot, frame)


class FrameSnapshot:
    """Immutable per-frame snapshot of the bot fields the overlay uses.

    We don't deep-copy :class:`~modulabot.state.Bot` every frame
    because it's large and the overlay only reads a few fields.
    Snapshots store the subset as plain values so the scrubber cache
    doesn't pin mutable state that'll drift as we step further.
    """

    __slots__ = (
        "frame",
        "phase",
        "role",
        "is_ghost",
        "interstitial",
        "self_color",
        "tick",
        "camera_x",
        "camera_y",
        "camera_score",
        "camera_lock",
        "localized",
        "visible_crewmates",
        "visible_bodies",
        "visible_ghosts",
        "visible_task_icons",
        "radar_dots",
        "players",
        "bodies",
        "tasks",
        "voting",
        "motion_velocity",
        "motion_stuck",
        "motion_jiggle",
        "goal_has",
        "goal_x",
        "goal_y",
        "goal_name",
        "goal_has_world",
        "goal_world_x",
        "goal_world_y",
        "goal_has_path_step",
        "goal_path_step_x",
        "goal_path_step_y",
        "goal_path",
        "goal_path_plan_tick",
        "branch_id",
        "intent",
    )

    @classmethod
    def from_bot(cls, bot: Bot, frame: np.ndarray) -> "FrameSnapshot":
        s = cls.__new__(cls)
        s.frame = frame.copy()
        p = bot.percep
        s.phase = p.phase
        s.role = bot.role
        s.is_ghost = bot.is_ghost
        s.interstitial = p.interstitial
        s.self_color = bot.identity.self_color
        s.tick = bot.tick
        s.camera_x = p.camera_x
        s.camera_y = p.camera_y
        s.camera_score = p.camera_score
        s.camera_lock = p.camera_lock
        s.localized = p.localized
        # Shallow-copy the match lists (small dataclasses).
        s.visible_crewmates = list(p.visible_crewmates)
        s.visible_bodies = list(p.visible_bodies)
        s.visible_ghosts = list(p.visible_ghosts)
        s.visible_task_icons = list(p.visible_task_icons)
        s.radar_dots = list(p.radar_dots)
        s.players = list(p.players)
        s.bodies = list(p.bodies)
        s.tasks = list(p.tasks)
        v = bot.voting
        s.voting = {
            "active": v.active,
            "player_count": v.player_count,
            "cursor": v.cursor,
            "self_slot": v.self_slot,
            "target_slot": v.target_slot,
            "chat_sus_color": v.chat_sus_color,
            "chat_text": v.chat_text,
            "chat_lines": [
                (line.speaker_color, line.y, line.text) for line in v.chat_lines
            ],
            "slots": [(slot.color_index, slot.alive) for slot in v.slots],
        }
        s.motion_velocity = (bot.motion.velocity_x, bot.motion.velocity_y)
        s.motion_stuck = bot.motion.stuck_ticks
        s.motion_jiggle = bot.motion.jiggle_ticks
        s.goal_has = bot.goal.has
        s.goal_x = bot.goal.x
        s.goal_y = bot.goal.y
        s.goal_name = bot.goal.name
        s.goal_has_world = bot.goal.has_world
        s.goal_world_x = bot.goal.world_x
        s.goal_world_y = bot.goal.world_y
        s.goal_has_path_step = bot.goal.has_path_step
        s.goal_path_step_x = bot.goal.path_step_x
        s.goal_path_step_y = bot.goal.path_step_y
        # Keep a shallow copy of the path (PathStep is immutable ints).
        s.goal_path = list(bot.goal.path)
        s.goal_path_plan_tick = bot.goal.path_plan_tick
        s.branch_id = bot.diag.branch_id
        s.intent = bot.diag.intent
        return s


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def frame_to_rgb(frame: np.ndarray) -> np.ndarray:
    return PICO8_PALETTE[frame]


def render_raw(frame: np.ndarray, scale: int = 4) -> Image.Image:
    rgb = frame_to_rgb(frame)
    img = Image.fromarray(rgb)
    return img.resize(
        (frame.shape[1] * scale, frame.shape[0] * scale), Image.NEAREST
    )


def _tint_rgb(color_index: int) -> tuple[int, int, int]:
    """RGB for a player tint colour index. Returns grey for unknown."""
    if 0 <= color_index < len(PLAYER_COLORS):
        palette_idx = int(PLAYER_COLORS[color_index])
        return tuple(int(c) for c in PICO8_PALETTE[palette_idx])
    return (160, 160, 160)


def render_overlay(snap: FrameSnapshot, data, scale: int = 4) -> Image.Image:
    """Render the frame with every perception annotation on top.

    Starts from a dimmed copy of the raw frame so the annotation
    strokes (brighter, saturated colours) pop against the
    busy map art.
    """
    # Dim the base so overlay strokes stand out.
    rgb = frame_to_rgb(snap.frame).astype(np.int16)
    rgb = (rgb * 55 // 100).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(rgb).resize(
        (snap.frame.shape[1] * scale, snap.frame.shape[0] * scale),
        Image.NEAREST,
    )
    draw = ImageDraw.Draw(img, "RGBA")
    font = _load_font(10)

    def box(x, y, w, h, colour, label=None, width=2, fill=None):
        x0, y0 = x * scale, y * scale
        x1, y1 = (x + w) * scale - 1, (y + h) * scale - 1
        if fill is not None:
            draw.rectangle([x0, y0, x1, y1], fill=fill)
        draw.rectangle([x0, y0, x1, y1], outline=colour, width=width)
        if label:
            # Cheap text-outline for readability on any background:
            # paint in black behind the coloured label.
            lx, ly = x0 + 2, max(0, y0 - 13)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                draw.text((lx + dx, ly + dy), label, fill=(0, 0, 0), font=font)
            draw.text((lx, ly), label, fill=colour, font=font)

    def cross(x, y, colour, r=4, width=2):
        cx = x * scale + scale // 2
        cy = y * scale + scale // 2
        draw.line([cx - r, cy, cx + r, cy], fill=colour, width=width)
        draw.line([cx, cy - r, cx, cy + r], fill=colour, width=width)

    # --- 1. Raw pixel-sprite matches ----------------------------------
    for cm in snap.visible_crewmates:
        label = f"c{cm.color_index}" if cm.color_index >= 0 else "c?"
        if cm.flip_h:
            label += "←"
        box(cm.x, cm.y, SPRITE_SIZE, SPRITE_SIZE, C_CREWMATE, label)
        # Small tint-colour swatch inside the box so the colour index is
        # visually verifiable against the sprite on-frame.
        tint = _tint_rgb(cm.color_index)
        draw.rectangle(
            [
                cm.x * scale + 2,
                cm.y * scale + 2,
                cm.x * scale + 6,
                cm.y * scale + 6,
            ],
            fill=tint,
            outline=(0, 0, 0),
        )

    for b in snap.visible_bodies:
        label = f"b{b.color_index}" if b.color_index >= 0 else "body"
        box(b.x, b.y, SPRITE_SIZE, SPRITE_SIZE, C_BODY, label)

    for g in snap.visible_ghosts:
        label = "ghost←" if g.flip_h else "ghost"
        box(g.x, g.y, SPRITE_SIZE, SPRITE_SIZE, C_GHOST, label)

    for icon in snap.visible_task_icons:
        box(icon.x, icon.y, SPRITE_SIZE, SPRITE_SIZE, C_TASK_ICON_MATCHED, "icon")

    for rd in snap.radar_dots:
        cross(rd.x, rd.y, C_RADAR, r=2)

    # --- 2. Projected task positions (world → screen via camera) ------
    # This is the key diagnostic for "are we steering at the right
    # pixel?". Every task from ``game_map`` gets painted at its
    # projected screen coordinate; if the projection is off, the
    # yellow markers won't land on top of the actual icons visible
    # in the frame.
    if snap.localized and snap.phase == Phase.PLAYING:
        for task in data.map.tasks:
            # Match pixel_pipeline._populate_tasks_from_camera: task is
            # on screen when the icon centre falls inside the viewport.
            icon_screen_x = task.cx - snap.camera_x
            icon_screen_y = task.y - snap.camera_y
            on_screen = (
                0 <= icon_screen_x < SCREEN_WIDTH
                and 0 <= icon_screen_y < SCREEN_HEIGHT
            )
            if on_screen:
                # Did we match an icon near this position? (mirror the
                # 10-px tolerance in the adapter)
                matched = any(
                    abs(m.x + 6 - icon_screen_x) <= 10
                    and abs(m.y + 6 - icon_screen_y) <= 10
                    for m in snap.visible_task_icons
                )
                colour = C_TASK_ICON_MATCHED if matched else C_TASK_ICON_EXPECTED
                # Draw a small cross at the projected icon centre.
                cross(icon_screen_x, icon_screen_y, colour, r=4)
                draw.text(
                    (icon_screen_x * scale + 6, icon_screen_y * scale + 4),
                    f"#{task.index}",
                    fill=colour,
                    font=font,
                )
            else:
                # Off-screen: draw an arrow at the screen edge pointing
                # toward the task so we can see which direction the
                # chase-the-arrow logic would steer.
                cx = max(0, min(SCREEN_WIDTH - 1, icon_screen_x))
                cy = max(0, min(SCREEN_HEIGHT - 1, icon_screen_y))
                cross(cx, cy, C_TASK_ARROW, r=3)

    # --- 3. Player centre + velocity arrow ----------------------------
    cx = PLAYER_SCREEN_X * scale + scale // 2
    cy = PLAYER_SCREEN_Y * scale + scale // 2
    draw.line([cx - 6, cy, cx + 6, cy], fill=C_PLAYER_CENTRE, width=1)
    draw.line([cx, cy - 6, cx, cy + 6], fill=C_PLAYER_CENTRE, width=1)
    vx, vy = snap.motion_velocity
    if vx or vy:
        # Scale velocity arrow by ~4 so sub-pixel motion is visible.
        mag = (vx * vx + vy * vy) ** 0.5
        if mag > 0:
            k = 4 * scale
            draw.line(
                [cx, cy, cx + int(vx * k / max(1, mag) * 2), cy + int(vy * k / max(1, mag) * 2)],
                fill=C_VELOCITY,
                width=2,
            )

    # --- 4. Goal marker + A* path ------------------------------------
    # Goal: draw both the screen-space marker (for trace sanity) and
    # the world-coord goal projected back through the current camera.
    # The A* path (if we have one) is painted as a chain of small
    # dots so you can see "we plan to walk this way" vs what we're
    # actually emitting.
    if snap.goal_has:
        box(snap.goal_x - 2, snap.goal_y - 2, 4, 4, C_GOAL, f"goal {snap.goal_name}")

    if snap.goal_has_world and snap.localized:
        gx = snap.goal_world_x - snap.camera_x
        gy = snap.goal_world_y - snap.camera_y
        if 0 <= gx < SCREEN_WIDTH and 0 <= gy < SCREEN_HEIGHT:
            box(gx - 3, gy - 3, 6, 6, C_GOAL_WORLD, "world")
        # Render the cached A* path — each PathStep is a world
        # coordinate, so project each through the camera.
        if snap.goal_path:
            for step in snap.goal_path[::4]:  # every 4th pixel — cheap
                sx = step.x - snap.camera_x
                sy = step.y - snap.camera_y
                if 0 <= sx < SCREEN_WIDTH and 0 <= sy < SCREEN_HEIGHT:
                    draw.ellipse(
                        [
                            sx * scale - 1,
                            sy * scale - 1,
                            sx * scale + 2,
                            sy * scale + 2,
                        ],
                        outline=C_PATH,
                        fill=C_PATH,
                    )
        # Current lookahead waypoint — prominent diamond.
        if snap.goal_has_path_step:
            wx = snap.goal_path_step_x - snap.camera_x
            wy = snap.goal_path_step_y - snap.camera_y
            if 0 <= wx < SCREEN_WIDTH and 0 <= wy < SCREEN_HEIGHT:
                cx_w = wx * scale + scale // 2
                cy_w = wy * scale + scale // 2
                draw.line(
                    [cx_w, cy_w - 5, cx_w + 5, cy_w, cx_w, cy_w + 5, cx_w - 5, cy_w, cx_w, cy_w - 5],
                    fill=C_PATH,
                    width=2,
                )

    # --- 5. Voting overlay --------------------------------------------
    if snap.phase == Phase.VOTING and snap.voting["player_count"] > 0:
        v = snap.voting
        for i in range(v["player_count"]):
            slot_x, slot_y = vote_cell_origin(v["player_count"], i)
            ci, alive = v["slots"][i]
            tint = _tint_rgb(ci) if alive else (96, 0, 0)
            box(slot_x, slot_y, VOTE_CELL_W, VOTE_CELL_H, tint, label=f"s{i}:{PLAYER_COLOR_NAMES[ci] if 0 <= ci < len(PLAYER_COLOR_NAMES) else '?'}" if alive else f"s{i}:dead", width=1)
        # Cursor highlight
        if v["cursor"] >= 0 and v["cursor"] < v["player_count"]:
            slot_x, slot_y = vote_cell_origin(v["player_count"], v["cursor"])
            box(slot_x - 1, slot_y - 1, VOTE_CELL_W + 2, VOTE_CELL_H + 2, C_VOTE_CURSOR, width=2)
        # Self slot
        if 0 <= v["self_slot"] < v["player_count"]:
            slot_x, slot_y = vote_cell_origin(v["player_count"], v["self_slot"])
            draw.text(
                (slot_x * scale + 2, slot_y * scale - 10),
                "SELF",
                fill=C_VOTE_SELF,
                font=font,
            )

    return img


def render_info_panel(
    snap: FrameSnapshot, index: int, total: int, width: int, height: int
) -> Image.Image:
    """Render a text panel with the full bot state for the current frame.

    Single image so it composes cleanly beside the overlay via
    :func:`compose`.
    """
    img = Image.new("RGB", (width, height), C_INFO_BG)
    draw = ImageDraw.Draw(img)
    font = _load_font(11)
    head = _load_font(12)

    lines: list[tuple[str, tuple[int, int, int]]] = []

    def h(text):
        lines.append(("", C_INFO_BG))  # spacer
        lines.append((text, C_INFO_HEAD))

    def kv(key, value, colour=C_INFO_FG):
        lines.append((f"  {key:<16}{value}", colour))

    h(f"frame {index}/{total - 1}  tick={snap.tick}")
    kv("phase", snap.phase.name)
    kv("role", snap.role.name)
    kv("ghost", str(snap.is_ghost))
    kv(
        "self_color",
        f"{snap.self_color} ({PLAYER_COLOR_NAMES[snap.self_color]})"
        if 0 <= snap.self_color < len(PLAYER_COLOR_NAMES)
        else str(snap.self_color),
    )

    h("camera")
    lock_label = snap.camera_lock.name if hasattr(snap.camera_lock, "name") else str(snap.camera_lock)
    kv("localized", str(snap.localized))
    kv("xy", f"({snap.camera_x}, {snap.camera_y})")
    kv("lock", lock_label)
    kv("score", str(snap.camera_score))

    h("motion")
    kv("velocity", f"({snap.motion_velocity[0]}, {snap.motion_velocity[1]})")
    kv("stuck", str(snap.motion_stuck))
    kv("jiggle", str(snap.motion_jiggle))

    h("goal")
    if snap.goal_has:
        kv("name", snap.goal_name)
        kv("screen", f"({snap.goal_x}, {snap.goal_y})")
    else:
        kv("", "(none)", C_INFO_DIM)
    if snap.goal_has_world:
        kv("world", f"({snap.goal_world_x}, {snap.goal_world_y})")
    if snap.goal_has_path_step:
        kv("waypoint", f"({snap.goal_path_step_x}, {snap.goal_path_step_y})")
    kv("path len", str(len(snap.goal_path)))
    if snap.goal_path_plan_tick >= 0:
        kv("plan age", f"{max(0, snap.tick - snap.goal_path_plan_tick)} ticks")

    h("pixel matches")
    kv("crewmates", str(len(snap.visible_crewmates)))
    kv("bodies", str(len(snap.visible_bodies)))
    kv("ghosts", str(len(snap.visible_ghosts)))
    kv("task icons", str(len(snap.visible_task_icons)))
    kv("radar dots", str(len(snap.radar_dots)))

    h("policy-facing state")
    kv("players", str(len(snap.players)))
    kv("bodies", str(len(snap.bodies)))
    kv("tasks", str(len(snap.tasks)))
    tasks_icon = sum(1 for t in snap.tasks if t.icon_visible)
    tasks_arrow = sum(1 for t in snap.tasks if t.arrow_visible)
    kv("icon_visible", str(tasks_icon))
    kv("arrow_visible", str(tasks_arrow))

    if snap.phase == Phase.VOTING:
        h("voting")
        v = snap.voting
        kv("player_count", str(v["player_count"]))
        kv("cursor", str(v["cursor"]))
        kv("self_slot", str(v["self_slot"]))
        kv("target", str(v["target_slot"]))
        kv(
            "chat_sus",
            PLAYER_COLOR_NAMES[v["chat_sus_color"]]
            if 0 <= v["chat_sus_color"] < len(PLAYER_COLOR_NAMES)
            else "-",
        )
        for speaker, y, text in v["chat_lines"]:
            name = (
                PLAYER_COLOR_NAMES[speaker]
                if 0 <= speaker < len(PLAYER_COLOR_NAMES)
                else "?"
            )
            lines.append((f"  {name:>10}: {text[:24]}", _tint_rgb(speaker)))

    h("decision")
    if snap.branch_id:
        kv("branch", snap.branch_id)
    if snap.intent:
        kv("intent", snap.intent[:30])

    y = 8
    for text, colour in lines:
        if not text:
            y += 4
            continue
        if colour is C_INFO_BG:
            y += 4
            continue
        use_font = head if colour is C_INFO_HEAD else font
        draw.text((8, y), text, fill=colour, font=use_font)
        y += 14
        if y > height - 16:
            break

    return img


def compose(
    raw: Image.Image, overlay: Image.Image, info: Image.Image, gap: int = 8
) -> Image.Image:
    width = raw.width + gap + overlay.width + gap + info.width
    height = max(raw.height, overlay.height, info.height)
    out = Image.new("RGB", (width, height), (48, 48, 48))
    out.paste(raw, (0, 0))
    out.paste(overlay, (raw.width + gap, 0))
    out.paste(info, (raw.width + gap + overlay.width + gap, 0))
    return out


_FONT_CACHE: dict[int, Any] = {}


def _load_font(size: int) -> Any:
    """Load a monospace font if one's around, else fall back to the
    Pillow default bitmap font. Cached to avoid per-frame reload."""
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for candidate in (
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        try:
            font = ImageFont.truetype(candidate, size)
            _FONT_CACHE[size] = font
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


# ---------------------------------------------------------------------------
# Text summary (for --summary, kept for parity with the old CLI)
# ---------------------------------------------------------------------------


def summary_line(snap: FrameSnapshot) -> str:
    return (
        f"phase={snap.phase.name:<13} role={snap.role.name:<9} "
        f"loc={snap.localized} cam=({snap.camera_x:4d},{snap.camera_y:4d}) "
        f"cm={len(snap.visible_crewmates)} b={len(snap.visible_bodies)} "
        f"gh={len(snap.visible_ghosts)} ti={len(snap.visible_task_icons)} "
        f"branch={snap.branch_id or '-'}"
    )


# ---------------------------------------------------------------------------
# Interactive viewer
# ---------------------------------------------------------------------------


def run_viewer(scrubber: Scrubber, scale: int) -> None:
    """Tkinter scrubber: ←/→ step, j/k step, g<N> jump, q quit.

    Keeps the rendered image cache warm via the Scrubber. Re-renders
    on every step because snapshots are small and Pillow text drawing
    is cheap.
    """
    import tkinter as tk
    from PIL import ImageTk

    data = scrubber.data
    frames = scrubber.frames

    root = tk.Tk()
    root.title("modulabot perception viewer")
    root.configure(bg="#1e1e22")

    index = {"i": 0}
    tk_image_ref: dict[str, Any] = {}

    canvas = tk.Label(root, bg="#1e1e22")
    canvas.pack(padx=4, pady=4)

    status = tk.Label(
        root,
        bg="#1e1e22",
        fg="#cccccc",
        font=("Menlo", 11),
        anchor="w",
        justify="left",
    )
    status.pack(fill="x", padx=4)

    def render(i: int) -> None:
        i = max(0, min(len(frames) - 1, i))
        index["i"] = i
        snap = scrubber.snapshot_for(i)
        raw = render_raw(snap.frame, scale=scale)
        overlay = render_overlay(snap, data, scale=scale)
        info = render_info_panel(
            snap, i, len(frames), width=360, height=raw.height
        )
        composite = compose(raw, overlay, info)
        tk_image = ImageTk.PhotoImage(composite)
        canvas.configure(image=tk_image)
        tk_image_ref["img"] = tk_image  # prevent GC
        status.configure(
            text=(
                f"[{i:4d} / {len(frames)-1}]   "
                f"{summary_line(snap)}   "
                "[←/→ step · Home/End first/last · g→frame → · q quit]"
            )
        )

    def on_key(event: Any) -> None:
        k = event.keysym.lower()
        if k in ("left", "j"):
            render(index["i"] - 1)
        elif k in ("right", "k"):
            render(index["i"] + 1)
        elif k == "home":
            render(0)
        elif k == "end":
            render(len(frames) - 1)
        elif k == "page_up":
            render(index["i"] - 10)
        elif k == "page_down":
            render(index["i"] + 10)
        elif k == "g":
            _ask_jump(root, len(frames), render)
        elif k in ("q", "escape"):
            root.destroy()

    root.bind("<Key>", on_key)
    render(0)
    root.mainloop()


def _ask_jump(root: Any, total: int, render_fn: Any) -> None:
    """Pop up a small dialog to jump to a specific frame index."""
    import tkinter as tk

    win = tk.Toplevel(root)
    win.title("go to frame")
    tk.Label(win, text=f"frame index (0..{total - 1}):").pack(padx=8, pady=4)
    entry = tk.Entry(win)
    entry.pack(padx=8, pady=4)
    entry.focus_set()

    def go(_event: Any = None) -> None:
        try:
            render_fn(int(entry.get()))
        except ValueError:
            pass
        win.destroy()

    entry.bind("<Return>", go)
    entry.bind("<Escape>", lambda _e: win.destroy())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "frames_path",
        type=Path,
        help="Path to a .npy file of (N, 128, 128) uint8 frames.",
    )
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--save", type=Path)
    parser.add_argument(
        "--range",
        help="Render frames [A:B) to PNGs. Requires --outdir.",
    )
    parser.add_argument("--outdir", type=Path)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Launch the interactive scrubber (tkinter).",
    )
    args = parser.parse_args()

    frames = np.load(args.frames_path)
    print(f"Loaded {frames.shape[0]} frames of shape {frames.shape[1:]} from {args.frames_path}")

    data = load_reference_data()
    scrubber = Scrubber(frames, data)

    if args.summary:
        for i in range(len(frames)):
            snap = scrubber.snapshot_for(i)
            print(f"frame {i:4d}: {summary_line(snap)}")
        return 0

    if args.watch:
        run_viewer(scrubber, scale=args.scale)
        return 0

    if args.range:
        if not args.outdir:
            raise SystemExit("--range requires --outdir")
        args.outdir.mkdir(parents=True, exist_ok=True)
        try:
            lo, hi = (int(x) for x in args.range.split(":"))
        except ValueError as exc:
            raise SystemExit(f"--range must be A:B integers, got {args.range!r}") from exc
        hi = min(hi, len(frames))
        for i in range(lo, hi):
            snap = scrubber.snapshot_for(i)
            raw = render_raw(snap.frame, scale=args.scale)
            overlay = render_overlay(snap, data, scale=args.scale)
            info = render_info_panel(snap, i, len(frames), 360, raw.height)
            out = compose(raw, overlay, info)
            out.save(args.outdir / f"frame_{i:05d}.png")
        print(f"Wrote {hi - lo} images to {args.outdir}")
        return 0

    # Single-frame render mode (default).
    if args.frame >= frames.shape[0]:
        raise SystemExit(f"--frame {args.frame} out of range (have {frames.shape[0]})")
    snap = scrubber.snapshot_for(args.frame)
    print(f"Frame {args.frame}: {summary_line(snap)}")
    raw = render_raw(snap.frame, scale=args.scale)
    overlay = render_overlay(snap, data, scale=args.scale)
    info = render_info_panel(snap, args.frame, len(frames), 360, raw.height)
    out = compose(raw, overlay, info)
    if args.save:
        out.save(args.save)
        print(f"Wrote {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
