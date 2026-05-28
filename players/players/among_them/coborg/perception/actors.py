"""Actor scan layer: roles, self colour, bodies, ghosts, crewmates.

Port of
``users/james/personal_cogs/among_them/guided_bot/perception/actors.nim``.
Names and constants are mirrored 1:1 (snake_cased) so the parity rig at
``perception/parity/run_parity.py`` can assert symbol-by-symbol equality
against the Nim oracle sidecars.

Pipeline mirrors the upstream ``scanAll`` ordering, minus the
``isInterstitial`` short-circuit (interstitial detection itself lands in
S4 — until then the scan procs always run when called, and the production
gate happens one level up). For one frame:

1. :func:`update_role` — HUD probe at ``(KILL_ICON_X, KILL_ICON_Y)`` for
   the ghost icon or the (lit / shadowed) kill button. Stateful: takes
   the previous frame's debounce counters and current role and returns
   updated counters + role transition.
2. :func:`update_self_color` — small search window around the player's
   rendered sprite anchor; returns the dominant tint colour slot if a
   match is found.
3. :func:`scan_bodies` / :func:`scan_ghosts` / :func:`scan_crewmates` —
   vectorised sprite match (via the S2 ``match_actor_sprite_all`` kernel)
   plus greedy raster-order Chebyshev dedup. ``scan_crewmates`` excludes
   anchors whose centre falls within ``PLAYER_IGNORE_RADIUS`` of the
   rendered self position.

Performance: the hot kernel (``match_actor_sprite_all``) is already
vectorised in S2. The HUD probes and self-colour search touch a single
``(12, 12)`` window each. Dedup loops are O(n²) but n is small (typically
<20 anchors per fixture across all sprite types). No numba.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .data import (
    SHADE_TINT_COLOR,
    SPRITE_SIZE,
    TINT_COLOR,
    TRANSPARENT_INDEX,
)
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH
from .sprite_match import (
    PLAYER_BODY_LUT,
    PLAYER_COLORS,
    SHADOW_MAP,
    match_actor_sprite_all,
)


# --- atlas slot indices (mirrors data/sprite_index.json) -------------------

ATLAS_PLAYER = 0
ATLAS_BODY = 1
ATLAS_GHOST = 2
ATLAS_TASK = 3
ATLAS_KILL_BUTTON = 4
ATLAS_GHOST_ICON = 5


# --- actor scan budgets (mirror actors.nim constants) ---------------------

CREWMATE_MAX_MISSES = 8
CREWMATE_MIN_STABLE = 8
CREWMATE_MIN_BODY = 8   # = min_tint at the kernel boundary

BODY_MAX_MISSES = 9
BODY_MIN_STABLE = 6
BODY_MIN_TINT = 6

GHOST_MAX_MISSES = 9
GHOST_MIN_STABLE = 6
GHOST_MIN_TINT = 6

CREWMATE_SEARCH_RADIUS = 1
BODY_SEARCH_RADIUS = 1
GHOST_SEARCH_RADIUS = 1


# --- HUD scalar-probe budgets (kill-button / ghost-icon at the HUD slot) --

GHOST_ICON_MAX_MISSES = 3
GHOST_ICON_FRAME_THRESHOLD = 2

KILL_ICON_MAX_MISSES = 5
# Consecutive kill-HUD matches before Unknown -> Imposter (upstream
# `tuning.nim:KillIconRoleFrames`). Crew -> Imposter requires stronger
# evidence; OCR-confirmed Crewmate is never overridden by this path.
KILL_ICON_ROLE_FRAMES = 3

# Strict-match miss budget for the lit kill-button (task-icon style budget).
MATCHES_SPRITE_MAX_MISSES = 4

KILL_ICON_X = 1
KILL_ICON_Y = SCREEN_HEIGHT - SPRITE_SIZE - 1  # = 115


# --- self-colour and player-ignore zone -----------------------------------

# Screen position where the player's own sprite is rendered. Distinct from
# the collision-box centre used by geometry.nim (upstream comment), and
# offset from the bare ``ScreenWidth/2 - SpriteSize/2`` self-colour search
# centre by one pixel in X and four pixels in Y.
PLAYER_SPRITE_ANCHOR_X = (SCREEN_WIDTH // 2) - 1   # = 63
PLAYER_SPRITE_ANCHOR_Y = (SCREEN_HEIGHT // 2) - 4  # = 60
PLAYER_IGNORE_RADIUS = 9

SELF_COLOR_SEARCH_RADIUS = 2


# --- types ----------------------------------------------------------------


class Role(Enum):
    """Mirrors the upstream ``BotRole`` enum. String values match the
    lowercase form the Nim oracle dumper emits (see
    ``extract_oracle.nim::roleToString``)."""

    UNKNOWN = "unknown"
    CREWMATE = "crewmate"
    IMPOSTER = "imposter"


@dataclass
class CrewmateMatch:
    x: int
    y: int
    color_index: int
    flip_h: bool


@dataclass
class BodyMatch:
    x: int
    y: int
    color_index: int


@dataclass
class GhostMatch:
    x: int
    y: int
    flip_h: bool


@dataclass
class ActorPercept:
    """Output of one actor-scan pass. Mirrors upstream ``ActorPercept`` in
    ``actors.nim``."""

    crewmates: list[CrewmateMatch] = field(default_factory=list)
    bodies: list[BodyMatch] = field(default_factory=list)
    ghosts: list[GhostMatch] = field(default_factory=list)
    role_updated: bool = False
    new_role: Role = Role.UNKNOWN
    is_ghost: bool = False
    kill_ready: bool = False
    ghost_icon_frames: int = 0
    kill_icon_frames: int = 0
    self_color_updated: bool = False
    new_self_color: int = -1


# --- raw-anchor helpers (used inside _scan_actor / dedup) -----------------


def _dedup_anchors(anchors: list[tuple[int, int, bool]], radius: int) -> list[tuple[int, int, bool]]:
    """Greedy raster-order dedup. Sorts by ``(y, x)``, then keeps an
    anchor iff no already-kept anchor is within Chebyshev ``radius`` on
    both axes. Mirrors ``actors.nim::dedupAnchors``."""
    if len(anchors) <= 1:
        return list(anchors)
    sorted_anchors = sorted(anchors, key=lambda a: (a[0], a[1]))
    kept: list[tuple[int, int, bool]] = []
    for y, x, flip in sorted_anchors:
        for ky, kx, _ in kept:
            if abs(y - ky) <= radius and abs(x - kx) <= radius:
                break
        else:
            kept.append((y, x, flip))
    return kept


def _scan_actor(
    frame: np.ndarray,
    sprite: np.ndarray,
    flips: tuple[bool, ...],
    max_misses: int,
    min_stable: int,
    min_tint: int,
    dedup_radius: int,
    ignore_center: bool,
) -> list[tuple[int, int, bool]]:
    """Run the vectorised match kernel for each flip in order, collect
    positive anchors not already claimed by an earlier flip, optionally
    exclude anchors whose sprite centre is inside the player-ignore zone,
    and finally dedup. Mirrors ``actors.nim::scanActor``.

    Flip priority: iterate flips in order; an anchor position is owned
    by the first flip that matches it. Mirrors upstream "prefer
    unflipped" semantics.
    """
    sh, sw = sprite.shape
    max_y = SCREEN_HEIGHT - sh + 1
    max_x = SCREEN_WIDTH - sw + 1
    claimed = np.zeros((max_y, max_x), dtype=bool)
    anchors: list[tuple[int, int, bool]] = []
    spr_centre_off_x = sw // 2
    spr_centre_off_y = sh // 2

    for flip in flips:
        mask = match_actor_sprite_all(
            frame,
            sprite,
            flip_h=flip,
            max_misses=max_misses,
            min_stable=min_stable,
            min_tint=min_tint,
        )
        if ignore_center:
            ys, xs = np.where(mask)
            for ay, ax in zip(ys.tolist(), xs.tolist()):
                cx = ax + spr_centre_off_x
                cy = ay + spr_centre_off_y
                if (
                    abs(cx - PLAYER_SPRITE_ANCHOR_X) <= PLAYER_IGNORE_RADIUS
                    and abs(cy - PLAYER_SPRITE_ANCHOR_Y) <= PLAYER_IGNORE_RADIUS
                ):
                    mask[ay, ax] = False

        ys, xs = np.where(mask & ~claimed)
        for ay, ax in zip(ys.tolist(), xs.tolist()):
            claimed[ay, ax] = True
            anchors.append((ay, ax, flip))

    return _dedup_anchors(anchors, dedup_radius)


# --- scalar sprite-match helpers (HUD icons) ------------------------------


def _sprite_misses(frame: np.ndarray, sprite: np.ndarray, x: int, y: int) -> tuple[int, int]:
    """Count ``(misses, opaque)`` for ``sprite`` placed at frame-space
    anchor ``(x, y)``. Mirrors ``actors.nim::spriteMisses``."""
    sh, sw = sprite.shape
    misses = 0
    opaque = 0
    for sy in range(sh):
        for sx in range(sw):
            c = int(sprite[sy, sx])
            if c == TRANSPARENT_INDEX:
                continue
            opaque += 1
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                misses += 1
            elif int(frame[fy, fx]) != c:
                misses += 1
    return misses, opaque


def _matches_sprite(frame: np.ndarray, sprite: np.ndarray, x: int, y: int) -> bool:
    """Strict per-anchor sprite match. Used for the lit kill-button check.
    Mirrors ``actors.nim::matchesSprite`` (task-icon miss budget = 4)."""
    misses, opaque = _sprite_misses(frame, sprite, x, y)
    return opaque > 0 and misses <= MATCHES_SPRITE_MAX_MISSES


def _matches_sprite_shadowed(frame: np.ndarray, sprite: np.ndarray, x: int, y: int) -> bool:
    """Per-anchor match against the sprite's shadow-mapped variant. Used
    for the unlit kill-button check. Mirrors
    ``actors.nim::matchesSpriteShadowed`` (miss budget =
    ``KILL_ICON_MAX_MISSES``)."""
    sh, sw = sprite.shape
    misses = 0
    opaque = 0
    for sy in range(sh):
        for sx in range(sw):
            c = int(sprite[sy, sx])
            if c == TRANSPARENT_INDEX:
                continue
            opaque += 1
            sc = int(SHADOW_MAP[c & 0x0F])
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                misses += 1
            elif int(frame[fy, fx]) != sc:
                misses += 1
            if misses > KILL_ICON_MAX_MISSES:
                return False
    return opaque > 0 and misses <= KILL_ICON_MAX_MISSES


# --- single-anchor crewmate match + colour vote ---------------------------


def _matches_crewmate(
    frame: np.ndarray, sprite: np.ndarray, x: int, y: int, flip_h: bool
) -> bool:
    """Strict single-anchor crewmate match. Used by :func:`update_self_color`
    where the screen position is known exactly. Mirrors
    ``actors.nim::matchesCrewmate``."""
    sh, sw = sprite.shape
    misses = 0
    matched_stable = 0
    body_matched = 0
    stable_pixels = 0
    body_pixels = 0
    for sy in range(sh):
        for sx in range(sw):
            src_x = sw - 1 - sx if flip_h else sx
            c = int(sprite[sy, src_x])
            if c == TRANSPARENT_INDEX:
                continue
            fx = x + sx
            fy = y + sy
            is_body_pixel = c == TINT_COLOR or c == SHADE_TINT_COLOR
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                misses += 1
                if is_body_pixel:
                    body_pixels += 1
                else:
                    stable_pixels += 1
            else:
                fc = int(frame[fy, fx])
                if is_body_pixel:
                    body_pixels += 1
                    if PLAYER_BODY_LUT[fc]:
                        body_matched += 1
                    else:
                        misses += 1
                else:
                    stable_pixels += 1
                    if fc == c:
                        matched_stable += 1
                    else:
                        misses += 1
            if misses > CREWMATE_MAX_MISSES:
                return False
    return (
        stable_pixels >= CREWMATE_MIN_STABLE
        and matched_stable >= CREWMATE_MIN_STABLE
        and body_pixels >= CREWMATE_MIN_BODY
        and body_matched >= CREWMATE_MIN_BODY
    )


def _crewmate_color_index(
    frame: np.ndarray, sprite: np.ndarray, x: int, y: int, flip_h: bool
) -> int:
    """Single-anchor dominant-tint vote. Only ``TintColor`` pixels vote
    (not ``ShadeTintColor``) — note this differs from the kernel's
    ``actor_color_index_all`` which counts both. Mirrors
    ``actors.nim::crewmateColorIndex``. Returns the argmax player-colour
    slot or ``-1``."""
    sh, sw = sprite.shape
    counts = np.zeros(PLAYER_COLORS.size, dtype=np.int64)
    for sy in range(sh):
        for sx in range(sw):
            src_x = sw - 1 - sx if flip_h else sx
            c = int(sprite[sy, src_x])
            if c != TINT_COLOR:
                continue
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                continue
            fc = int(frame[fy, fx])
            for i, pc in enumerate(PLAYER_COLORS):
                if fc == int(pc):
                    counts[i] += 1
                    break
    best = -1
    best_votes = 0
    for i in range(PLAYER_COLORS.size):
        if counts[i] > best_votes:
            best_votes = int(counts[i])
            best = i
    return best


# --- public scan procs ----------------------------------------------------


def update_role(
    percept: ActorPercept,
    prev_ghost_icon_frames: int,
    prev_kill_icon_frames: int,
    prev_role: Role,
    atlas: np.ndarray,
    frame: np.ndarray,
) -> None:
    """HUD slot probe at ``(KILL_ICON_X, KILL_ICON_Y)``. Mirrors
    ``actors.nim::updateRole``.

    Ghost detection requires ``GHOST_ICON_FRAME_THRESHOLD`` consecutive
    frames with the ghost icon present (debounce against transient
    occlusion). Kill-button role detection is also debounced —
    ``Unknown -> Imposter`` needs ``KILL_ICON_ROLE_FRAMES`` consecutive
    HUD matches, and ``Crewmate -> Imposter`` is never set from this
    path: an OCR-confirmed crewmate role is authoritative.
    """
    ghost_sprite = atlas[ATLAS_GHOST_ICON]
    g_misses, g_opaque = _sprite_misses(frame, ghost_sprite, KILL_ICON_X, KILL_ICON_Y)
    if g_opaque > 0 and g_misses <= GHOST_ICON_MAX_MISSES:
        percept.ghost_icon_frames = prev_ghost_icon_frames + 1
        percept.kill_icon_frames = 0
        percept.kill_ready = False
        if percept.ghost_icon_frames >= GHOST_ICON_FRAME_THRESHOLD:
            percept.is_ghost = True
            percept.role_updated = True
            if prev_role == Role.UNKNOWN:
                percept.new_role = Role.CREWMATE
            else:
                percept.new_role = prev_role
        return

    percept.ghost_icon_frames = 0

    kill_sprite = atlas[ATLAS_KILL_BUTTON]
    lit_match = _matches_sprite(frame, kill_sprite, KILL_ICON_X, KILL_ICON_Y)
    shad_match = _matches_sprite_shadowed(frame, kill_sprite, KILL_ICON_X, KILL_ICON_Y)

    if lit_match or shad_match:
        percept.kill_icon_frames = prev_kill_icon_frames + 1
        stable = prev_role == Role.IMPOSTER or percept.kill_icon_frames >= KILL_ICON_ROLE_FRAMES
        percept.kill_ready = lit_match and stable
        # OCR-confirmed Crewmate is never overridden — HUD sprite matching
        # at (1, 115) produces false positives when map / task pixels land
        # there. Mirrors upstream comment in actors.nim:472.
        if stable and prev_role == Role.UNKNOWN:
            percept.role_updated = True
            percept.new_role = Role.IMPOSTER
    else:
        percept.kill_icon_frames = 0
        percept.kill_ready = False
        if prev_role == Role.UNKNOWN:
            percept.role_updated = True
            percept.new_role = Role.CREWMATE


def update_self_color(percept: ActorPercept, atlas: np.ndarray, frame: np.ndarray) -> None:
    """Centre-camera colour probe. Tries the canonical sprite-render
    anchor first, then expanding rings of offsets up to
    ``SELF_COLOR_SEARCH_RADIUS``, trying ``flip_h=False`` then
    ``flip_h=True`` at each anchor. Mirrors ``actors.nim::updateSelfColor``.
    """
    sprite = atlas[ATLAS_PLAYER]
    base_x = (SCREEN_WIDTH // 2) - (sprite.shape[1] // 2)
    base_y = (SCREEN_HEIGHT // 2) - (sprite.shape[0] // 2)
    for radius in range(SELF_COLOR_SEARCH_RADIUS + 1):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if abs(dx) != radius and abs(dy) != radius:
                    continue
                ax = base_x + dx
                ay = base_y + dy
                for flip in (False, True):
                    if _matches_crewmate(frame, sprite, ax, ay, flip):
                        ci = _crewmate_color_index(frame, sprite, ax, ay, flip)
                        if ci >= 0:
                            percept.self_color_updated = True
                            percept.new_self_color = ci
                            return


def scan_crewmates(percept: ActorPercept, atlas: np.ndarray, frame: np.ndarray) -> None:
    """Living-crewmate scan, excluding self. Uses the vectorised
    ``match_actor_sprite_all`` kernel plus :func:`_dedup_anchors` and the
    player-ignore-zone mask. Per-anchor colour vote uses the
    ``TintColor``-only :func:`_crewmate_color_index`. Mirrors
    ``actors.nim::scanCrewmates``."""
    sprite = atlas[ATLAS_PLAYER]
    anchors = _scan_actor(
        frame,
        sprite,
        flips=(False, True),
        max_misses=CREWMATE_MAX_MISSES,
        min_stable=CREWMATE_MIN_STABLE,
        min_tint=CREWMATE_MIN_BODY,
        dedup_radius=CREWMATE_SEARCH_RADIUS,
        ignore_center=True,
    )
    for y, x, flip in anchors:
        ci = _crewmate_color_index(frame, sprite, x, y, flip)
        percept.crewmates.append(CrewmateMatch(x=x, y=y, color_index=ci, flip_h=flip))


def scan_bodies(percept: ActorPercept, atlas: np.ndarray, frame: np.ndarray) -> None:
    """Dead-crewmate (body) scan. Bodies don't flip in-game, so the scan
    uses ``flips=(False,)``. Mirrors ``actors.nim::scanBodies``."""
    sprite = atlas[ATLAS_BODY]
    anchors = _scan_actor(
        frame,
        sprite,
        flips=(False,),
        max_misses=BODY_MAX_MISSES,
        min_stable=BODY_MIN_STABLE,
        min_tint=BODY_MIN_TINT,
        dedup_radius=BODY_SEARCH_RADIUS,
        ignore_center=False,
    )
    for y, x, _flip in anchors:
        ci = _crewmate_color_index(frame, sprite, x, y, False)
        percept.bodies.append(BodyMatch(x=x, y=y, color_index=ci))


def scan_ghosts(percept: ActorPercept, atlas: np.ndarray, frame: np.ndarray) -> None:
    """Ghost-sprite scan. Ghosts are translucent — no reliable colour
    extraction, only anchor + flip. Mirrors ``actors.nim::scanGhosts``."""
    sprite = atlas[ATLAS_GHOST]
    anchors = _scan_actor(
        frame,
        sprite,
        flips=(False, True),
        max_misses=GHOST_MAX_MISSES,
        min_stable=GHOST_MIN_STABLE,
        min_tint=GHOST_MIN_TINT,
        dedup_radius=GHOST_SEARCH_RADIUS,
        ignore_center=False,
    )
    for y, x, flip in anchors:
        percept.ghosts.append(GhostMatch(x=x, y=y, flip_h=flip))
