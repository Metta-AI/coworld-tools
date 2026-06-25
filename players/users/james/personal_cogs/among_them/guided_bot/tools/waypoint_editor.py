#!/usr/bin/env python3
"""Waypoint graph editor for the guided_bot navigation system.

Displays the walk mask, auto-suggests waypoints at key locations
(doorways, task stations, vents, intersections), and allows manual
creation/editing/removal of waypoints and edges.

Usage:
    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/tools/waypoint_editor.py

Controls:
    Left click (empty space)  — Add new waypoint at cursor
    Left click (on waypoint)  — Select waypoint (also starts drag)
    Left drag (on waypoint)   — Move waypoint (snaps to walkable)
    Right click (on waypoint) — Delete waypoint and its edges
    Middle drag / Ctrl+drag   — Pan the view
    Scroll wheel              — Zoom in/out

    'e'        — Create edge between the two selected waypoints
    'x'        — Delete edge between the two selected waypoints
    'd'        — Disconnect: remove ALL edges from selected waypoint(s)
    'a'        — Auto-suggest waypoints (tasks, vents, rooms, doorways)
    'c'        — Auto-connect edges (BFS reachability)
    'v'        — Validate graph connectivity (prints to console)
    's'        — Save to nav_graph.json
    'l'        — Load from nav_graph.json
    Escape     — Clear selection
    'q'        — Quit

    '1'-'7'    — Set waypoint kind for next placement:
                 1=doorway, 2=intersection, 3=task, 4=vent,
                 5=button, 6=home, 7=poi

Requires: pygame, numpy, Pillow
"""

from __future__ import annotations

import json
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pygame

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GUIDED_BOT_DIR = Path(__file__).resolve().parent.parent
BAKED_DIR = GUIDED_BOT_DIR / "perception" / "baked"
WALK_MASK_PATH = BAKED_DIR / "walk_mask.bin"
MAP_JSON_PATH = BAKED_DIR / "map.json"
NAV_GRAPH_PATH = BAKED_DIR / "nav_graph.json"

MAP_WIDTH = 952
MAP_HEIGHT = 534

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

WAYPOINT_KINDS = [
    "doorway",       # 1
    "intersection",  # 2
    "task",          # 3
    "vent",          # 4
    "button",        # 5
    "home",          # 6
    "poi",           # 7
]

KIND_COLORS = {
    "doorway": (255, 136, 0),
    "intersection": (255, 255, 0),
    "task": (0, 255, 0),
    "vent": (255, 0, 255),
    "button": (255, 0, 0),
    "home": (0, 255, 255),
    "poi": (255, 255, 255),
}


@dataclass
class Waypoint:
    id: int
    x: int
    y: int
    kind: str = "poi"
    room: str = ""
    label: str = ""
    vent_group: str = ""
    vent_index: int = 0


@dataclass
class Edge:
    src: int
    dst: int
    is_vent: bool = False
    vent_group: str = ""


@dataclass
class NavGraphData:
    waypoints: list[Waypoint] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    next_id: int = 0

    def add_waypoint(self, x: int, y: int, kind: str = "poi", **kwargs) -> Waypoint:
        wp = Waypoint(id=self.next_id, x=x, y=y, kind=kind, **kwargs)
        self.waypoints.append(wp)
        self.next_id += 1
        return wp

    def remove_waypoint(self, wp_id: int) -> None:
        self.waypoints = [w for w in self.waypoints if w.id != wp_id]
        self.edges = [e for e in self.edges if e.src != wp_id and e.dst != wp_id]

    def add_edge(self, src: int, dst: int, is_vent: bool = False,
                 vent_group: str = "") -> Edge | None:
        for e in self.edges:
            if (e.src == src and e.dst == dst) or (e.src == dst and e.dst == src):
                return None
        edge = Edge(src=src, dst=dst, is_vent=is_vent, vent_group=vent_group)
        self.edges.append(edge)
        return edge

    def remove_edge(self, src: int, dst: int) -> bool:
        before = len(self.edges)
        self.edges = [
            e for e in self.edges
            if not ((e.src == src and e.dst == dst) or
                    (e.src == dst and e.dst == src))
        ]
        return len(self.edges) < before

    def get_waypoint(self, wp_id: int) -> Waypoint | None:
        for w in self.waypoints:
            if w.id == wp_id:
                return w
        return None

    def waypoint_at(self, x: int, y: int, radius: int = 8) -> Waypoint | None:
        best = None
        best_dist = radius + 1
        for w in self.waypoints:
            d = abs(w.x - x) + abs(w.y - y)
            if d < best_dist:
                best = w
                best_dist = d
        return best

    def to_json(self) -> dict:
        return {
            "version": 1,
            "waypoints": [
                {
                    "id": w.id,
                    "x": w.x,
                    "y": w.y,
                    "kind": w.kind,
                    "room": w.room,
                    "label": w.label,
                    **({"vent_group": w.vent_group, "vent_index": w.vent_index}
                       if w.kind == "vent" else {}),
                }
                for w in self.waypoints
            ],
            "edges": [
                {
                    "src": e.src,
                    "dst": e.dst,
                    **({"is_vent": True, "vent_group": e.vent_group}
                       if e.is_vent else {}),
                }
                for e in self.edges
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "NavGraphData":
        graph = cls()
        for w in data.get("waypoints", []):
            wp = Waypoint(
                id=w["id"], x=w["x"], y=w["y"],
                kind=w.get("kind", "poi"),
                room=w.get("room", ""),
                label=w.get("label", ""),
                vent_group=w.get("vent_group", ""),
                vent_index=w.get("vent_index", 0),
            )
            graph.waypoints.append(wp)
            graph.next_id = max(graph.next_id, wp.id + 1)
        for e in data.get("edges", []):
            graph.edges.append(Edge(
                src=e["src"], dst=e["dst"],
                is_vent=e.get("is_vent", False),
                vent_group=e.get("vent_group", ""),
            ))
        return graph


# ---------------------------------------------------------------------------
# Map data
# ---------------------------------------------------------------------------


def load_walk_mask() -> np.ndarray:
    raw = np.fromfile(WALK_MASK_PATH, dtype=np.uint8)
    return raw.reshape(MAP_HEIGHT, MAP_WIDTH)


def load_map_json() -> dict:
    with open(MAP_JSON_PATH) as f:
        return json.load(f)


def walk_mask_to_surface(wm: np.ndarray) -> pygame.Surface:
    """Convert walk mask to a pygame surface."""
    img = np.zeros((MAP_HEIGHT, MAP_WIDTH, 3), dtype=np.uint8)
    img[wm != 0] = [40, 50, 55]   # walkable
    img[wm == 0] = [15, 15, 20]   # walls
    return pygame.surfarray.make_surface(img.transpose(1, 0, 2))


def find_room_for_point(map_data: dict, x: int, y: int) -> str:
    for room in map_data.get("rooms", []):
        if (room["x"] <= x < room["x"] + room["w"] and
                room["y"] <= y < room["y"] + room["h"]):
            return room["name"]
    return ""


def snap_to_walkable(wm: np.ndarray, x: int, y: int,
                     radius: int = 40) -> tuple[int, int]:
    """Find nearest walkable pixel to (x, y)."""
    if 0 <= y < MAP_HEIGHT and 0 <= x < MAP_WIDTH and wm[y, x] != 0:
        return x, y
    for r in range(1, radius + 1):
        for dx in range(-r, r + 1):
            dy = r - abs(dx)
            for sign in [-1, 1]:
                ny, nx = y + sign * dy, x + dx
                if 0 <= ny < MAP_HEIGHT and 0 <= nx < MAP_WIDTH and wm[ny, nx] != 0:
                    return nx, ny
                if dy == 0:
                    break
    return x, y


# ---------------------------------------------------------------------------
# Auto-suggestion
# ---------------------------------------------------------------------------


def auto_suggest_waypoints(wm: np.ndarray, map_data: dict) -> NavGraphData:
    """Generate initial waypoint suggestions from map data."""
    graph = NavGraphData()

    # Home
    home = map_data.get("home", {})
    if home:
        hx, hy = snap_to_walkable(wm, home["x"], home["y"])
        graph.add_waypoint(hx, hy, kind="home", label="home",
                           room=find_room_for_point(map_data, hx, hy))

    # Emergency button
    button = map_data.get("button", {})
    if button:
        bx = button["x"] + button["w"] // 2
        by = button["y"] + button["h"] // 2
        bx, by = snap_to_walkable(wm, bx, by)
        graph.add_waypoint(bx, by, kind="button", label="emergency_button",
                           room=find_room_for_point(map_data, bx, by))

    # Task stations
    for task in map_data.get("tasks", []):
        tx = task["x"] + task["w"] // 2
        ty = task["y"] + task["h"] // 2
        tx, ty = snap_to_walkable(wm, tx, ty)
        name = task.get("name", f"task_{len(graph.waypoints)}")
        graph.add_waypoint(tx, ty, kind="task", label=name,
                           room=find_room_for_point(map_data, tx, ty))

    # Vents
    for vent in map_data.get("vents", []):
        vx = vent["x"] + vent["w"] // 2
        vy = vent["y"] + vent["h"] // 2
        vx, vy = snap_to_walkable(wm, vx, vy)
        label = f"vent_{vent['group']}{vent['groupIndex']}"
        graph.add_waypoint(vx, vy, kind="vent", label=label,
                           room=find_room_for_point(map_data, vx, vy),
                           vent_group=vent["group"],
                           vent_index=vent["groupIndex"])

    # Room centers (for rooms without a nearby waypoint)
    for room in map_data.get("rooms", []):
        cx = room["x"] + room["w"] // 2
        cy = room["y"] + room["h"] // 2
        cx, cy = snap_to_walkable(wm, cx, cy)
        existing = graph.waypoint_at(cx, cy, radius=30)
        if existing is None:
            is_hallway = "hallway" in room["name"].lower() or "bend" in room["name"].lower()
            kind = "doorway" if is_hallway else "intersection"
            graph.add_waypoint(cx, cy, kind=kind,
                               label=room["name"].lower().replace(" ", "_"),
                               room=room["name"])

    return graph


def auto_connect_edges(graph: NavGraphData, wm: np.ndarray,
                       max_distance: int = 350,
                       max_edges_per_node: int = 6) -> int:
    """Auto-connect waypoints via BFS reachability. Returns edges added.

    For each waypoint, finds all reachable waypoints within max_distance
    walk-steps, then keeps only the closest max_edges_per_node neighbors
    that pass the wall-intersection / directness filter. This produces a
    sparse graph suitable for navigation without redundant long shortcuts.
    """
    added = 0

    # Vent edges (same group, sequential)
    vent_wps = [w for w in graph.waypoints if w.kind == "vent"]
    for group_char in set(w.vent_group for w in vent_wps):
        group = sorted([w for w in vent_wps if w.vent_group == group_char],
                       key=lambda w: w.vent_index)
        for i in range(len(group)):
            nxt = (i + 1) % len(group)
            e = graph.add_edge(group[i].id, group[nxt].id,
                               is_vent=True, vent_group=group_char)
            if e:
                added += 1

    # Walking edges: BFS from each waypoint, keep K nearest valid neighbors
    wp_positions = np.array([(w.x, w.y) for w in graph.waypoints], dtype=np.int32)

    # Collect candidate edges with distances, then filter
    candidate_edges: dict[tuple[int, int], int] = {}  # (min_id, max_id) -> walk_dist

    for i, w1 in enumerate(graph.waypoints):
        if wm[w1.y, w1.x] == 0:
            continue
        reachable = _bfs_to_waypoints(wm, w1.x, w1.y, wp_positions, max_distance)
        # Sort by distance, take nearest K that pass filter
        reachable.sort(key=lambda x: x[1])
        kept = 0
        for j, dist in reachable:
            if kept >= max_edges_per_node:
                break
            w2 = graph.waypoints[j]
            if (w1.kind == "vent" and w2.kind == "vent" and
                    w1.vent_group == w2.vent_group):
                continue

            # Filter: keep if has LOS, is short, or has low detour ratio
            has_los = not _line_crosses_wall(wm, w1.x, w1.y, w2.x, w2.y)
            is_short = dist <= 100
            manhattan = abs(w1.x - w2.x) + abs(w1.y - w2.y)
            detour_ratio = dist / max(manhattan, 1)
            low_detour = detour_ratio < 1.5

            if has_los or is_short or low_detour:
                key = (min(w1.id, w2.id), max(w1.id, w2.id))
                if key not in candidate_edges or dist < candidate_edges[key]:
                    candidate_edges[key] = dist
                kept += 1

    # Add all candidate edges to the graph
    for (src, dst), dist in candidate_edges.items():
        e = graph.add_edge(src, dst)
        if e:
            added += 1

    return added


def _line_crosses_wall(wm: np.ndarray, x0: int, y0: int,
                       x1: int, y1: int) -> bool:
    """Bresenham line test: returns True if any pixel on the line from
    (x0,y0) to (x1,y1) is impassable (wall).

    Uses a 1-pixel-wide line. This is a conservative test — if the
    straight line crosses a wall, the edge is rejected (the path would
    need to detour around it anyway, so the edge is not useful for
    direct navigation).
    """
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0

    while True:
        if x < 0 or y < 0 or x >= MAP_WIDTH or y >= MAP_HEIGHT:
            return True  # out of bounds = wall
        if wm[y, x] == 0:
            return True  # hit a wall
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy

    return False


def _bfs_to_waypoints(wm: np.ndarray, sx: int, sy: int,
                      wp_positions: np.ndarray,
                      max_dist: int) -> list[tuple[int, int]]:
    """BFS from (sx, sy), return (waypoint_index, distance) for each
    waypoint reached within max_dist."""
    visited = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.bool_)
    visited[sy, sx] = True
    queue = deque([(sx, sy, 0)])
    results: list[tuple[int, int]] = []

    # Build target set
    targets: dict[tuple[int, int], int] = {}
    for idx in range(len(wp_positions)):
        wx, wy = int(wp_positions[idx, 0]), int(wp_positions[idx, 1])
        if abs(wx - sx) + abs(wy - sy) <= max_dist * 2:
            targets[(wx, wy)] = idx

    while queue:
        x, y, d = queue.popleft()
        if d >= max_dist:
            continue
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= MAP_WIDTH or ny >= MAP_HEIGHT:
                continue
            if visited[ny, nx]:
                continue
            if wm[ny, nx] == 0:
                continue
            visited[ny, nx] = True
            nd = d + 1
            key = (nx, ny)
            if key in targets:
                results.append((targets.pop(key), nd))
            queue.append((nx, ny, nd))

    return results


def validate_connectivity(graph: NavGraphData) -> tuple[bool, str]:
    """Check all waypoints reachable from home via walking edges."""
    if not graph.waypoints:
        return False, "No waypoints."

    home_wps = [w for w in graph.waypoints if w.kind == "home"]
    root = home_wps[0].id if home_wps else graph.waypoints[0].id

    adj: dict[int, set[int]] = {w.id: set() for w in graph.waypoints}
    for e in graph.edges:
        if not e.is_vent:
            adj.setdefault(e.src, set()).add(e.dst)
            adj.setdefault(e.dst, set()).add(e.src)

    visited = set()
    queue = [root]
    visited.add(root)
    while queue:
        node = queue.pop(0)
        for nb in adj.get(node, set()):
            if nb not in visited:
                visited.add(nb)
                queue.append(nb)

    all_ids = {w.id for w in graph.waypoints}
    unreachable = all_ids - visited
    if unreachable:
        labels = []
        for wp_id in sorted(unreachable):
            wp = graph.get_waypoint(wp_id)
            if wp:
                labels.append(f"{wp.label}@({wp.x},{wp.y})")
        return False, f"{len(unreachable)} unreachable: {', '.join(labels[:8])}"

    return True, f"All {len(graph.waypoints)} connected ({len(graph.edges)} edges)."


# ---------------------------------------------------------------------------
# Pygame editor
# ---------------------------------------------------------------------------

WINDOW_W = 1400
WINDOW_H = 850
TOOLBAR_H = 36
FPS = 30


class WaypointEditor:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Guided Bot — Waypoint Editor")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("menlo", 11)
        self.font_sm = pygame.font.SysFont("menlo", 9)

        # Load data
        self.wm = load_walk_mask()
        self.map_data = load_map_json()
        self.map_surface = walk_mask_to_surface(self.wm)
        self.graph = NavGraphData()

        # View
        self.zoom = 1.5
        self.cam_x = 0.0  # world offset of screen top-left
        self.cam_y = 0.0

        # Interaction
        self.selected: list[int] = []
        self.dragging_wp: Waypoint | None = None
        self.panning = False
        self.pan_anchor = (0, 0)
        self.place_kind = "poi"
        self.status = "Ready. 'a'=auto-suggest, 's'=save, 'l'=load"

        # Load existing graph if present
        if NAV_GRAPH_PATH.exists():
            self._load_graph()

    # --- Coordinate transforms ---

    def world_to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        sx = int((wx - self.cam_x) * self.zoom)
        sy = int((wy - self.cam_y) * self.zoom) + TOOLBAR_H
        return sx, sy

    def screen_to_world(self, sx: int, sy: int) -> tuple[int, int]:
        wx = int(sx / self.zoom + self.cam_x)
        wy = int((sy - TOOLBAR_H) / self.zoom + self.cam_y)
        return wx, wy

    # --- Rendering ---

    def render(self):
        self.screen.fill((20, 20, 25))
        sw, sh = self.screen.get_size()

        # Map
        scaled_w = int(MAP_WIDTH * self.zoom)
        scaled_h = int(MAP_HEIGHT * self.zoom)
        if scaled_w > 0 and scaled_h > 0:
            scaled = pygame.transform.scale(self.map_surface, (scaled_w, scaled_h))
            ox = int(-self.cam_x * self.zoom)
            oy = int(-self.cam_y * self.zoom) + TOOLBAR_H
            self.screen.blit(scaled, (ox, oy))

            # Room outlines
            for room in self.map_data.get("rooms", []):
                rx, ry = self.world_to_screen(room["x"], room["y"])
                rw = int(room["w"] * self.zoom)
                rh = int(room["h"] * self.zoom)
                pygame.draw.rect(self.screen, (50, 50, 60),
                                 (rx, ry, rw, rh), 1)

        # Edges
        for edge in self.graph.edges:
            w1 = self.graph.get_waypoint(edge.src)
            w2 = self.graph.get_waypoint(edge.dst)
            if w1 and w2:
                p1 = self.world_to_screen(w1.x, w1.y)
                p2 = self.world_to_screen(w2.x, w2.y)
                color = (170, 0, 170) if edge.is_vent else (60, 90, 120)
                width = 2 if edge.is_vent else 1
                pygame.draw.line(self.screen, color, p1, p2, width)

        # Waypoints
        for wp in self.graph.waypoints:
            sx, sy = self.world_to_screen(wp.x, wp.y)
            r = max(3, int(4 * self.zoom))
            color = KIND_COLORS.get(wp.kind, (255, 255, 255))
            if wp.id in self.selected:
                pygame.draw.circle(self.screen, (255, 255, 255),
                                   (sx, sy), r + 3, 2)
            pygame.draw.circle(self.screen, color, (sx, sy), r)
            # Label
            if self.zoom >= 1.0 and wp.label:
                lbl = self.font_sm.render(wp.label[:20], True, (150, 150, 150))
                self.screen.blit(lbl, (sx + r + 2, sy - 5))

        # Toolbar
        pygame.draw.rect(self.screen, (40, 40, 45), (0, 0, sw, TOOLBAR_H))
        # Kind indicator
        kind_color = KIND_COLORS.get(self.place_kind, (255, 255, 255))
        kind_text = self.font.render(
            f"Kind: {self.place_kind} (1-7)", True, kind_color)
        self.screen.blit(kind_text, (10, 10))

        # Stats
        stats = self.font.render(
            f"WP:{len(self.graph.waypoints)} E:{len(self.graph.edges)} "
            f"Zoom:{self.zoom:.1f} Sel:{self.selected}",
            True, (180, 180, 180))
        self.screen.blit(stats, (200, 10))

        # Status bar
        status_surf = self.font.render(self.status, True, (160, 200, 160))
        self.screen.blit(status_surf, (10, sh - 20))

        pygame.display.flip()

    # --- Event loop ---

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self._handle_mouse_down(event)
                elif event.type == pygame.MOUSEBUTTONUP:
                    self._handle_mouse_up(event)
                elif event.type == pygame.MOUSEMOTION:
                    self._handle_mouse_motion(event)
                elif event.type == pygame.KEYDOWN:
                    self._handle_key(event)
                elif event.type == pygame.MOUSEWHEEL:
                    self._handle_scroll(event)

            self.render()
            self.clock.tick(FPS)

        pygame.quit()

    def _handle_mouse_down(self, event):
        mx, my = event.pos
        if my < TOOLBAR_H:
            return

        wx, wy = self.screen_to_world(mx, my)

        # Middle button or ctrl+left = pan
        if event.button == 2 or (event.button == 1 and
                                  pygame.key.get_mods() & pygame.KMOD_CTRL):
            self.panning = True
            self.pan_anchor = (mx, my)
            return

        # Right click = delete
        if event.button == 3:
            hit = self.graph.waypoint_at(wx, wy, radius=int(10 / self.zoom) + 4)
            if hit:
                self.graph.remove_waypoint(hit.id)
                if hit.id in self.selected:
                    self.selected.remove(hit.id)
                self.status = f"Deleted waypoint {hit.id} ({hit.label})"
            return

        # Left click
        if event.button == 1:
            hit = self.graph.waypoint_at(wx, wy, radius=int(10 / self.zoom) + 4)
            if hit:
                # Select; only start drag if waypoint is movable
                locked_kinds = ("task", "vent", "button", "home")
                if hit.kind not in locked_kinds:
                    self.dragging_wp = hit
                else:
                    self.dragging_wp = None
                if hit.id in self.selected:
                    pass  # already selected, allow drag
                else:
                    self.selected.append(hit.id)
                    if len(self.selected) > 2:
                        self.selected = self.selected[-2:]
                # Status feedback
                if len(self.selected) == 2:
                    w1 = self.graph.get_waypoint(self.selected[0])
                    w2 = self.graph.get_waypoint(self.selected[1])
                    self.status = (
                        f"2 selected: {w1.label}, {w2.label} — "
                        f"'e'=add edge, 'x'=remove edge, 'd'=disconnect")
                else:
                    lock_note = " [locked]" if hit.kind in locked_kinds else " — drag to move"
                    self.status = (
                        f"Selected: {hit.label} ({hit.kind}) @ ({hit.x},{hit.y})"
                        f"{lock_note} — click another for edge")
            else:
                # Add new waypoint
                if 0 <= wx < MAP_WIDTH and 0 <= wy < MAP_HEIGHT:
                    wx, wy = snap_to_walkable(self.wm, wx, wy)
                    room = find_room_for_point(self.map_data, wx, wy)
                    wp = self.graph.add_waypoint(wx, wy, kind=self.place_kind,
                                                 room=room)
                    self.selected = [wp.id]
                    self.status = f"Added {wp.kind} @ ({wp.x},{wp.y}) room={room}"

    def _handle_mouse_up(self, event):
        if event.button == 2 or (event.button == 1 and self.panning):
            self.panning = False
        if event.button == 1:
            self.dragging_wp = None

    def _handle_mouse_motion(self, event):
        mx, my = event.pos
        if self.panning:
            dx = mx - self.pan_anchor[0]
            dy = my - self.pan_anchor[1]
            self.cam_x -= dx / self.zoom
            self.cam_y -= dy / self.zoom
            self.pan_anchor = (mx, my)
        elif self.dragging_wp:
            wx, wy = self.screen_to_world(mx, my)
            wx = max(0, min(MAP_WIDTH - 1, wx))
            wy = max(0, min(MAP_HEIGHT - 1, wy))
            # Larger snap radius during drag for better UX
            wx, wy = snap_to_walkable(self.wm, wx, wy, radius=30)
            self.dragging_wp.x = wx
            self.dragging_wp.y = wy
            self.dragging_wp.room = find_room_for_point(self.map_data, wx, wy)
            self.status = f"Moving {self.dragging_wp.label} -> ({wx},{wy})"

    def _handle_scroll(self, event):
        mx, my = pygame.mouse.get_pos()
        # World point under cursor before zoom
        old_wx, old_wy = self.screen_to_world(mx, my)
        factor = 1.15 if event.y > 0 else 1 / 1.15
        self.zoom = max(0.3, min(6.0, self.zoom * factor))
        # Adjust cam so world point stays under cursor
        new_wx, new_wy = self.screen_to_world(mx, my)
        self.cam_x += old_wx - new_wx
        self.cam_y += old_wy - new_wy

    def _handle_key(self, event):
        key = event.key

        if key == pygame.K_ESCAPE:
            self.selected = []
            self.status = "Selection cleared."
        elif key == pygame.K_q:
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        elif key == pygame.K_e:
            self._create_edge()
        elif key == pygame.K_x:
            self._delete_edge()
        elif key == pygame.K_d:
            self._disconnect_node()
        elif key == pygame.K_a:
            self._auto_suggest()
        elif key == pygame.K_c:
            self._auto_connect()
        elif key == pygame.K_v:
            self._validate()
        elif key == pygame.K_s:
            self._save_graph()
        elif key == pygame.K_l:
            self._load_graph()
        elif key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
                     pygame.K_5, pygame.K_6, pygame.K_7):
            idx = key - pygame.K_1
            self.place_kind = WAYPOINT_KINDS[idx]
            self.status = f"Placement kind: {self.place_kind}"

    # --- Actions ---

    def _create_edge(self):
        if len(self.selected) == 2:
            src, dst = self.selected
            w1 = self.graph.get_waypoint(src)
            w2 = self.graph.get_waypoint(dst)
            if w1 and w2:
                is_vent = (w1.kind == "vent" and w2.kind == "vent" and
                           w1.vent_group == w2.vent_group)
                vent_group = w1.vent_group if is_vent else ""
                e = self.graph.add_edge(src, dst, is_vent=is_vent,
                                        vent_group=vent_group)
                if e:
                    self.status = f"Edge added: {w1.label} <-> {w2.label}"
                else:
                    self.status = "Edge already exists between those two."
        else:
            self.status = "Select 2 waypoints (click each), then press 'e' to connect."

    def _delete_edge(self):
        if len(self.selected) == 2:
            src, dst = self.selected
            if self.graph.remove_edge(src, dst):
                self.status = f"Edge removed: {src} <-> {dst}"
            else:
                self.status = "No edge between selected waypoints."
        else:
            self.status = "Select 2 waypoints, then press 'x' to remove edge."

    def _disconnect_node(self):
        """Remove ALL edges connected to the selected waypoint(s)."""
        if not self.selected:
            self.status = "Select a waypoint first, then press 'd' to disconnect."
            return
        total_removed = 0
        for wp_id in self.selected:
            before = len(self.graph.edges)
            self.graph.edges = [
                e for e in self.graph.edges
                if e.src != wp_id and e.dst != wp_id
            ]
            total_removed += before - len(self.graph.edges)
        wp_labels = []
        for wp_id in self.selected:
            wp = self.graph.get_waypoint(wp_id)
            if wp:
                wp_labels.append(wp.label or str(wp_id))
        self.status = f"Disconnected {', '.join(wp_labels)}: removed {total_removed} edges"

    def _auto_suggest(self):
        self.graph = auto_suggest_waypoints(self.wm, self.map_data)
        self.selected = []
        self.status = (f"Auto-suggested {len(self.graph.waypoints)} waypoints. "
                       f"Press 'c' to connect.")

    def _auto_connect(self):
        self.status = "Computing edges (BFS)... please wait."
        self.render()
        count = auto_connect_edges(self.graph, self.wm, max_distance=350)
        self.status = f"Auto-connected {count} edges."

    def _validate(self):
        ok, msg = validate_connectivity(self.graph)
        self.status = msg
        print(f"[validate] {msg}")

    def _save_graph(self):
        data = self.graph.to_json()
        with open(NAV_GRAPH_PATH, "w") as f:
            json.dump(data, f, indent=2)
        self.status = f"Saved {NAV_GRAPH_PATH.name} ({len(self.graph.waypoints)} wp, {len(self.graph.edges)} edges)"
        print(f"[save] {NAV_GRAPH_PATH}")

    def _load_graph(self):
        if not NAV_GRAPH_PATH.exists():
            self.status = "No nav_graph.json found."
            return
        with open(NAV_GRAPH_PATH) as f:
            data = json.load(f)
        self.graph = NavGraphData.from_json(data)
        self.selected = []
        self.status = (f"Loaded {len(self.graph.waypoints)} waypoints, "
                       f"{len(self.graph.edges)} edges.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    editor = WaypointEditor()
    editor.run()
