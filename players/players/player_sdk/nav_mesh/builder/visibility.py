"""Compute per-node visibility coefficients under an engine's line-of-sight.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (swgy-crewrift;
original module ``swgy_tools.navmesh.visibility``). The screen-frame
constants are parameterized into :class:`SightParams`; the defaults are the
byte-faithful reference-engine profile the original validated against.

The reference engine decides what a player sees with a per-pixel integer DDA
raycast against the **wall layer** (distinct from walkability), clamped to a
``frame`` x ``frame`` screen window centred on the player. Visibility is
binary, has no radius beyond the frame, and is identical for all agents. We
replicate that predicate offline and turn it into two coefficients per nav
node:

- ``exposure`` in ``[0, 1]``: how much walkable floor is visible from the node,
  normalised against the most-open node on the map. Low = enclosed = good place
  to be caught unseen / cornered alone. Since line-of-sight is ~symmetric, "floor
  I can see" is a proxy for "floor a witness could see me from".
- ``witnesses``: how many *other* nodes have line-of-sight to the node -- the
  discrete vantage points a witness could occupy.

This stays independent of the runtime ``nav_mesh`` model (it works on
interchange node dicts + the wall/walk masks); the interchange is the
boundary. numpy + stdlib only.

Faithfulness notes (matched the reference engine bit-for-bit):
- The raycast origin's *screen* position is a constant for every node; the ray
  geometry is shared and precomputed once.
- Integer division is **truncate-toward-zero** (Nim ``div``), not Python floor --
  it diverges on up/left rays (the ``_tdiv`` detail, validated against the live
  engine).
- A step that leaves the map blocks the ray (the engine treats out-of-bounds as
  occluded).
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SightParams:
    """The screen-frame geometry of the engine's line-of-sight.

    Defaults are the reference profile of the origin engine (crewrift
    ``sim.nim``): a 128x128 view whose raycast origin sits at screen
    ``(60, 66)`` -- derived there as ``SCREEN//2 - SPRITE_SIZE//2 +
    SPRITE_DRAW_OFF_{X,Y}`` = ``64 - 6 + 2`` / ``64 - 6 + 8`` with
    ``SPRITE_DRAW_OFF_X=2, SPRITE_DRAW_OFF_Y=8, SPRITE_SIZE=12``. Supply your
    own frame size / origin for a different engine.
    """

    frame: int = 128
    """View window is ``frame`` x ``frame`` pixels, centred on the viewer."""

    origin: tuple[int, int] = (60, 66)
    """The viewer's constant position within the screen frame ``(x, y)``."""


_DEFAULT_SIGHT = SightParams()


def _tdiv(n, d):
    """Truncate-toward-zero integer division (Nim ``div``); ``d`` > 0.

    Works on Python ints or numpy int arrays. Python ``//`` floors toward -inf,
    which desyncs from the engine on negative numerators (up/left rays).
    """
    q = np.abs(n) // d
    return np.where(n < 0, -q, q)


@dataclass(frozen=True)
class RayTemplates:
    """Screen-ray geometry shared by every node (precomputed once).

    ``offx``/``offy`` are ``(max_steps, n_pixels)`` int32 step offsets *relative
    to the node's world position*: step ``i`` of the ray to screen pixel ``p``
    samples world ``(node_x + offx[i, p], node_y + offy[i, p])``. Rows past a
    pixel's true step count repeat its target (a harmless no-op for the OR that
    detects the first occluder). ``sxrel``/``syrel`` are each pixel's own offset
    (the ray endpoint), used to test whether that screen pixel is walkable floor.
    """

    offx: np.ndarray
    offy: np.ndarray
    sxrel: np.ndarray
    syrel: np.ndarray


def build_ray_templates(sight: SightParams = _DEFAULT_SIGHT) -> RayTemplates:
    """Build the constant per-pixel DDA ray geometry for the sight frame."""
    screen = sight.frame
    osx, osy = sight.origin
    p = np.arange(screen * screen)
    sy, sx = np.divmod(p, screen)  # row-major screen pixel
    dx = (sx - osx).astype(np.int64)
    dy = (sy - osy).astype(np.int64)
    steps = np.maximum(np.abs(dx), np.abs(dy))
    denom = np.maximum(steps, 1)
    max_steps = int(steps.max())

    offx = np.empty((max_steps, p.size), dtype=np.int32)
    offy = np.empty((max_steps, p.size), dtype=np.int32)
    for i in range(max_steps):
        eff = np.minimum(i + 1, steps)  # clamp to target once past the last step
        offx[i] = _tdiv(dx * eff, denom)
        offy[i] = _tdiv(dy * eff, denom)
    return RayTemplates(
        offx=offx,
        offy=offy,
        sxrel=dx.astype(np.int32),
        syrel=dy.astype(np.int32),
    )


def _visible_buffer(
    px: int, py: int, wall_flat: np.ndarray, w: int, h: int, t: RayTemplates
) -> np.ndarray:
    """Boolean ``(n_pixels,)`` of which screen pixels are visible from ``(px, py)``."""
    wx = px + t.offx  # (max_steps, n_pixels)
    wy = py + t.offy
    inb = (wx >= 0) & (wx < w) & (wy >= 0) & (wy < h)
    idx = np.where(inb, wy * w + wx, 0)
    hit = wall_flat[idx] & inb  # wall pixel reached in-bounds
    blocked = (hit | ~inb).any(axis=0)  # any step occluded or off-map
    return ~blocked


def _visible_floor_count(
    px: int, py: int, wall_flat, walk_flat, w: int, h: int, t: RayTemplates
) -> int:
    """Number of walkable screen pixels with clear line-of-sight from ``(px, py)``."""
    visible = _visible_buffer(px, py, wall_flat, w, h, t)
    wxs = px + t.sxrel
    wys = py + t.syrel
    inb = (wxs >= 0) & (wxs < w) & (wys >= 0) & (wys < h)
    walkable = np.zeros(wxs.shape, dtype=bool)
    walkable[inb] = walk_flat[wys[inb] * w + wxs[inb]]
    return int((visible & walkable).sum())


def is_visible(
    px: int,
    py: int,
    tx: int,
    ty: int,
    wall: np.ndarray,
    sight: SightParams = _DEFAULT_SIGHT,
) -> bool:
    """True iff a viewer at ``(px, py)`` can see world point ``(tx, ty)``.

    Engine-exact single-ray predicate: the target must lie in the viewer's
    sight frame and the truncate-toward-zero DDA ray from the viewer must hit
    no wall (and stay on the map).
    """
    screen = sight.frame
    osx, osy = sight.origin
    h, w = wall.shape
    cam_x = px - osx
    cam_y = py - osy
    sx = tx - cam_x
    sy = ty - cam_y
    if not (0 <= sx < screen and 0 <= sy < screen):
        return False
    dx = sx - osx
    dy = sy - osy
    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return True
    for step in range(1, steps + 1):
        rx = osx + (abs(dx * step) // steps) * (1 if dx >= 0 else -1)
        ry = osy + (abs(dy * step) // steps) * (1 if dy >= 0 else -1)
        mx = cam_x + rx
        my = cam_y + ry
        if mx < 0 or my < 0 or mx >= w or my >= h:
            return False
        if wall[my, mx]:
            return False
    return True


# --- parallel exposure over nodes -----------------------------------------

# Per-worker globals (populated once via the pool initializer; never pickled
# per task). Read-only after init.
_G: dict = {}


def _worker_init(wall_flat, walk_flat, w, h, offx, offy, sxrel, syrel) -> None:
    _G["wall_flat"] = wall_flat
    _G["walk_flat"] = walk_flat
    _G["w"] = w
    _G["h"] = h
    _G["t"] = RayTemplates(offx=offx, offy=offy, sxrel=sxrel, syrel=syrel)


def _worker_chunk(coords: list[tuple[int, int]]) -> list[int]:
    return [
        _visible_floor_count(x, y, _G["wall_flat"], _G["walk_flat"], _G["w"], _G["h"], _G["t"])
        for x, y in coords
    ]


def _chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def exposure_counts(
    coords: list[tuple[int, int]],
    wall: np.ndarray,
    walk: np.ndarray,
    templates: RayTemplates,
    workers: int = 1,
) -> list[int]:
    """Visible-walkable-pixel count per node, parallelised across ``workers``.

    ``workers <= 1`` runs inline (no pool) so it stays debuggable; otherwise the
    node list is chunked across a ``ProcessPoolExecutor`` whose workers each hold
    the read-only masks + ray templates (shared via the pool initializer).
    """
    h, w = wall.shape
    wall_flat = np.ascontiguousarray(wall).reshape(-1)
    walk_flat = np.ascontiguousarray(walk).reshape(-1)

    if workers <= 1 or len(coords) < 2:
        return [
            _visible_floor_count(x, y, wall_flat, walk_flat, w, h, templates) for x, y in coords
        ]

    # ~4 chunks per worker keeps the queue balanced without per-node overhead.
    chunk = max(1, len(coords) // (workers * 4))
    chunks = list(_chunked(coords, chunk))
    init_args = (
        wall_flat,
        walk_flat,
        w,
        h,
        templates.offx,
        templates.offy,
        templates.sxrel,
        templates.syrel,
    )
    out: list[int] = []
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_worker_init, initargs=init_args
    ) as ex:
        for part in ex.map(_worker_chunk, chunks):
            out.extend(part)
    return out


def witness_counts(
    coords: list[tuple[int, int]],
    wall: np.ndarray,
    sight: SightParams = _DEFAULT_SIGHT,
) -> list[int]:
    """For each node, how many *other* nodes have line-of-sight to it.

    A viewer at ``M`` can witness node ``N`` iff ``N`` is in ``M``'s frame and the
    ray ``M -> N`` is clear. Only nodes within the centred sight frame can qualify,
    so pairs are pruned by a bounding box before the exact predicate.
    """
    screen = sight.frame
    xs = np.array([c[0] for c in coords], dtype=np.int64)
    ys = np.array([c[1] for c in coords], dtype=np.int64)
    counts = [0] * len(coords)
    for i, (nx, ny) in enumerate(coords):
        near = (xs > nx - screen) & (xs < nx + screen) & (ys > ny - screen) & (ys < ny + screen)
        near[i] = False
        c = 0
        for j in np.nonzero(near)[0]:
            if is_visible(int(xs[j]), int(ys[j]), nx, ny, wall, sight):
                c += 1
        counts[i] = c
    return counts


def _vis_worker_init(wall, xs, ys, sight) -> None:
    _G["wall"] = wall
    _G["xs"] = xs
    _G["ys"] = ys
    _G["sight"] = sight


def _vis_worker_rows(idxs: list[int]) -> list[tuple[int, np.ndarray]]:
    wall = _G["wall"]
    xs = _G["xs"]
    ys = _G["ys"]
    sight = _G["sight"]
    screen = sight.frame
    n = len(xs)
    out: list[tuple[int, np.ndarray]] = []
    for i in idxs:
        xi, yi = int(xs[i]), int(ys[i])
        row = np.zeros(n, dtype=bool)
        # Only targets inside the centred sight frame can ever be visible -> cull
        # the far pairs before the exact ray test (same prune as witness_counts).
        cand = np.nonzero((np.abs(xs - xi) < screen) & (np.abs(ys - yi) < screen))[0]
        for j in cand:
            j = int(j)
            row[j] = i == j or is_visible(xi, yi, int(xs[j]), int(ys[j]), wall, sight)
        out.append((i, row))
    return out


def visibility_matrix(
    coords: list[tuple[int, int]],
    wall: np.ndarray,
    workers: int | None = None,
    sight: SightParams = _DEFAULT_SIGHT,
) -> np.ndarray:
    """Pairwise node visibility ``[n, n]`` under the engine line-of-sight.

    ``vis[i, j]`` is True iff a viewer at node ``i`` can see node ``j`` (engine
    ``is_visible``; diagonal True). Frame-limited and ~symmetric but stored full
    because the ``_tdiv`` truncation can differ by ray direction.
    """
    if workers is None:
        workers = os.cpu_count() or 1
    n = len(coords)
    xs = np.array([c[0] for c in coords], dtype=np.int64)
    ys = np.array([c[1] for c in coords], dtype=np.int64)
    mat = np.zeros((n, n), dtype=bool)

    if workers <= 1 or n < 64:
        _vis_worker_init(wall, xs, ys, sight)
        for i, row in _vis_worker_rows(list(range(n))):
            mat[i] = row
        return mat

    chunk = max(1, n // (workers * 4))
    chunks = [list(range(i, min(i + chunk, n))) for i in range(0, n, chunk)]
    with ProcessPoolExecutor(
        max_workers=workers, initializer=_vis_worker_init, initargs=(wall, xs, ys, sight)
    ) as ex:
        for part in ex.map(_vis_worker_rows, chunks):
            for i, row in part:
                mat[i] = row
    return mat


def enrich_nodes(
    nodes: list[dict],
    wall: np.ndarray,
    walk: np.ndarray,
    workers: int | None = None,
    sight: SightParams = _DEFAULT_SIGHT,
) -> tuple[list[dict], dict]:
    """Return node dicts with ``exposure`` (0..1) and ``witnesses`` (int) added.

    ``exposure`` is the visible-floor count normalised by the most-open node
    (``1.0`` = most exposed spot on the map). Returns ``(enriched_nodes, stats)``;
    ``stats`` records the raw normaliser for provenance. ``workers`` defaults to
    the CPU count.
    """
    if workers is None:
        workers = os.cpu_count() or 1
    coords = [(int(n["x"]), int(n["y"])) for n in nodes]
    templates = build_ray_templates(sight)

    raw = exposure_counts(coords, wall, walk, templates, workers=workers)
    witnesses = witness_counts(coords, wall, sight)
    max_raw = max(raw) if raw else 0
    denom = max_raw or 1

    enriched = []
    for n, r, wcount in zip(nodes, raw, witnesses):
        nn = dict(n)
        nn["exposure"] = round(r / denom, 6)
        nn["witnesses"] = int(wcount)
        enriched.append(nn)

    stats = {
        "exposure_raw_max": int(max_raw),
        "exposure_norm": "visible-floor px / most-open node",
        "wall_px": int(wall.sum()),
        "workers": int(workers),
    }
    return enriched, stats
