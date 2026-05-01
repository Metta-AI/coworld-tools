"""Actor sprite scanners: crewmates, bodies, ghosts, HUD role icon, task icons, radar dots.

Port of ``actors.nim``. All scanners read a 128×128 ``uint8`` frame and
write into :class:`~modulabot.state.Perception` sub-record lists.

Performance: the per-anchor scanners
(:func:`scan_crewmates`, :func:`scan_bodies`, :func:`scan_ghosts`) use
the vectorised all-anchor matcher
(:func:`~modulabot.sprite_match.match_actor_sprite_all_anchors`) so a
full :func:`scan_all` completes in a handful of milliseconds instead
of several hundred. See the module docstring in
:mod:`~modulabot.sprite_match` for the vectorisation notes.

See :mod:`modulabot.perception.localize` for the camera lock that makes
:func:`scan_task_icons` usable; without a camera, we can't project
world task positions to screen space.
"""

from __future__ import annotations

import numpy as np

from . import nim_perception as _nim_perception
from .data import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPRITE_SIZE,
    Sprites,
)
from .frame import KILL_ICON_X, KILL_ICON_Y, RADAR_TASK_COLOR
from .geometry import PLAYER_SCREEN_X, PLAYER_SCREEN_Y
from .sprite_match import (
    CREWMATE_MAX_MISSES,
    CREWMATE_MIN_BODY_PIXELS,
    CREWMATE_MIN_STABLE_PIXELS,
    crewmate_color_index,
    match_actor_sprite_all_anchors,
    matches_crewmate,
    matches_sprite,
    matches_sprite_shadowed,
    sprite_misses,
)
from .state import (
    BodyMatch,
    Bot,
    CrewmateMatch,
    GhostMatch,
    IconMatch,
    RadarDotMatch,
    Role,
)

# Tunables from actors.nim.
GHOST_ICON_MAX_MISSES = 3
GHOST_ICON_FRAME_THRESHOLD = 2
RADAR_PERIPHERY_MARGIN = 1
CREWMATE_SEARCH_RADIUS = 1
BODY_SEARCH_RADIUS = 1
BODY_MAX_MISSES = 9
BODY_MIN_STABLE_PIXELS = 6
BODY_MIN_TINT_PIXELS = 6
GHOST_SEARCH_RADIUS = 1
GHOST_MAX_MISSES = 9
GHOST_MIN_STABLE_PIXELS = 6
GHOST_MIN_TINT_PIXELS = 6
TASK_ICON_EXPECTED_SEARCH_RADIUS = 3
PLAYER_IGNORE_RADIUS = 9  # v2 duplicate; kept local to avoid cross-module coupling


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------


def _add_icon_match(matches: list[IconMatch], x: int, y: int) -> None:
    for m in matches:
        if abs(m.x - x) <= 1 and abs(m.y - y) <= 1:
            return
    matches.append(IconMatch(x=x, y=y))


def _dedup_anchors(ys: np.ndarray, xs: np.ndarray, radius: int) -> list[tuple[int, int]]:
    """Filter overlapping ``(y, x)`` anchors with a greedy radius sweep.

    Matches the per-anchor ``abs(m.x - x) <= radius`` dedup rule the
    scalar scanners used to enforce as they appended matches. We scan
    in raster order (ascending y, then x) so two bots running the
    vectorised vs. scalar paths over the same frame return anchors in
    the same order.

    For typical frames each scanner yields <20 accepted anchors, so
    the O(N²) sweep is fine — on the order of 400 comparisons, all
    scalar arithmetic.
    """
    out: list[tuple[int, int]] = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        keep = True
        for oy, ox in out:
            if abs(ox - x) <= radius and abs(oy - y) <= radius:
                keep = False
                break
        if keep:
            out.append((int(y), int(x)))
    return out


# ---------------------------------------------------------------------------
# Role detection from the HUD kill/ghost icon slot
# ---------------------------------------------------------------------------


def update_role(bot: Bot, sprites: Sprites, frame: np.ndarray) -> None:
    """Infer ``role`` / ``is_ghost`` / ``imposter.kill_ready`` from the HUD icon.

    The icon lives at a fixed (KILL_ICON_X, KILL_ICON_Y) slot. Match against
    the ghost icon first (priority signal); then, if not ghost, against
    the kill button (both lit and shadowed variants).
    """
    ghost_misses, ghost_opaque = sprite_misses(frame, sprites.ghost_icon, KILL_ICON_X, KILL_ICON_Y)
    if ghost_opaque > 0 and ghost_misses <= GHOST_ICON_MAX_MISSES:
        bot.ghost_icon_frames += 1
        bot.imposter.kill_ready = False
        if bot.ghost_icon_frames >= GHOST_ICON_FRAME_THRESHOLD:
            bot.is_ghost = True
            if bot.role == Role.UNKNOWN:
                bot.role = Role.CREWMATE
        return
    if not bot.is_ghost:
        bot.ghost_icon_frames = 0

    lit = matches_sprite(frame, sprites.kill_button, KILL_ICON_X, KILL_ICON_Y)
    shaded = matches_sprite_shadowed(frame, sprites.kill_button, KILL_ICON_X, KILL_ICON_Y)
    bot.imposter.kill_ready = lit
    if lit or shaded:
        bot.role = Role.IMPOSTER
    elif bot.role == Role.UNKNOWN:
        bot.role = Role.CREWMATE


def update_self_color(bot: Bot, sprites: Sprites, frame: np.ndarray) -> None:
    """Infer our own colour from the centred player sprite.

    Single-anchor check — uses the scalar matcher directly rather than
    the vectorised all-anchor version. Running the 117×117 pass for
    one known anchor would be ~60× more work.
    """
    sprite = sprites.player
    x = PLAYER_SCREEN_X - sprite.width // 2
    y = PLAYER_SCREEN_Y - sprite.height // 2
    color_index = -1
    if matches_crewmate(frame, sprite, x, y, False):
        color_index = crewmate_color_index(frame, sprite, x, y, False)
    elif matches_crewmate(frame, sprite, x, y, True):
        color_index = crewmate_color_index(frame, sprite, x, y, True)
    if 0 <= color_index:
        bot.identity.self_color = color_index


# ---------------------------------------------------------------------------
# Actor scans (vectorised)
# ---------------------------------------------------------------------------


def _scan_actor(
    frame: np.ndarray,
    sprite,
    *,
    flips: tuple[bool, ...],
    max_misses: int,
    min_stable_pixels: int,
    min_tint_pixels: int,
    dedup_radius: int,
    ignore_center: bool = False,
) -> list[tuple[int, int, bool]]:
    """Return ``[(y, x, flip_h), ...]`` anchors accepted by the matcher.

    Shared backbone for :func:`scan_crewmates`, :func:`scan_bodies`,
    and :func:`scan_ghosts`. Runs the vectorised all-anchor matcher
    once per ``flip_h`` orientation, unions the accept masks, and
    dedups overlapping anchors.

    When ``ignore_center`` is set, anchors whose centre falls within
    :data:`PLAYER_IGNORE_RADIUS` of screen centre are zeroed out before
    dedup — matches the "don't report self as a neighbouring crewmate"
    rule the scalar scanner used.
    """
    per_flip_accepts: list[tuple[bool, np.ndarray]] = []
    for flip_h in flips:
        accept = match_actor_sprite_all_anchors(
            frame,
            sprite,
            flip_h,
            max_misses=max_misses,
            min_stable_pixels=min_stable_pixels,
            min_tint_pixels=min_tint_pixels,
        )
        per_flip_accepts.append((flip_h, accept))

    # Zero out the self-sprite exclusion zone if requested.
    if ignore_center:
        max_y, max_x = per_flip_accepts[0][1].shape
        # Anchor (y, x) maps to sprite centre (y + sh//2, x + sw//2).
        # We want to exclude anchors whose centre is within
        # PLAYER_IGNORE_RADIUS of PLAYER_SCREEN_X/Y.
        ys = np.arange(max_y).reshape(-1, 1)
        xs = np.arange(max_x).reshape(1, -1)
        centre_y = ys + SPRITE_SIZE // 2
        centre_x = xs + SPRITE_SIZE // 2
        near_self = (np.abs(centre_x - PLAYER_SCREEN_X) <= PLAYER_IGNORE_RADIUS) & (
            np.abs(centre_y - PLAYER_SCREEN_Y) <= PLAYER_IGNORE_RADIUS
        )
        per_flip_accepts = [(f, a & ~near_self) for f, a in per_flip_accepts]

    # Each anchor position is reported at most once per frame, preferring
    # the first orientation in ``flips``. This matches the scalar scanner's
    # ``break`` after a match on the first flip.
    claimed = np.zeros_like(per_flip_accepts[0][1], dtype=bool)
    raw: list[tuple[int, int, bool]] = []
    for flip_h, accept in per_flip_accepts:
        accept = accept & ~claimed
        ys, xs = np.nonzero(accept)
        for y, x in zip(ys.tolist(), xs.tolist()):
            raw.append((int(y), int(x), flip_h))
        claimed |= accept

    # Dedup overlapping anchors across flips. We walk in raster order
    # (y asc, x asc) regardless of which flip contributed the anchor
    # — same behaviour as the scalar scanner's linear sweep.
    raw.sort(key=lambda t: (t[0], t[1]))
    kept: list[tuple[int, int, bool]] = []
    for y, x, flip_h in raw:
        collision = False
        for ky, kx, _ in kept:
            if abs(ky - y) <= dedup_radius and abs(kx - x) <= dedup_radius:
                collision = True
                break
        if not collision:
            kept.append((y, x, flip_h))
    return kept


def scan_crewmates(bot: Bot, sprites: Sprites, frame: np.ndarray) -> None:
    """Populate ``bot.percep.visible_crewmates`` via the vectorised matcher.

    Excludes the self-sprite zone around screen centre so we don't
    double-report self. Tint colour is inferred per accepted anchor
    via the scalar :func:`~modulabot.sprite_match.crewmate_color_index`
    — running the vectorised all-anchor variant to read back at ~3
    positions would be wasted work.
    """
    bot.percep.visible_crewmates.clear()
    sprite = sprites.player
    anchors = _scan_actor(
        frame,
        sprite,
        flips=(False, True),
        max_misses=CREWMATE_MAX_MISSES,
        min_stable_pixels=CREWMATE_MIN_STABLE_PIXELS,
        min_tint_pixels=CREWMATE_MIN_BODY_PIXELS,
        dedup_radius=CREWMATE_SEARCH_RADIUS,
        ignore_center=True,
    )
    for y, x, flip_h in anchors:
        ci = crewmate_color_index(frame, sprite, x, y, flip_h)
        bot.percep.visible_crewmates.append(
            CrewmateMatch(x=x, y=y, color_index=ci, flip_h=flip_h)
        )
    for cm in bot.percep.visible_crewmates:
        if 0 <= cm.color_index:
            bot.identity.last_seen[cm.color_index] = bot.percep.tick


def scan_bodies(bot: Bot, sprites: Sprites, frame: np.ndarray) -> None:
    """Populate ``bot.percep.visible_bodies`` via the vectorised matcher."""
    bot.percep.visible_bodies.clear()
    sprite = sprites.body
    anchors = _scan_actor(
        frame,
        sprite,
        flips=(False,),  # bodies in the Nim bot only scan the unflipped sprite
        max_misses=BODY_MAX_MISSES,
        min_stable_pixels=BODY_MIN_STABLE_PIXELS,
        min_tint_pixels=BODY_MIN_TINT_PIXELS,
        dedup_radius=BODY_SEARCH_RADIUS,
    )
    for y, x, _flip in anchors:
        ci = crewmate_color_index(frame, sprite, x, y, False)
        bot.percep.visible_bodies.append(BodyMatch(x=x, y=y, color_index=ci))


def scan_ghosts(bot: Bot, sprites: Sprites, frame: np.ndarray) -> None:
    """Populate ``bot.percep.visible_ghosts`` via the vectorised matcher."""
    bot.percep.visible_ghosts.clear()
    sprite = sprites.ghost
    anchors = _scan_actor(
        frame,
        sprite,
        flips=(False, True),
        max_misses=GHOST_MAX_MISSES,
        min_stable_pixels=GHOST_MIN_STABLE_PIXELS,
        min_tint_pixels=GHOST_MIN_TINT_PIXELS,
        dedup_radius=GHOST_SEARCH_RADIUS,
    )
    for y, x, flip_h in anchors:
        bot.percep.visible_ghosts.append(GhostMatch(x=x, y=y, flip_h=flip_h))


# Keyed-on-id cache of the ``(N, 4) int32`` task rect array.
# Building the array is O(N) and the result is read-only, so it's
# safe to share across every scanner call for a given GameMap. One
# map per process → effectively permanent.
_TASK_COORDS_CACHE: dict[int, np.ndarray] = {}


def _task_coords_for(game_map) -> np.ndarray:
    """Return (and lazily build) the ``(N, 4) int32`` task-rect array.

    Matches the ``(x, y, w, h)`` layout the Nim FFI expects. Cached
    on first call and never invalidated — the map is immutable.
    """
    key = id(game_map)
    arr = _TASK_COORDS_CACHE.get(key)
    if arr is None:
        arr = np.array(
            [(t.x, t.y, t.w, t.h) for t in game_map.tasks],
            dtype=np.int32,
        )
        _TASK_COORDS_CACHE[key] = arr
    return arr


def scan_task_icons(bot: Bot, sprites: Sprites, frame: np.ndarray, game_map) -> None:
    """Scan expected task-icon positions given a locked camera.

    Dispatches to the Nim bulk kernel when :data:`nim_perception.
    HAVE_NATIVE`, else walks the same search grid in Python. Both
    paths produce identical ``bot.percep.visible_task_icons`` lists
    (pinned by :class:`tests.test_nim_perception.ScanTaskIconsParityTests`).

    No-op when ``bot.percep.localized`` is False — task icon positions
    in screen space depend on the camera, and without a lock they'd
    just be noise.
    """
    bot.percep.visible_task_icons.clear()
    if not bot.percep.localized:
        return
    sprite = sprites.task
    cam_x = bot.percep.camera_x
    cam_y = bot.percep.camera_y

    if _nim_perception.HAVE_NATIVE:
        task_coords = _task_coords_for(game_map)
        matches = _nim_perception.scan_task_icons(
            frame,
            sprite.pixels,
            task_coords,
            cam_x,
            cam_y,
            search_radius=TASK_ICON_EXPECTED_SEARCH_RADIUS,
        )
        for x, y in matches:
            bot.percep.visible_task_icons.append(IconMatch(x=x, y=y))
        return

    # Pure-Python fallback: same scan pattern the Nim kernel mirrors.
    for task in game_map.tasks:
        base_x = task.x + task.w // 2 - SPRITE_SIZE // 2 - cam_x
        base_y = task.y - SPRITE_SIZE - 2 - cam_y
        for bob_y in (-1, 0, 1):
            expected_y = base_y + bob_y
            for dy in range(-TASK_ICON_EXPECTED_SEARCH_RADIUS, TASK_ICON_EXPECTED_SEARCH_RADIUS + 1):
                for dx in range(-TASK_ICON_EXPECTED_SEARCH_RADIUS, TASK_ICON_EXPECTED_SEARCH_RADIUS + 1):
                    x = base_x + dx
                    y = expected_y + dy
                    if matches_sprite(frame, sprite, x, y):
                        _add_icon_match(bot.percep.visible_task_icons, x, y)


# ---------------------------------------------------------------------------
# Radar dots (vectorised)
# ---------------------------------------------------------------------------


def _is_radar_periphery(x: int, y: int) -> bool:
    return (
        x <= RADAR_PERIPHERY_MARGIN
        or y <= RADAR_PERIPHERY_MARGIN
        or x >= SCREEN_WIDTH - 1 - RADAR_PERIPHERY_MARGIN
        or y >= SCREEN_HEIGHT - 1 - RADAR_PERIPHERY_MARGIN
    )


def scan_radar_dots(bot: Bot, frame: np.ndarray) -> None:
    """Populate ``bot.percep.radar_dots`` from the screen-edge radar pixels.

    Vectorised: identifies all radar-coloured pixels in the periphery
    ring in one numpy pass, then dedupes adjacent matches.
    """
    bot.percep.radar_dots.clear()
    mask = frame == RADAR_TASK_COLOR
    # Periphery ring.
    periphery = np.zeros_like(mask, dtype=bool)
    m = RADAR_PERIPHERY_MARGIN
    periphery[: m + 1, :] = True
    periphery[-(m + 1) :, :] = True
    periphery[:, : m + 1] = True
    periphery[:, -(m + 1) :] = True
    ys, xs = np.nonzero(mask & periphery)
    # Adjacent radar pixels collapse to a single dot; raster-order sweep
    # matches the scalar helper the actors previously used.
    for dy, dx in _dedup_anchors(ys, xs, radius=1):
        bot.percep.radar_dots.append(RadarDotMatch(x=int(dx), y=int(dy)))


# ---------------------------------------------------------------------------
# Top-level orchestrator for actor scans
# ---------------------------------------------------------------------------


def scan_all(bot: Bot, sprites: Sprites, frame: np.ndarray, game_map) -> None:
    """Run every actor scan in sequence.

    Order matches the Nim bot (role → self → bodies → ghosts → crewmates
    → task icons, with imposters skipping task icons since they don't do
    real tasks). Radar dots are scanned separately because they don't
    depend on any earlier scan.

    Short-circuits on interstitial frames — mostly-black screens match
    too many sprite anchors because the body/ghost sprites are
    dominated by the black outline pixel. Nim does the same gate.
    """
    from .frame import looks_like_interstitial
    if looks_like_interstitial(frame):
        bot.percep.visible_crewmates.clear()
        bot.percep.visible_bodies.clear()
        bot.percep.visible_ghosts.clear()
        bot.percep.visible_task_icons.clear()
        bot.percep.radar_dots.clear()
        return

    update_role(bot, sprites, frame)
    update_self_color(bot, sprites, frame)
    scan_bodies(bot, sprites, frame)
    scan_ghosts(bot, sprites, frame)
    scan_crewmates(bot, sprites, frame)
    if bot.role == Role.IMPOSTER and not bot.is_ghost:
        bot.percep.visible_task_icons.clear()
    else:
        scan_task_icons(bot, sprites, frame, game_map)
    scan_radar_dots(bot, frame)


__all__ = [
    "update_role",
    "update_self_color",
    "scan_crewmates",
    "scan_bodies",
    "scan_ghosts",
    "scan_task_icons",
    "scan_radar_dots",
    "scan_all",
    "GHOST_ICON_FRAME_THRESHOLD",
    "GHOST_ICON_MAX_MISSES",
]
