#!/usr/bin/env python3
"""Bake precomputed pixel-paths for the guided_bot navigation graph.

Reads nav_graph.json and walk_mask.bin, computes A* paths between all
connected waypoint pairs (walking edges only), and writes nav_paths.bin.

Usage:
    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/tools/bake_nav.py

Output: perception/baked/nav_paths.bin

Binary format:
    Header:
        u32 num_edges
        u32 total_points
    Edge index (num_edges entries):
        u32 offset_into_points_array
        u16 num_points_in_this_path
        u16 src_waypoint_id
        u16 dst_waypoint_id
    Points array (total_points entries):
        [i16 x, i16 y] per point

    Points for edge i start at points[edge_index[i].offset] and contain
    edge_index[i].num_points entries. The path goes from src to dst
    (exclusive of src, inclusive of dst).

Also updates nav_graph.json with computed edge costs (walk distances).
"""

from __future__ import annotations

import heapq
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GUIDED_BOT_DIR = Path(__file__).resolve().parent.parent
BAKED_DIR = GUIDED_BOT_DIR / "perception" / "baked"
WALK_MASK_PATH = BAKED_DIR / "walk_mask.bin"
NAV_GRAPH_PATH = BAKED_DIR / "nav_graph.json"
NAV_PATHS_PATH = BAKED_DIR / "nav_paths.bin"

MAP_WIDTH = 952
MAP_HEIGHT = 534


# ---------------------------------------------------------------------------
# A* (unlimited, offline)
# ---------------------------------------------------------------------------


def astar(wm: np.ndarray, sx: int, sy: int, gx: int, gy: int
           ) -> list[tuple[int, int]] | None:
    """Full A* with no node cap. Returns path from step after start
    through goal inclusive, or None if unreachable.

    4-connected, unit cost, Manhattan heuristic.
    """
    if wm[sy, sx] == 0 or wm[gy, gx] == 0:
        return None
    if sx == gx and sy == gy:
        return []

    def h(x, y):
        return abs(x - gx) + abs(y - gy)

    start_idx = sy * MAP_WIDTH + sx
    goal_idx = gy * MAP_WIDTH + gx

    # Use flat arrays for performance on large searches
    area = MAP_WIDTH * MAP_HEIGHT
    costs = np.full(area, 0x7FFFFFFF, dtype=np.int32)
    parents = np.full(area, -2, dtype=np.int32)
    closed = np.zeros(area, dtype=np.bool_)

    costs[start_idx] = 0
    parents[start_idx] = -1
    heap = [(h(sx, sy), start_idx)]

    while heap:
        _, current = heapq.heappop(heap)
        if closed[current]:
            continue
        if current == goal_idx:
            # Reconstruct
            path = []
            step = goal_idx
            while step != start_idx and step >= 0:
                path.append((step % MAP_WIDTH, step // MAP_WIDTH))
                step = int(parents[step])
            path.reverse()
            return path

        closed[current] = True
        cx = current % MAP_WIDTH
        cy = current // MAP_WIDTH
        cur_cost = int(costs[current])

        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if nx < 0 or ny < 0 or nx >= MAP_WIDTH or ny >= MAP_HEIGHT:
                continue
            if wm[ny, nx] == 0:
                continue
            ni = ny * MAP_WIDTH + nx
            if closed[ni]:
                continue
            new_cost = cur_cost + 1
            if new_cost >= costs[ni]:
                continue
            costs[ni] = new_cost
            parents[ni] = current
            heapq.heappush(heap, (new_cost + h(nx, ny), ni))

    return None  # unreachable


# ---------------------------------------------------------------------------
# Path sampling (reduce point count for storage)
# ---------------------------------------------------------------------------


def _segment_walkable(wm: np.ndarray, x0: int, y0: int,
                      x1: int, y1: int) -> bool:
    """Check that every pixel on the line from (x0,y0) to (x1,y1) is walkable.

    Uses Bresenham-style stepping so no pixel is skipped. This prevents
    path simplification from creating segments that cut through walls.
    """
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    steps = max(dx, dy)
    if steps == 0:
        return wm[y0, x0] != 0
    for i in range(steps + 1):
        t = i / steps
        x = int(round(x0 + t * (x1 - x0)))
        y = int(round(y0 + t * (y1 - y0)))
        if x < 0 or y < 0 or x >= MAP_WIDTH or y >= MAP_HEIGHT:
            return False
        if wm[y, x] == 0:
            return False
    return True


def simplify_path(path: list[tuple[int, int]],
                  max_deviation: float = 1.5,
                  wm: np.ndarray | None = None) -> list[tuple[int, int]]:
    """Wall-aware Douglas-Peucker simplification.

    Keeps all points where either:
    - The simplified line deviates more than max_deviation pixels, OR
    - The straight-line segment between endpoints crosses a wall pixel.

    The second condition prevents the common failure mode where a path
    hugs a wall (1px deviation) and gets collapsed into a segment that
    cuts through the wall.
    """
    if len(path) <= 2:
        return path

    # Find point with maximum distance from line start->end
    sx, sy = path[0]
    ex, ey = path[-1]
    dx, dy = ex - sx, ey - sy
    line_len_sq = dx * dx + dy * dy

    max_dist = 0.0
    max_idx = 0

    for i in range(1, len(path) - 1):
        px, py = path[i]
        if line_len_sq == 0:
            dist = ((px - sx) ** 2 + (py - sy) ** 2) ** 0.5
        else:
            t = max(0, min(1, ((px - sx) * dx + (py - sy) * dy) / line_len_sq))
            proj_x = sx + t * dx
            proj_y = sy + t * dy
            dist = ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    # Only collapse if geometry is within tolerance AND the segment is
    # fully walkable (no wall pixels on the straight line).
    if max_dist <= max_deviation:
        if wm is None or _segment_walkable(wm, sx, sy, ex, ey):
            return [path[0], path[-1]]
        # Wall crossing detected — must subdivide even though geometry
        # is within tolerance. Split at the midpoint of the path to
        # force retention of intermediate waypoints.
        max_idx = len(path) // 2

    left = simplify_path(path[:max_idx + 1], max_deviation, wm)
    right = simplify_path(path[max_idx:], max_deviation, wm)
    return left[:-1] + right


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print(f"Loading walk mask from {WALK_MASK_PATH}...")
    wm = np.fromfile(WALK_MASK_PATH, dtype=np.uint8).reshape(MAP_HEIGHT, MAP_WIDTH)

    print(f"Loading nav graph from {NAV_GRAPH_PATH}...")
    with open(NAV_GRAPH_PATH) as f:
        graph_data = json.load(f)

    waypoints = {w["id"]: w for w in graph_data["waypoints"]}
    edges = graph_data["edges"]

    # Filter to walking edges only
    walking_edges = [e for e in edges if not e.get("is_vent", False)]
    print(f"Computing paths for {len(walking_edges)} walking edges...")

    paths: list[tuple[int, int, list[tuple[int, int]]]] = []
    failed = []
    total_points = 0

    t0 = time.time()
    for i, edge in enumerate(walking_edges):
        src_wp = waypoints[edge["src"]]
        dst_wp = waypoints[edge["dst"]]
        sx, sy = src_wp["x"], src_wp["y"]
        gx, gy = dst_wp["x"], dst_wp["y"]

        path = astar(wm, sx, sy, gx, gy)
        if path is None:
            failed.append((edge["src"], edge["dst"], src_wp.get("label", ""),
                           dst_wp.get("label", "")))
            # Store empty path
            paths.append((edge["src"], edge["dst"], []))
        else:
            # Simplify for storage (wall-aware to prevent segments crossing walls)
            simplified = simplify_path(path, max_deviation=1.0, wm=wm)
            paths.append((edge["src"], edge["dst"], simplified))
            total_points += len(simplified)
            # Update edge cost in graph data
            edge["cost"] = len(path)

        if (i + 1) % 50 == 0 or i == len(walking_edges) - 1:
            elapsed = time.time() - t0
            print(f"  [{i+1}/{len(walking_edges)}] "
                  f"{elapsed:.1f}s, {total_points} points so far")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Total paths: {len(paths)}")
    print(f"  Total points (simplified): {total_points}")
    print(f"  Failed (unreachable): {len(failed)}")

    if failed:
        print("\n  FAILED EDGES (unreachable on walk mask):")
        for src_id, dst_id, src_lbl, dst_lbl in failed[:10]:
            print(f"    {src_id}({src_lbl}) -> {dst_id}({dst_lbl})")
        if len(failed) > 10:
            print(f"    ... and {len(failed) - 10} more")

    # Write nav_paths.bin
    print(f"\nWriting {NAV_PATHS_PATH}...")
    _write_paths_bin(paths, total_points)

    # Update nav_graph.json with costs
    print(f"Updating {NAV_GRAPH_PATH} with edge costs...")
    with open(NAV_GRAPH_PATH, "w") as f:
        json.dump(graph_data, f, indent=2)

    # Stats
    if total_points > 0:
        raw_points = sum(edge.get("cost", 0) for edge in walking_edges)
        ratio = total_points / max(raw_points, 1)
        print(f"\n  Raw A* points: {raw_points}")
        print(f"  Simplified points: {total_points} ({ratio:.1%} of raw)")
        print(f"  File size: {NAV_PATHS_PATH.stat().st_size / 1024:.1f} KB")

    return 0 if not failed else 1


def _write_paths_bin(
    paths: list[tuple[int, int, list[tuple[int, int]]]],
    total_points: int
) -> None:
    """Write the binary nav_paths file."""
    num_edges = len(paths)

    with open(NAV_PATHS_PATH, "wb") as f:
        # Header: num_edges (u32), total_points (u32)
        f.write(struct.pack("<II", num_edges, total_points))

        # Edge index: for each edge, (offset u32, num_points u16, src u16, dst u16)
        offset = 0
        for src_id, dst_id, points in paths:
            f.write(struct.pack("<IHHH", offset, len(points), src_id, dst_id))
            offset += len(points)

        # Points array: [i16 x, i16 y] per point
        for _, _, points in paths:
            for x, y in points:
                f.write(struct.pack("<hh", x, y))


if __name__ == "__main__":
    sys.exit(main())
