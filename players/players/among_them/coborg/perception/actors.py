"""Actor scan layer: roles, self colour, bodies, ghosts, crewmates.

Public API surface (the only symbols the rest of the codebase should
depend on):

- :func:`compute_actor_percept` — canonical orchestration. Returns a
  fully populated :class:`ActorPercept` for one frame. **Use this if
  you don't have a specific reason to call the individual scans.**
- :func:`update_role` -> :class:`RoleUpdate`
- :func:`update_self_color` -> :class:`SelfColorUpdate`
- :func:`scan_bodies` -> ``list[BodyMatch]``
- :func:`scan_ghosts` -> ``list[GhostMatch]``
- :func:`scan_crewmates` -> ``list[CrewmateMatch]``
- :class:`ActorPercept`, :class:`Role`, and the four match record
  dataclasses.

Every scan function takes ``(atlas, frame)`` and returns its own
output. None of them mutate caller state. This is so an alternate
implementation of any single scan can be dropped in without touching
the orchestration or other scans.

The role / self-colour ports were originally written against the
upstream Nim ``var ActorPercept`` in-place mutation pattern; the
return-value API here is a deliberate departure. Concrete behavior
parity against the Nim oracle is preserved by the fixture-based gate
in ``perception/parity/run_parity.py``.

Initially ported from
``users/james/personal_cogs/among_them/guided_bot/perception/actors.nim``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .data import (
    ATLAS_BODY,
    ATLAS_GHOST,
    ATLAS_GHOST_ICON,
    ATLAS_KILL_BUTTON,
    ATLAS_PLAYER,
    PALETTE_TO_PLAYER_SLOT,
    PLAYER_BODY_LUT,
    PLAYER_COLORS,
    SHADE_TINT_COLOR,
    SHADOW_MAP,
    SPRITE_SIZE,
    TINT_COLOR,
    TRANSPARENT_INDEX,
)
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH
from .sprite_match import match_actor_sprite_all

# Sentinel palette value for out-of-screen pixels in patches built by
# :func:`_oob_filled_patch`. 255 is safe to use as an in-band sentinel
# because real frames are 4-bpp (palette indices 0..15) so 255 never
# appears in a legitimate frame pixel. PLAYER_BODY_LUT[255] and
# PALETTE_TO_PLAYER_SLOT[255] are both "not a player color".
_OOB_SENTINEL = np.uint8(255)


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
class RoleUpdate:
    """Result of one :func:`update_role` call. Mirrors the role-related
    sub-fields of upstream ``ActorPercept`` after a single ``updateRole``
    invocation. ``ghost_icon_frames`` / ``kill_icon_frames`` are the
    post-update counter values and feed back as priors on the next tick."""

    role_updated: bool = False
    new_role: Role = Role.UNKNOWN
    is_ghost: bool = False
    kill_ready: bool = False
    ghost_icon_frames: int = 0
    kill_icon_frames: int = 0


@dataclass
class SelfColorUpdate:
    """Result of one :func:`update_self_color` call. ``updated`` is True
    iff the search window found a single-anchor crewmate match with at
    least one tint vote; ``color_index`` is the slot in ``PLAYER_COLORS``
    or ``-1`` when no vote landed."""

    updated: bool = False
    color_index: int = -1


@dataclass
class ActorPercept:
    """Aggregated per-frame actor-scan output. Convenience composition of
    :func:`update_role` / :func:`update_self_color` / :func:`scan_bodies`
    / :func:`scan_ghosts` / :func:`scan_crewmates`. The flat-field shape
    mirrors upstream ``ActorPercept`` in ``actors.nim``."""

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


def _oob_filled_patch(
    frame: np.ndarray, x: int, y: int, shape: tuple[int, int]
) -> np.ndarray:
    """Return a ``shape``-sized uint8 patch of ``frame`` anchored at
    ``(x, y)``, with out-of-screen pixels filled with :data:`_OOB_SENTINEL`
    (255). Real frame pixels are palette indices 0..15, so 255 is safe to
    use as an in-band sentinel — ``PLAYER_BODY_LUT[255]`` and
    ``PALETTE_TO_PLAYER_SLOT[255]`` both report "not a player color".

    Lets the vectorised match helpers skip the per-pixel OOB branch by
    making the OOB rule fall out of the same boolean-mask arithmetic the
    in-bounds rule already uses.
    """
    sh, sw = shape
    patch = np.full((sh, sw), _OOB_SENTINEL, dtype=np.uint8)
    fy0, fx0 = max(0, y), max(0, x)
    fy1 = min(SCREEN_HEIGHT, y + sh)
    fx1 = min(SCREEN_WIDTH, x + sw)
    if fy0 < fy1 and fx0 < fx1:
        py0, px0 = fy0 - y, fx0 - x
        py1, px1 = fy1 - y, fx1 - x
        patch[py0:py1, px0:px1] = frame[fy0:fy1, fx0:fx1]
    return patch


def _ignore_zone_mask(max_y: int, max_x: int, sh: int, sw: int) -> np.ndarray:
    """``(max_y, max_x)`` bool mask: True iff a sprite anchored at
    ``(ay, ax)`` would have its centre inside the player-render
    ignore zone. Used by :func:`_scan_actor` when ``ignore_center=True``.
    """
    ys = np.arange(max_y)[:, None]
    xs = np.arange(max_x)[None, :]
    return (
        (np.abs(xs + sw // 2 - PLAYER_SPRITE_ANCHOR_X) <= PLAYER_IGNORE_RADIUS)
        & (np.abs(ys + sh // 2 - PLAYER_SPRITE_ANCHOR_Y) <= PLAYER_IGNORE_RADIUS)
    )


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
    ignore_zone = _ignore_zone_mask(max_y, max_x, sh, sw) if ignore_center else None

    anchors: list[tuple[int, int, bool]] = []
    for flip in flips:
        mask = match_actor_sprite_all(
            frame,
            sprite,
            flip_h=flip,
            max_misses=max_misses,
            min_stable=min_stable,
            min_tint=min_tint,
        ).astype(bool)
        if ignore_zone is not None:
            mask &= ~ignore_zone
        new_hits = mask & ~claimed
        claimed |= new_hits
        ys, xs = np.where(new_hits)
        anchors.extend((int(y), int(x), flip) for y, x in zip(ys.tolist(), xs.tolist()))

    return _dedup_anchors(anchors, dedup_radius)


# --- vectorised sprite-match helpers (HUD icons) --------------------------


def _sprite_misses(frame: np.ndarray, sprite: np.ndarray, x: int, y: int) -> tuple[int, int]:
    """Count ``(misses, opaque)`` for ``sprite`` placed at frame-space
    anchor ``(x, y)``. Mirrors ``actors.nim::spriteMisses``."""
    patch = _oob_filled_patch(frame, x, y, sprite.shape)
    opaque = sprite != TRANSPARENT_INDEX
    misses = int(np.count_nonzero(opaque & (patch != sprite)))
    return misses, int(opaque.sum())


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
    patch = _oob_filled_patch(frame, x, y, sprite.shape)
    opaque = sprite != TRANSPARENT_INDEX
    shadow = SHADOW_MAP[sprite & 0x0F]
    misses = int(np.count_nonzero(opaque & (patch != shadow)))
    return bool(opaque.any()) and misses <= KILL_ICON_MAX_MISSES


# --- single-anchor crewmate match + colour vote ---------------------------


def _matches_crewmate(
    frame: np.ndarray, sprite: np.ndarray, x: int, y: int, flip_h: bool
) -> bool:
    """Strict single-anchor crewmate match. Used by :func:`update_self_color`
    where the screen position is known exactly. Mirrors
    ``actors.nim::matchesCrewmate``: out-of-screen pixels count toward
    ``stable_pixels`` / ``body_pixels`` (whichever the sprite says) and
    add to ``misses``, but never to ``matched_stable`` /
    ``body_matched``."""
    spr = sprite[:, ::-1] if flip_h else sprite
    patch = _oob_filled_patch(frame, x, y, spr.shape)
    opaque = spr != TRANSPARENT_INDEX
    body = (spr == TINT_COLOR) | (spr == SHADE_TINT_COLOR)
    stable = opaque & ~body

    stable_pixels = int(stable.sum())
    body_pixels = int(body.sum())
    matched_stable = int(np.count_nonzero(stable & (patch == spr)))
    body_matched = int(np.count_nonzero(body & PLAYER_BODY_LUT[patch]))

    misses = (stable_pixels - matched_stable) + (body_pixels - body_matched)
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
    spr = sprite[:, ::-1] if flip_h else sprite
    tint_mask = spr == TINT_COLOR
    if not tint_mask.any():
        return -1
    patch = _oob_filled_patch(frame, x, y, spr.shape)
    slots = PALETTE_TO_PLAYER_SLOT[patch[tint_mask]]
    in_range = slots < PLAYER_COLORS.size
    if not in_range.any():
        return -1
    counts = np.bincount(slots[in_range], minlength=PLAYER_COLORS.size)
    return int(counts.argmax())


# --- public scan procs (return their outputs; never mutate args) ----------


def update_role(
    atlas: np.ndarray,
    frame: np.ndarray,
    *,
    prev_ghost_icon_frames: int = 0,
    prev_kill_icon_frames: int = 0,
    prev_role: Role = Role.UNKNOWN,
) -> RoleUpdate:
    """HUD slot probe at ``(KILL_ICON_X, KILL_ICON_Y)``. Mirrors
    ``actors.nim::updateRole``.

    Ghost detection requires ``GHOST_ICON_FRAME_THRESHOLD`` consecutive
    frames with the ghost icon present (debounce against transient
    occlusion). Kill-button role detection is also debounced —
    ``Unknown -> Imposter`` needs ``KILL_ICON_ROLE_FRAMES`` consecutive
    HUD matches, and ``Crewmate -> Imposter`` is never set from this
    path: an OCR-confirmed crewmate role is authoritative.

    Stateful: thread the previous tick's ``ghost_icon_frames`` /
    ``kill_icon_frames`` / role through the keyword arguments so the
    debounce counters advance correctly across frames. The defaults
    treat the call as the very first tick of a fresh episode.
    """
    result = RoleUpdate(new_role=Role.UNKNOWN)

    ghost_sprite = atlas[ATLAS_GHOST_ICON]
    g_misses, g_opaque = _sprite_misses(frame, ghost_sprite, KILL_ICON_X, KILL_ICON_Y)
    if g_opaque > 0 and g_misses <= GHOST_ICON_MAX_MISSES:
        result.ghost_icon_frames = prev_ghost_icon_frames + 1
        result.kill_icon_frames = 0
        result.kill_ready = False
        if result.ghost_icon_frames >= GHOST_ICON_FRAME_THRESHOLD:
            result.is_ghost = True
            result.role_updated = True
            if prev_role == Role.UNKNOWN:
                result.new_role = Role.CREWMATE
            else:
                result.new_role = prev_role
        return result

    result.ghost_icon_frames = 0

    kill_sprite = atlas[ATLAS_KILL_BUTTON]
    lit_match = _matches_sprite(frame, kill_sprite, KILL_ICON_X, KILL_ICON_Y)
    shad_match = _matches_sprite_shadowed(frame, kill_sprite, KILL_ICON_X, KILL_ICON_Y)

    if lit_match or shad_match:
        result.kill_icon_frames = prev_kill_icon_frames + 1
        stable = prev_role == Role.IMPOSTER or result.kill_icon_frames >= KILL_ICON_ROLE_FRAMES
        result.kill_ready = lit_match and stable
        # OCR-confirmed Crewmate is never overridden — HUD sprite matching
        # at (1, 115) produces false positives when map / task pixels land
        # there. Mirrors upstream comment in actors.nim:472.
        if stable and prev_role == Role.UNKNOWN:
            result.role_updated = True
            result.new_role = Role.IMPOSTER
    else:
        result.kill_icon_frames = 0
        result.kill_ready = False
        if prev_role == Role.UNKNOWN:
            result.role_updated = True
            result.new_role = Role.CREWMATE

    return result


def update_self_color(atlas: np.ndarray, frame: np.ndarray) -> SelfColorUpdate:
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
                            return SelfColorUpdate(updated=True, color_index=ci)
    return SelfColorUpdate()


def scan_crewmates(atlas: np.ndarray, frame: np.ndarray) -> list[CrewmateMatch]:
    """Living-crewmate scan, excluding self. Mirrors
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
    return [
        CrewmateMatch(
            x=x,
            y=y,
            color_index=_crewmate_color_index(frame, sprite, x, y, flip),
            flip_h=flip,
        )
        for y, x, flip in anchors
    ]


def scan_bodies(atlas: np.ndarray, frame: np.ndarray) -> list[BodyMatch]:
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
    return [
        BodyMatch(
            x=x,
            y=y,
            color_index=_crewmate_color_index(frame, sprite, x, y, False),
        )
        for y, x, _flip in anchors
    ]


def scan_ghosts(atlas: np.ndarray, frame: np.ndarray) -> list[GhostMatch]:
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
    return [GhostMatch(x=x, y=y, flip_h=flip) for y, x, flip in anchors]


def compute_actor_percept(
    atlas: np.ndarray,
    frame: np.ndarray,
    *,
    prev: ActorPercept | None = None,
) -> ActorPercept:
    """Canonical actor-scan orchestration. Runs every public scan
    function and assembles the result into a single :class:`ActorPercept`.

    This is the entry point callers should reach for unless they have a
    specific reason to invoke a single scan. Swapping the implementation
    of any individual scan only requires editing that scan's function;
    this orchestrator stays untouched as long as the public signatures
    hold.

    Pass ``prev`` (a previous tick's percept) to thread the debounce
    counters for :func:`update_role` across frames. Omit it (or pass
    ``None``) to treat the call as the very first tick.
    """
    prev_g = prev.ghost_icon_frames if prev is not None else 0
    prev_k = prev.kill_icon_frames if prev is not None else 0
    prev_role = prev.new_role if prev is not None else Role.UNKNOWN

    role = update_role(
        atlas,
        frame,
        prev_ghost_icon_frames=prev_g,
        prev_kill_icon_frames=prev_k,
        prev_role=prev_role,
    )
    self_color = update_self_color(atlas, frame)

    return ActorPercept(
        crewmates=scan_crewmates(atlas, frame),
        bodies=scan_bodies(atlas, frame),
        ghosts=scan_ghosts(atlas, frame),
        role_updated=role.role_updated,
        new_role=role.new_role,
        is_ghost=role.is_ghost,
        kill_ready=role.kill_ready,
        ghost_icon_frames=role.ghost_icon_frames,
        kill_icon_frames=role.kill_icon_frames,
        self_color_updated=self_color.updated,
        new_self_color=self_color.color_index,
    )
