"""Pathfinding from first principles -- A*, flood fill, frontier exploration.

Three pure algorithms:
  a_star       -- shortest path on partial map
  flood_fill   -- discover all reachable cells
  find_frontier -- nearest unexplored cell for exploration

One stateful wrapper:
  Navigator    -- handles stuck detection, path caching, two-pass A*
"""

from __future__ import annotations

import heapq
import random
from collections import deque
from typing import Callable, Optional

from robot.types import (
  CARDINAL_DELTAS,
  MOVE_DELTAS,
  MOVE_NAMES,
  Coord,
  MacroCommand,
  MacroKind,
  NavState,
  NavStatus,
  coord_add,
  manhattan,
)
from robot.memory import SpatialMemory

MAX_A_STAR = 20_000
MAX_FRONTIER_DEPTH = 50
POSITION_HISTORY_LEN = 30
STUCK_WINDOW = 6
STUCK_UNIQUE_THRESHOLD = 2


# ---------------------------------------------------------------------------
# A* search
# ---------------------------------------------------------------------------

def a_star(
  start: Coord,
  goals: set[Coord],
  is_passable: Callable[[Coord], bool],
  max_iterations: int = MAX_A_STAR,
) -> list[Coord] | None:
  """Standard A* with manhattan heuristic.

  Returns path as list of coords (excluding start), or None if unreachable.
  """
  if not goals:
    return None
  if start in goals:
    return []

  goal_list = list(goals)
  if len(goal_list) == 1:
    g0 = goal_list[0]
    def h(p: Coord) -> int:
      return abs(p[0] - g0[0]) + abs(p[1] - g0[1])
  else:
    def h(p: Coord) -> int:
      return min(abs(p[0] - g[0]) + abs(p[1] - g[1]) for g in goal_list)

  INF = 999_999
  tie = 0
  heap: list[tuple[int, int, Coord]] = [(h(start), 0, start)]
  came_from: dict[Coord, Coord | None] = {start: None}
  g_score: dict[Coord, int] = {start: 0}

  iterations = 0
  while heap and iterations < max_iterations:
    iterations += 1
    _, _, current = heapq.heappop(heap)

    if current in goals:
      return _reconstruct(came_from, current)

    cur_g = g_score.get(current, INF)
    if cur_g == INF:
      continue

    for dr, dc in CARDINAL_DELTAS:
      nb = (current[0] + dr, current[1] + dc)
      if nb in goals or is_passable(nb):
        ng = cur_g + 1
        if ng < g_score.get(nb, INF):
          came_from[nb] = current
          g_score[nb] = ng
          tie += 1
          heapq.heappush(heap, (ng + h(nb), tie, nb))

  return None


def _reconstruct(came_from: dict[Coord, Coord | None], current: Coord) -> list[Coord]:
  path: list[Coord] = []
  while came_from[current] is not None:
    path.append(current)
    current = came_from[current]  # type: ignore[assignment]
  path.reverse()
  return path


# ---------------------------------------------------------------------------
# Flood fill
# ---------------------------------------------------------------------------

def flood_fill(
  start: Coord,
  is_passable: Callable[[Coord], bool],
  max_cells: int = 5000,
) -> set[Coord]:
  """BFS flood fill. Returns all reachable cells from start."""
  visited: set[Coord] = {start}
  queue: deque[Coord] = deque([start])

  while queue and len(visited) < max_cells:
    current = queue.popleft()
    for dr, dc in CARDINAL_DELTAS:
      nb = (current[0] + dr, current[1] + dc)
      if nb in visited:
        continue
      if is_passable(nb):
        visited.add(nb)
        queue.append(nb)

  return visited


# ---------------------------------------------------------------------------
# Frontier exploration
# ---------------------------------------------------------------------------

def find_frontier(
  start: Coord,
  known_open: set[Coord],
  visited: set[Coord],
  is_blocked: Callable[[Coord], bool],
  max_depth: int = MAX_FRONTIER_DEPTH,
) -> Coord | None:
  """BFS to find the nearest unexplored cell.

  An unexplored cell is one that:
    - is NOT in known_open and NOT in visited
    - is NOT blocked (not a wall)
    - is adjacent to at least one known open cell
  """
  bfs_seen: set[Coord] = {start}
  queue: deque[tuple[Coord, int]] = deque([(start, 0)])

  while queue:
    current, depth = queue.popleft()
    if depth > max_depth:
      continue

    for dr, dc in CARDINAL_DELTAS:
      nb = (current[0] + dr, current[1] + dc)
      if nb in bfs_seen:
        continue
      bfs_seen.add(nb)

      if nb not in known_open and nb not in visited:
        if not is_blocked(nb):
          return nb
        continue

      if not is_blocked(nb):
        queue.append((nb, depth + 1))

  return None


def find_frontier_spread(
  start: Coord,
  known_open: set[Coord],
  visited: set[Coord],
  is_blocked: Callable[[Coord], bool],
  teammate_positions: list[Coord],
  max_candidates: int = 8,
  max_depth: int = MAX_FRONTIER_DEPTH,
) -> Coord | None:
  """BFS for frontier cells, preferring those far from teammates.

  Collects up to max_candidates frontier cells, then picks the one that
  maximizes distance to the nearest teammate (breaking ties by proximity
  to self so we don't walk forever).
  """
  candidates: list[Coord] = []
  bfs_seen: set[Coord] = {start}
  queue: deque[tuple[Coord, int]] = deque([(start, 0)])

  while queue and len(candidates) < max_candidates:
    current, depth = queue.popleft()
    if depth > max_depth:
      continue

    for dr, dc in CARDINAL_DELTAS:
      nb = (current[0] + dr, current[1] + dc)
      if nb in bfs_seen:
        continue
      bfs_seen.add(nb)

      if nb not in known_open and nb not in visited:
        if not is_blocked(nb):
          candidates.append(nb)
        continue

      if not is_blocked(nb):
        queue.append((nb, depth + 1))

  if not candidates:
    return None
  if not teammate_positions:
    return candidates[0]

  def score(cell: Coord) -> tuple[int, int]:
    teammate_dist = min(manhattan(cell, t) for t in teammate_positions)
    self_dist = manhattan(start, cell)
    return (teammate_dist, -self_dist)

  return max(candidates, key=score)


# ---------------------------------------------------------------------------
# Navigator -- stateful wrapper
# ---------------------------------------------------------------------------

RECENT_ACTION_WINDOW = 4
BUMP_FAIL_THRESHOLD = 3


class Navigator:
  """Handles A* navigation, exploration, fleeing, and stuck detection.

  Key anti-congestion mechanism: the navigator tracks the last 2
  (position, action) pairs and never repeats the same action from
  the same position.  This breaks bump loops, oscillations, and
  stuck-recovery re-entry in a single rule.
  """

  def __init__(self):
    self._history: list[Coord] = []
    self._stuck_count: int = 0
    self._cached_path: list[Coord] | None = None
    self._cached_target: Coord | None = None
    self._ticks_active: int = 0

    # Recent-action tracking (anti-repeat)
    self._recent_actions: list[tuple[Coord, str]] = []

    # Bump-failure tracking
    self._failed_bumps: int = 0
    self._last_bump_target: Coord | None = None

  # --- Action filtering ---

  def _is_repeat(self, pos: Coord, action: str) -> bool:
    """True if this (position, action) was already taken in the last 2 frames."""
    return (pos, action) in self._recent_actions

  def _record_action(self, pos: Coord, action: str) -> None:
    self._recent_actions.append((pos, action))
    if len(self._recent_actions) > RECENT_ACTION_WINDOW:
      self._recent_actions.pop(0)

  def _pick_non_repeat(self, pos: Coord, preferred: str, mem: SpatialMemory) -> str:
    """Pick an action that isn't a repeat. Falls back to noop."""
    if not self._is_repeat(pos, preferred):
      return preferred
    dirs = list(MOVE_NAMES)
    random.shuffle(dirs)
    for d in dirs:
      if d == preferred:
        continue
      if self._is_repeat(pos, d):
        continue
      nxt = coord_add(pos, MOVE_DELTAS[d])
      if not mem.is_blocked(nxt):
        return d
    return "noop"

  def _emit(self, pos: Coord, action: str, mem: SpatialMemory) -> str:
    """Filter an action through the repeat detector, record, and return."""
    action = self._pick_non_repeat(pos, action, mem)
    self._record_action(pos, action)
    return action

  # --- Command dispatch ---

  def execute(self, cmd: MacroCommand, mem: SpatialMemory) -> tuple[str, NavState]:
    """Dispatch a MacroCommand to the appropriate navigation method."""
    safe = cmd.params.get("safe_mode", False)
    if cmd.kind == MacroKind.NAVIGATE_TO and cmd.target is not None:
      return self.navigate_to(cmd.target, mem, safe_mode=safe)
    if cmd.kind == MacroKind.EXPLORE:
      teammates = cmd.params.get("teammates")
      return self.explore(mem, teammate_positions=teammates)
    if cmd.kind == MacroKind.FLEE:
      return self.flee(mem)
    return "noop", NavState(status=NavStatus.IDLE)

  # --- Navigate to target ---

  def navigate_to(self, target: Coord, mem: SpatialMemory,
                   safe_mode: bool = False) -> tuple[str, NavState]:
    """A* to cell adjacent to target, then bump into it to interact."""
    pos = mem.position
    self._record_position(pos)
    self._ticks_active += 1

    dist = manhattan(pos, target)

    # On the target (dist=0): step off so we can re-enter next tick
    # (interactions trigger on cell entry, not while standing still)
    if dist == 0:
      self._clear_cache()
      for d in MOVE_NAMES:
        nxt = coord_add(pos, MOVE_DELTAS[d])
        if not mem.is_blocked(nxt):
          self._record_action(pos, d)
          return d, NavState(
            status=NavStatus.ARRIVED, target=target,
            ticks_active=self._ticks_active,
          )
      self._record_action(pos, "noop")
      return "noop", NavState(
        status=NavStatus.ARRIVED, target=target,
        ticks_active=self._ticks_active,
      )

    # Adjacent to target (dist=1): bump toward it to interact
    if dist == 1:
      if (len(self._history) >= 2
          and self._history[-1] == self._history[-2]
          and self._last_bump_target == target):
        self._failed_bumps += 1
      else:
        self._failed_bumps = 0
      self._last_bump_target = target

      if self._failed_bumps >= BUMP_FAIL_THRESHOLD:
        self._failed_bumps = 0
        alt = self._alt_adjacent(target, pos, mem)
        if alt:
          self._clear_cache()
          action = self._emit(pos, self._direction_toward(pos, alt), mem)
          print(f"    [NAV] bump_fail_alt pos={pos} target={target} -> {action}")
          return action, NavState(
            status=NavStatus.NAVIGATING, target=target,
            ticks_active=self._ticks_active,
          )
        action = self._emit(pos, "noop", mem)
        print(f"    [NAV] bump_fail_noop pos={pos} target={target}")
        return action, NavState(
          status=NavStatus.ARRIVED, target=target,
          ticks_active=self._ticks_active,
        )

      self._clear_cache()
      bump = self._direction_toward(pos, target)
      self._record_action(pos, bump)
      print(f"    [NAV] bump pos={pos} target={target} dir={bump} "
            f"failed_bumps={self._failed_bumps}")
      return bump, NavState(
        status=NavStatus.ARRIVED, target=target,
        ticks_active=self._ticks_active,
      )

    # Far from target -- reset bump tracking
    self._failed_bumps = 0
    self._last_bump_target = None

    # Stuck detection (only when not adjacent)
    if self._is_stuck():
      action = self._emit(pos, self._break_stuck(mem, target=target), mem)
      return action, NavState(
        status=NavStatus.STUCK, target=target,
        ticks_active=self._ticks_active,
      )

    # Invalidate cache if target changed
    if target != self._cached_target:
      self._clear_cache()
      self._cached_target = target

    path = self._get_path(pos, target, mem, safe_mode=safe_mode)

    if path:
      next_pos = path[0]
      self._cached_path = path[1:] if len(path) > 1 else None
      action = self._emit(pos, self._direction_toward(pos, next_pos), mem)
      return action, NavState(
        status=NavStatus.NAVIGATING, target=target,
        path=list(path), distance_remaining=len(path),
        ticks_active=self._ticks_active,
      )

    # Fallback: greedy move toward target
    action = self._emit(pos, self._greedy_toward(pos, target, mem), mem)
    return action, NavState(
      status=NavStatus.UNREACHABLE, target=target,
      ticks_active=self._ticks_active,
    )

  # --- Explore ---

  def explore(
    self, mem: SpatialMemory,
    teammate_positions: list[Coord] | None = None,
  ) -> tuple[str, NavState]:
    """Move toward the nearest frontier (unexplored) cell.

    When teammate_positions is provided, uses repulsion-based frontier
    selection to spread agents apart naturally.
    """
    pos = mem.position
    self._record_position(pos)
    self._ticks_active += 1

    if self._is_stuck():
      action = self._emit(pos, self._break_stuck(mem), mem)
      return action, NavState(status=NavStatus.STUCK, ticks_active=self._ticks_active)

    if not teammate_positions:
      for name in MOVE_NAMES:
        nxt = coord_add(pos, MOVE_DELTAS[name])
        if not mem.is_blocked(nxt) and nxt not in mem.visited:
          action = self._emit(pos, name, mem)
          return action, NavState(status=NavStatus.NAVIGATING, ticks_active=self._ticks_active)

    if teammate_positions:
      frontier = find_frontier_spread(
        pos, mem.open_cells, mem.visited, mem.is_blocked, teammate_positions,
      )
    else:
      frontier = find_frontier(pos, mem.open_cells, mem.visited, mem.is_blocked)

    if frontier is not None:
      path = a_star(pos, {frontier}, mem.is_passable_optimistic)
      if path is None:
        path = a_star(pos, {frontier}, mem.is_passable_strict)
      if path:
        action = self._emit(pos, self._direction_toward(pos, path[0]), mem)
        return action, NavState(
          status=NavStatus.NAVIGATING, target=frontier,
          path=list(path), distance_remaining=len(path),
          ticks_active=self._ticks_active,
        )

    action = self._emit(pos, self._random_move(mem), mem)
    return action, NavState(status=NavStatus.IDLE, ticks_active=self._ticks_active)

  # --- Flee ---

  def flee(self, mem: SpatialMemory) -> tuple[str, NavState]:
    """Navigate to the nearest cell with friendly territory."""
    pos = mem.position

    if mem.in_friendly_territory():
      return "noop", NavState(status=NavStatus.ARRIVED, ticks_active=self._ticks_active)

    friendly: list[Coord] = [p for p, v in mem.territory.items() if v == 1]
    if friendly:
      nearest = min(friendly, key=lambda c: manhattan(pos, c))
      return self.navigate_to(nearest, mem)

    for epos, rec in mem.entities.items():
      if any("hub" in n for n in rec.tag_names):
        return self.navigate_to(epos, mem)

    return self.explore(mem)

  # --- Path computation ---

  def _get_path(self, start: Coord, target: Coord, mem: SpatialMemory,
                 safe_mode: bool = False) -> list[Coord] | None:
    if self._cached_path:
      nxt = self._cached_path[0]
      if (manhattan(start, nxt) == 1
          and not mem.is_wall(nxt)
          and not mem.has_recent_agent(nxt)):
        return self._cached_path
      self._clear_cache()

    adj_goals = self._adjacent_goals(target, mem)
    if not adj_goals:
      return None

    if safe_mode:
      path = a_star(start, adj_goals, mem.is_passable_safe)
      if path is None:
        path = a_star(start, adj_goals, mem.is_passable_optimistic)
    else:
      path = a_star(start, adj_goals, mem.is_passable_optimistic)
      if path is None:
        path = a_star(start, adj_goals, mem.is_passable_strict)

    self._cached_path = list(path) if path else None
    return path

  def _adjacent_goals(self, target: Coord, mem: SpatialMemory) -> set[Coord]:
    """Cells adjacent to target we can stand on.

    Deprioritizes cells occupied by recently-seen agents: returns
    agent-free cells first, falls back to agent-occupied if needed.
    """
    agent_free: set[Coord] = set()
    all_passable: set[Coord] = set()
    for dr, dc in CARDINAL_DELTAS:
      pos = (target[0] + dr, target[1] + dc)
      if not mem.is_blocked(pos):
        all_passable.add(pos)
        if not mem.has_recent_agent(pos):
          agent_free.add(pos)

    if agent_free:
      return agent_free
    if all_passable:
      return all_passable

    # Last resort: anything not a wall
    for dr, dc in CARDINAL_DELTAS:
      pos = (target[0] + dr, target[1] + dc)
      if not mem.is_wall(pos):
        all_passable.add(pos)
    return all_passable

  def _alt_adjacent(self, target: Coord, current_pos: Coord, mem: SpatialMemory) -> Coord | None:
    """Find an alternative adjacent cell of target to approach from."""
    best: Coord | None = None
    for dr, dc in CARDINAL_DELTAS:
      adj = (target[0] + dr, target[1] + dc)
      if adj == current_pos:
        continue
      if mem.is_blocked(adj):
        continue
      if not mem.has_recent_agent(adj):
        return adj
      if best is None:
        best = adj
    return best

  # --- Stuck detection and recovery ---

  def _record_position(self, pos: Coord) -> None:
    self._history.append(pos)
    if len(self._history) > POSITION_HISTORY_LEN:
      self._history.pop(0)

  def _is_stuck(self) -> bool:
    if len(self._history) < STUCK_WINDOW:
      return False
    recent = self._history[-STUCK_WINDOW:]
    return len(set(recent)) <= STUCK_UNIQUE_THRESHOLD

  def _break_stuck(self, mem: SpatialMemory, target: Coord | None = None) -> str:
    self._stuck_count += 1
    self._clear_cache()
    pos = mem.position
    if target and self._stuck_count <= 3:
      dr = target[0] - pos[0]
      dc = target[1] - pos[1]
      if abs(dr) >= abs(dc):
        perps = ["move_east", "move_west"]
      else:
        perps = ["move_south", "move_north"]
      for d in perps:
        nxt = coord_add(pos, MOVE_DELTAS[d])
        if not mem.is_blocked(nxt):
          self._history.clear()
          return d
    self._history.clear()
    return self._random_move(mem)

  # --- Movement helpers ---

  def _direction_toward(self, start: Coord, end: Coord) -> str:
    dr = end[0] - start[0]
    dc = end[1] - start[1]
    for name, delta in MOVE_DELTAS.items():
      if delta == (dr, dc):
        return name
    if abs(dr) >= abs(dc):
      return "move_south" if dr > 0 else "move_north"
    return "move_east" if dc > 0 else "move_west"

  def _greedy_toward(self, pos: Coord, target: Coord, mem: SpatialMemory) -> str:
    dr = target[0] - pos[0]
    dc = target[1] - pos[1]

    if abs(dr) >= abs(dc):
      primary = "move_south" if dr > 0 else "move_north"
      secondary = "move_east" if dc > 0 else "move_west"
    else:
      primary = "move_east" if dc > 0 else "move_west"
      secondary = "move_south" if dr > 0 else "move_north"

    for d in [primary, secondary]:
      nxt = coord_add(pos, MOVE_DELTAS[d])
      if not mem.is_blocked(nxt):
        return d

    return self._random_move(mem)

  def _random_move(self, mem: SpatialMemory) -> str:
    pos = mem.position
    dirs = list(MOVE_NAMES)
    random.shuffle(dirs)
    for d in dirs:
      nxt = coord_add(pos, MOVE_DELTAS[d])
      if not mem.is_blocked(nxt) and nxt in mem.open_cells:
        return d
    for d in dirs:
      nxt = coord_add(pos, MOVE_DELTAS[d])
      if not mem.is_blocked(nxt):
        return d
    return "noop"

  def _clear_cache(self) -> None:
    self._cached_path = None
    self._cached_target = None

  def reset(self) -> None:
    self._history.clear()
    self._stuck_count = 0
    self._clear_cache()
    self._ticks_active = 0
    self._recent_actions.clear()
    self._failed_bumps = 0
    self._last_bump_target = None
