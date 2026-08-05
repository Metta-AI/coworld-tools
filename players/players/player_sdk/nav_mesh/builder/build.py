"""Build a simple waypoint graph over a walkability mask.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original module ``swgy_tools.navmesh.build``).

Concepts adapted from a prior ``navgraph.c`` waypoint builder (lattice nodes with a
clearance filter, edges within EDGE_MAX with a clear corridor, euclidean edge
cost, single-component stitching) -- reimplemented in Python for Croatoan and
kept deliberately naive. The output is plain dicts ready for the JSON
interchange; the robust runtime model lives one package up (``nav_mesh.model``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np


@dataclass
class BuildParams:
    grid: int = 14  # node lattice spacing, px
    edge_max: int = 30  # longest edge, px
    node_clear: int = 0  # (2r+1)^2 clearance box required around a node
    edge_clear: int = 0  # +/- band perpendicular to an edge corridor


def _clear_box(mask: np.ndarray, x: int, y: int, r: int) -> bool:
    if r <= 0:
        return bool(mask[y, x])
    h, w = mask.shape
    if x - r < 0 or y - r < 0 or x + r >= w or y + r >= h:
        return False
    return bool(mask[y - r : y + r + 1, x - r : x + r + 1].all())


def _line_walkable(mask: np.ndarray, x0: int, y0: int, x1: int, y1: int, band: int) -> bool:
    """Bresenham corridor check: every pixel on the segment (+/- band) walkable."""
    h, w = mask.shape
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    # Band offset axis is perpendicular to the dominant travel axis.
    horizontal = dx >= -dy
    while True:
        for b in range(-band, band + 1):
            px, py = (x, y + b) if horizontal else (x + b, y)
            if px < 0 or px >= w or py < 0 or py >= h or not mask[py, px]:
                return False
        if x == x1 and y == y1:
            return True
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_graph(
    mask: np.ndarray,
    params: BuildParams,
    tagger: Callable[[int, int], set[str]] | None = None,
    seeds: Sequence[tuple[int, int, frozenset[str]]] = (),
) -> tuple[list[dict], list[dict]]:
    """Return (nodes, edges) as interchange-ready dicts.

    ``tagger(x, y)`` supplies semantic tags per node (e.g. room/vent/task);
    ``seeds`` are extra points (e.g. vent centers) added if walkable and not
    already covered by a nearby lattice node.
    """
    h, w = mask.shape
    tag = tagger or (lambda _x, _y: set())

    # 1. Lattice nodes on walkable, clearance-passing cells.
    coords: list[tuple[int, int]] = []
    tags: list[set[str]] = []
    for y in range(params.node_clear, h - params.node_clear, params.grid):
        for x in range(params.node_clear, w - params.node_clear, params.grid):
            if _clear_box(mask, x, y, params.node_clear):
                coords.append((x, y))
                tags.append(set(tag(x, y)))

    # 1b. Seed points (e.g. vent/room centers): add if walkable and not within
    #     grid/2 of an existing node; merge seed tags onto the chosen node.
    #     Task stations are an exception: distinct stations can sit closer than
    #     grid/2 to the same lattice node (and to each other), and each is its
    #     own objective, so task seeds only coalesce on near-exact coincidence --
    #     otherwise every station gets its own node.
    half = max(1, params.grid // 2)
    for sx, sy, seed_tags in seeds:
        if not (0 <= sx < w and 0 <= sy < h and mask[sy, sx]):
            continue
        thr = 2 if "task" in seed_tags else half
        near = next(
            (i for i, (x, y) in enumerate(coords) if abs(x - sx) <= thr and abs(y - sy) <= thr),
            None,
        )
        if near is not None:
            tags[near] |= set(seed_tags)
        else:
            coords.append((sx, sy))
            tags.append(set(tag(sx, sy)) | set(seed_tags))

    # 2. Edges between near nodes with a clear corridor, via spatial buckets.
    cell = max(1, params.edge_max)
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x, y) in enumerate(coords):
        buckets[(x // cell, y // cell)].append(i)

    uf = _UnionFind(len(coords))
    edges: list[dict] = []
    seen: set[tuple[int, int]] = set()
    max_sq = params.edge_max * params.edge_max
    for i, (xi, yi) in enumerate(coords):
        bx, by = xi // cell, yi // cell
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                for j in buckets.get((bx + ox, by + oy), ()):
                    if j <= i:
                        continue
                    xj, yj = coords[j]
                    d2 = (xi - xj) ** 2 + (yi - yj) ** 2
                    if d2 > max_sq:
                        continue
                    if not _line_walkable(mask, xi, yi, xj, yj, params.edge_clear):
                        continue
                    key = (i, j)
                    if key in seen:
                        continue
                    seen.add(key)
                    edges.append(
                        {
                            "src": i,
                            "dst": j,
                            "weight": math.sqrt(d2),
                            "directed": False,
                            "tags": ["walk"],
                        }
                    )
                    uf.union(i, j)

    # 3. Stitch components: connect the nearest clear cross-component pair until
    #    the walk graph is a single component (or no clear bridge remains).
    edges += _stitch(mask, coords, uf, params)

    # 4. Guarantee a single connected component. ``_stitch`` only bridges a
    #    straight clear segment, so components separated by a bent corridor stay
    #    apart; route a walkable path (pixel BFS) around the bend and insert the
    #    intermediate waypoints as nodes. Append-only -> existing ids unchanged,
    #    and a no-op when the graph is already connected.
    coords, tags, edges = _ensure_connected(mask, coords, tags, edges, tag, params)

    # 4b. Recover corridors the coarse lattice dropped. ``edge_max`` gates how far
    #     two nodes may connect, so a real corridor whose mouth is wider than
    #     edge_max (or whose nodes straddle a gap) yields only a single edge --
    #     coarsening then amputates whole paths (e.g. a room left with one exit
    #     instead of two). Add an edge for any clear walkable line up to ~2.5*grid
    #     when the graph currently forces a long detour between its ends; skip
    #     pairs already well connected so this never adds a false shortcut.
    coords, tags, edges = _add_missing_corridors(mask, coords, tags, edges, tag, params)

    # 5. Keep edges ~uniform (~grid). Stitch/route bridges can span a long clear
    #    corridor as a single edge; split any edge over edge_max into waypoint-
    #    spaced hops so "one edge ~= one move" stays honest for the sim's tick
    #    grid. Interior points lie on an already-clear segment -> walkable.
    coords, tags, edges = _subdivide_long_edges(mask, coords, tags, edges, tag, params)

    nodes = [{"id": i, "x": x, "y": y, "tags": sorted(tags[i])} for i, (x, y) in enumerate(coords)]
    return nodes, edges


def _stitch(
    mask: np.ndarray, coords: list[tuple[int, int]], uf: _UnionFind, params: BuildParams
) -> list[dict]:
    if not coords:
        return []
    pts = np.array(coords, dtype=np.int64)
    extra: list[dict] = []
    stalled: set[int] = set()  # component roots we couldn't bridge

    while True:
        roots = np.array([uf.find(i) for i in range(len(coords))])
        unique = [r for r in set(roots.tolist()) if r not in stalled]
        if len(set(roots.tolist())) <= 1 or len(unique) <= 1:
            break
        # Bridge the smallest live component to its nearest clear node elsewhere.
        sizes = {r: int((roots == r).sum()) for r in unique}
        target = min(sizes, key=lambda r: sizes[r])
        in_t = roots == target
        t_idx = np.flatnonzero(in_t)
        o_idx = np.flatnonzero(~in_t)
        bridged = False
        # Try target nodes by increasing distance to the other-component centroid.
        other_centroid = pts[o_idx].mean(axis=0)
        order = np.argsort(((pts[t_idx] - other_centroid) ** 2).sum(axis=1))
        for ti in t_idx[order]:
            d2 = ((pts[o_idx] - pts[ti]) ** 2).sum(axis=1)
            for oj in o_idx[np.argsort(d2)][:25]:  # nearest few candidates
                xi, yi = coords[ti]
                xj, yj = coords[oj]
                if _line_walkable(mask, xi, yi, xj, yj, params.edge_clear):
                    extra.append(
                        {
                            "src": int(ti),
                            "dst": int(oj),
                            "weight": math.dist((xi, yi), (xj, yj)),
                            "directed": False,
                            "tags": ["walk", "stitch"],
                        }
                    )
                    uf.union(int(ti), int(oj))
                    bridged = True
                    break
            if bridged:
                break
        if not bridged:
            stalled.add(target)  # give up on this island; avoid infinite loop
    return extra


def _component_labels(n: int, edges: list[dict]) -> list[int]:
    """Union-find component id (0..) per node index, from the edge list."""
    uf = _UnionFind(n)
    for e in edges:
        uf.union(e["src"], e["dst"])
    roots = [uf.find(i) for i in range(n)]
    remap: dict[int, int] = {}
    return [remap.setdefault(r, len(remap)) for r in roots]


def _nearest_walkable(mask: np.ndarray, x: int, y: int, step: int) -> tuple[int, int] | None:
    """Nearest strided cell to ``(x, y)`` whose pixel is walkable (spiral search)."""
    h, w = mask.shape
    x0, y0 = x - x % step, y - y % step
    for r in range(0, max(h, w), step):
        for dy in range(-r, r + 1, step):
            for dx in range(-r, r + 1, step):
                if max(abs(dx), abs(dy)) != r:
                    continue  # ring only
                cx, cy = x0 + dx, y0 + dy
                if 0 <= cx < w and 0 <= cy < h and mask[cy, cx]:
                    return cx, cy
    return None


def _bfs_route(
    mask: np.ndarray, p0: tuple[int, int], p1: tuple[int, int], step: int, band: int
) -> list[tuple[int, int]] | None:
    """Walkable polyline ``p0 -> p1`` via 8-connected BFS on a strided lattice.

    Coarsened by ``step`` for speed; each lattice hop must be corridor-clear so
    the route never clips a wall. Returns the pixel waypoints (endpoints exact)
    or ``None`` if no walkable route exists (the walk mask is one region, so this
    only happens for genuinely unreachable seeds).
    """
    h, w = mask.shape
    s = _nearest_walkable(mask, p0[0], p0[1], step)
    t = _nearest_walkable(mask, p1[0], p1[1], step)
    if s is None or t is None:
        return None
    nbrs = [
        (step, 0),
        (-step, 0),
        (0, step),
        (0, -step),
        (step, step),
        (step, -step),
        (-step, step),
        (-step, -step),
    ]
    parent: dict[tuple[int, int], tuple[int, int] | None] = {s: None}
    q = deque([s])
    while q:
        cur = q.popleft()
        if cur == t:
            break
        cx, cy = cur
        for dx, dy in nbrs:
            nx, ny = cx + dx, cy + dy
            nxt = (nx, ny)
            if nxt in parent or not (0 <= nx < w and 0 <= ny < h) or not mask[ny, nx]:
                continue
            if not _line_walkable(mask, cx, cy, nx, ny, band):
                continue
            parent[nxt] = cur
            q.append(nxt)
    if t not in parent:
        return None
    chain: list[tuple[int, int]] = []
    node: tuple[int, int] | None = t
    while node is not None:
        chain.append(node)
        node = parent[node]
    chain.reverse()
    chain[0] = p0  # snap endpoints back to the exact node coords
    chain[-1] = p1
    return chain


def _simplify_path(
    mask: np.ndarray, path: list[tuple[int, int]], band: int
) -> list[tuple[int, int]]:
    """Greedy line-of-sight reduction: longest clear straight segments."""
    if len(path) <= 2:
        return path
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not _line_walkable(mask, *path[i], *path[j], band):
            j -= 1
        out.append(path[j])
        i = j
    return out


def _ensure_connected(
    mask: np.ndarray,
    coords: list[tuple[int, int]],
    tags: list[set[str]],
    edges: list[dict],
    tagger: Callable[[int, int], set[str]],
    params: BuildParams,
) -> tuple[list[tuple[int, int]], list[set[str]], list[dict]]:
    """Force the walk graph into one component by routing waypoint bridges.

    Repeatedly connects the largest component to its nearest other component via
    a walkable BFS route (around bends ``_stitch`` cannot bridge), inserting the
    route's interior waypoints as new nodes. Append-only; returns the (possibly
    extended) coords/tags/edges. No-op when already connected, so existing
    callers and connected fixtures are unaffected.
    """
    step = max(2, params.grid // 4)
    guard = 0
    while True:
        labels = _component_labels(len(coords), edges)
        groups: dict[int, list[int]] = defaultdict(list)
        for i, c in enumerate(labels):
            groups[c].append(i)
        if len(groups) <= 1:
            return coords, tags, edges
        guard += 1
        if guard > len(coords) + 8:  # safety: never loop forever
            return coords, tags, edges
        pts = np.array(coords, dtype=np.int64)
        order = sorted(groups.values(), key=len, reverse=True)
        main = np.array(order[0])
        # nearest (other-node, main-node) pair across all remaining components
        best: tuple[float, int, int] | None = None
        for comp in order[1:]:
            for oi in comp:
                d2 = ((pts[main] - pts[oi]) ** 2).sum(axis=1)
                k = int(np.argmin(d2))
                dd = float(d2[k])
                if best is None or dd < best[0]:
                    best = (dd, oi, int(main[k]))
        assert best is not None
        _, oi, mj = best
        route = _bfs_route(mask, coords[oi], coords[mj], step, params.edge_clear)
        wpts = _simplify_path(mask, route, params.edge_clear) if route else [coords[oi], coords[mj]]
        chain = [oi]
        for x, y in wpts[1:-1]:
            chain.append(len(coords))
            coords.append((int(x), int(y)))
            tags.append(set(tagger(int(x), int(y))))
        chain.append(mj)
        for a, b in zip(chain, chain[1:]):
            xa, ya = coords[a]
            xb, yb = coords[b]
            edges.append(
                {
                    "src": int(a),
                    "dst": int(b),
                    "weight": math.dist((xa, ya), (xb, yb)),
                    "directed": False,
                    "tags": ["walk", "stitch", "route"],
                }
            )


def _subdivide_long_edges(
    mask: np.ndarray,
    coords: list[tuple[int, int]],
    tags: list[set[str]],
    edges: list[dict],
    tagger: Callable[[int, int], set[str]],
    params: BuildParams,
) -> tuple[list[tuple[int, int]], list[set[str]], list[dict]]:
    """Split edges longer than ``edge_max`` into ~grid-length waypoint hops.

    Only bridges (stitch/route) exceed ``edge_max``; they are straight clear
    segments, so linearly-interpolated interior points are walkable. Keeps the
    edge-length distribution tight around ``grid`` so the sim's one-edge = one-
    tick model stays calibrated. No-op for graphs whose edges are all short.
    """
    limit = params.edge_max * 1.25
    out: list[dict] = []
    for e in edges:
        a, b = e["src"], e["dst"]
        xa, ya = coords[a]
        xb, yb = coords[b]
        d = math.dist((xa, ya), (xb, yb))
        if d <= limit:
            out.append(e)
            continue
        n = int(d // params.edge_max)  # interior points -> n+1 hops of ~edge_max
        prev = a
        for k in range(1, n + 1):
            f = k / (n + 1)
            x = int(round(xa + (xb - xa) * f))
            y = int(round(ya + (yb - ya) * f))
            nid = len(coords)
            coords.append((x, y))
            tags.append(set(tagger(x, y)))
            px, py = coords[prev]
            out.append(
                {
                    "src": int(prev),
                    "dst": int(nid),
                    "weight": math.dist((px, py), (x, y)),
                    "directed": False,
                    "tags": list(e["tags"]),
                }
            )
            prev = nid
        px, py = coords[prev]
        out.append(
            {
                "src": int(prev),
                "dst": int(b),
                "weight": math.dist((px, py), (xb, yb)),
                "directed": False,
                "tags": list(e["tags"]),
            }
        )
    return coords, tags, out


def _reachable_within(adj: dict[int, set[int]], src: int, dst: int, cutoff: int) -> bool:
    """BFS: is ``dst`` reachable from ``src`` within ``cutoff`` hops?"""
    seen = {src}
    frontier = [src]
    for _ in range(cutoff):
        nxt: list[int] = []
        for u in frontier:
            for v in adj[u]:
                if v == dst:
                    return True
                if v not in seen:
                    seen.add(v)
                    nxt.append(v)
        if not nxt:
            break
        frontier = nxt
    return False


def _add_missing_corridors(
    mask: np.ndarray,
    coords: list[tuple[int, int]],
    tags: list[set[str]],
    edges: list[dict],
    tagger: Callable[[int, int], set[str]],
    params: BuildParams,
) -> tuple[list[tuple[int, int]], list[set[str]], list[dict]]:
    """Reconnect node pairs that are physically near (Euclid (edge_max, 2.5*grid])
    but graph-distant, when a fairly direct WALKABLE ROUTE exists between them --
    a real corridor the coarse lattice dropped (its mouth wider than edge_max, or
    bent so no straight segment fits). Routes around bends via pixel BFS and
    inserts the waypoints. Skips pairs already reachable in ~direct hops, and
    routes that detour far (>1.6x the straight line), so it restores missing
    paths without adding false shortcuts. Returns extended coords/tags/edges.
    """
    n = len(coords)
    if n == 0:
        return coords, tags, edges
    adj: dict[int, set[int]] = defaultdict(set)
    for e in edges:
        adj[e["src"]].add(e["dst"])
        adj[e["dst"]].add(e["src"])
    lo = params.edge_max
    hi = 2.5 * params.grid
    grid = max(1, params.grid)
    step = max(2, params.grid // 4)
    cell = max(1, int(hi))
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x, y) in enumerate(coords):
        buckets[(x // cell, y // cell)].append(i)
    for i in range(n):
        xi, yi = coords[i]
        bx, by = xi // cell, yi // cell
        cand: list[int] = []
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                cand += buckets.get((bx + ox, by + oy), ())
        for j in cand:
            if j <= i or j in adj[i]:
                continue
            xj, yj = coords[j]
            d = math.dist((xi, yi), (xj, yj))
            if d <= lo or d > hi:
                continue
            # already well connected (short graph path)? -> not a dropped corridor
            if _reachable_within(adj, i, j, int(d / grid) + 4):
                continue
            route = _bfs_route(mask, (xi, yi), (xj, yj), step, params.edge_clear)
            if route is None:
                continue
            wpts = _simplify_path(mask, route, params.edge_clear)
            rlen = sum(math.dist(wpts[k], wpts[k + 1]) for k in range(len(wpts) - 1))
            if rlen > 1.6 * d:  # routes the long way -> genuinely separate, not a corridor
                continue
            chain = [i]
            for x, y in wpts[1:-1]:
                nid = len(coords)
                coords.append((int(x), int(y)))
                tags.append(set(tagger(int(x), int(y))))
                chain.append(nid)
            chain.append(j)
            for a, b in zip(chain, chain[1:]):
                xa, ya = coords[a]
                xb, yb = coords[b]
                edges.append(
                    {
                        "src": int(a),
                        "dst": int(b),
                        "weight": math.dist((xa, ya), (xb, yb)),
                        "directed": False,
                        "tags": ["walk", "corridor"],
                    }
                )
                adj[a].add(b)
                adj[b].add(a)
    return coords, tags, edges
