"""Tools that the LLM can call to control a cog.

Each tool is either:
- Instant: returns a result immediately (e.g., find_nearest)
- Action policy: returns immediately, then yields actions each game tick
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from heapq import heappop, heappush

from mettagrid.simulator import Action

from toolsy_policy.obs import (
    CHANNELS,
    EntityInfo,
    GameView,
    inv,
    type_tag,
)

DIRS = [
    ("move_north", -1, 0),
    ("move_south", 1, 0),
    ("move_west", 0, -1),
    ("move_east", 0, 1),
]


def _move_toward(dr: int, dc: int, alt: bool = False) -> str:
    if alt:
        if abs(dr) < abs(dc):
            return "move_north" if dr < 0 else "move_south"
        return "move_west" if dc < 0 else "move_east"
    if abs(dr) >= abs(dc):
        return "move_north" if dr < 0 else "move_south"
    return "move_west" if dc < 0 else "move_east"


def _open_dirs(view: GameView) -> list[str]:
    wall_set = set(view.walls)
    blocked_entities = {
        (entity.dr, entity.dc)
        for entity in view.entities
        if entity.dist == 1
    }
    dirs = []
    for name, dr, dc in DIRS:
        if (dr, dc) not in wall_set and (dr, dc) not in blocked_entities:
            dirs.append(name)
    return dirs or ["move_north", "move_south", "move_east", "move_west"]


def _fallback_dir(view: GameView) -> str:
    open_dirs = _open_dirs(view)
    return open_dirs[view.step % len(open_dirs)]


def _center(view: GameView) -> tuple[int, int]:
    return view.decoded.center_row, view.decoded.center_col


def _entity_pos(view: GameView, entity: EntityInfo) -> tuple[int, int]:
    if entity.row is not None and entity.col is not None:
        return entity.row, entity.col
    cr, cc = _center(view)
    return cr + entity.dr, cc + entity.dc


def _entity_from_known(view: GameView, row: int, col: int, type_name: str,
                       visible: bool = False) -> EntityInfo:
    cr, cc = _center(view)
    dr, dc = row - cr, col - cc
    return EntityInfo(
        type_name=type_name,
        dr=dr,
        dc=dc,
        dist=abs(dr) + abs(dc),
        row=row,
        col=col,
        visible=visible,
    )


def _refresh_entity(view: GameView, target: EntityInfo) -> EntityInfo | None:
    target_pos = _entity_pos(view, target)
    for entity in view.entities:
        if _entity_pos(view, entity) == target_pos:
            return entity
    type_name = view.world_map.entities.get(target_pos)
    if type_name is None and target_pos in view.world_map.seen:
        return None
    if type_name is None:
        type_name = target.type_name
    return _entity_from_known(view, target_pos[0], target_pos[1], type_name)


def _absolute_walls(view: GameView) -> set[tuple[int, int]]:
    cr, cc = _center(view)
    walls = set(view.world_map.walls)
    walls.update((cr + dr, cc + dc) for dr, dc in view.walls)
    return walls


def _known_cells(view: GameView) -> set[tuple[int, int]]:
    known = set(view.world_map.seen)
    known.update(getattr(view.decoded, "cells_by_location", {}).keys())
    known.add(_center(view))
    return known


def _entity_obstacles(view: GameView, target_pos: tuple[int, int]) -> set[tuple[int, int]]:
    obstacles = set(view.world_map.entities)
    obstacles.update(_entity_pos(view, entity) for entity in view.entities)
    obstacles.discard(target_pos)
    obstacles.discard(_center(view))
    return obstacles


def _first_step_from_world_model(
    view: GameView,
    goals: set[tuple[int, int]],
    obstacles: set[tuple[int, int]] | None = None,
) -> str | None:
    start = _center(view)
    goals = set(goals)
    if start in goals:
        return None
    if not goals:
        return None

    walls = _absolute_walls(view)
    known = _known_cells(view)
    obstacles = set(obstacles or set())
    obstacles.discard(start)
    obstacles.difference_update(goals)

    rows = [start[0], *(row for row, _col in goals), *(row for row, _col in known)]
    cols = [start[1], *(col for _row, col in goals), *(col for _row, col in known)]
    min_row, max_row = min(rows) - 8, max(rows) + 8
    min_col, max_col = min(cols) - 8, max(cols) + 8

    def search(allow_unknown: bool) -> str | None:
        def heuristic(pos: tuple[int, int]) -> int:
            return min(abs(pos[0] - goal[0]) + abs(pos[1] - goal[1]) for goal in goals)

        frontier: list[tuple[int, int, int, tuple[int, int], str | None]] = []
        heappush(frontier, (heuristic(start), 0, 0, start, None))
        best_cost = {start: 0}
        sequence = 0
        while frontier:
            _priority, cost, _sequence, (row, col), first_action = heappop(frontier)
            if (row, col) in goals:
                return first_action
            if cost != best_cost.get((row, col)):
                continue
            for action_name, dr, dc in DIRS:
                next_pos = (row + dr, col + dc)
                if not (min_row <= next_pos[0] <= max_row and min_col <= next_pos[1] <= max_col):
                    continue
                if next_pos in walls or next_pos in obstacles:
                    continue
                if not allow_unknown and next_pos not in known and next_pos not in goals:
                    continue
                next_cost = cost + (1 if next_pos in known else 3)
                if next_cost >= best_cost.get(next_pos, 1_000_000):
                    continue
                best_cost[next_pos] = next_cost
                sequence += 1
                next_first = first_action or action_name
                priority = next_cost + heuristic(next_pos)
                heappush(frontier, (priority, next_cost, sequence, next_pos, next_first))
        return None

    if start in known and any(goal in known for goal in goals):
        known_step = search(allow_unknown=False)
        if known_step is not None:
            return known_step
    return search(allow_unknown=True)


def _path_step(view: GameView, target: EntityInfo,
               adjacent: bool = True) -> str | None:
    start = _center(view)
    target_pos = _entity_pos(view, target)
    walls = _absolute_walls(view)

    if adjacent:
        goals = {
            (target_pos[0] + dr, target_pos[1] + dc)
            for _name, dr, dc in DIRS
        }
    else:
        goals = {target_pos}
    goals = {pos for pos in goals if pos not in walls}
    if start in goals:
        return None
    if not goals:
        return None

    obstacles = _entity_obstacles(view, target_pos)
    return _first_step_from_world_model(view, goals, obstacles)


def _step_toward_coord(view: GameView, target: tuple[int, int],
                       arrive_distance: int = 0) -> str | None:
    target_row, target_col = target
    goals = {
        (row, col)
        for row in range(target_row - arrive_distance, target_row + arrive_distance + 1)
        for col in range(target_col - arrive_distance, target_col + arrive_distance + 1)
        if abs(row - target_row) + abs(col - target_col) <= arrive_distance
    }
    obstacles = _entity_obstacles(view, target)
    obstacles.discard(target)
    return _first_step_from_world_model(view, goals, obstacles)


def _step_toward_entity(view: GameView, target: EntityInfo, stuck: int = 0) -> str:
    planned = _path_step(view, target)
    if planned in _open_dirs(view):
        return planned

    return _fallback_dir(view)


def _frontier_step(view: GameView, radius: int = 36) -> str | None:
    cr, cc = _center(view)
    known = _known_cells(view)
    walls = _absolute_walls(view)
    open_dirs = _open_dirs(view)
    for action_name, dr, dc in DIRS:
        next_pos = (cr + dr, cc + dc)
        if action_name in open_dirs and next_pos not in known and next_pos not in walls:
            return action_name

    candidates = []
    for row in range(cr - radius, cr + radius + 1):
        for col in range(cc - radius, cc + radius + 1):
            pos = (row, col)
            if pos not in known or pos in walls:
                continue
            if any((row + dr, col + dc) not in known and (row + dr, col + dc) not in walls for _name, dr, dc in DIRS):
                candidates.append((abs(row - cr) + abs(col - cc), pos))
    candidates.sort()
    for _dist, target in candidates[:80]:
        action = _step_toward_coord(view, target)
        if action in open_dirs:
            return action
    return None


def _goto_target(view: GameView, target: EntityInfo, max_ticks: int,
                 label: str | None = None) -> Generator[Action, GameView, ToolResult]:
    ticks = 0
    stuck = 0
    last_pos = (-1, -1)
    recent = []
    label = label or target.type_name
    while ticks < max_ticks:
        refreshed = _refresh_entity(view, target)
        if refreshed is None:
            return ToolResult(False, f"Lost target {label}.", ticks)
        target = refreshed
        if target.dist <= 1:
            return ToolResult(True, f"Adjacent to {target.type_name} at {target.pos_str}.", ticks)

        open_dirs = _open_dirs(view)
        preferred = _step_toward_entity(view, target, stuck)
        cr, cc = _center(view)
        pos = (cr, cc)
        recent.append(pos)
        if len(recent) > 8:
            recent.pop(0)
        if len(recent) >= 8 and len(set(recent[-8:])) <= 2:
            preferred = open_dirs[view.step % len(open_dirs)]
            recent.clear()
        if pos == last_pos:
            stuck += 1
        else:
            stuck = 0
        last_pos = pos
        ticks += 1
        view = yield Action(name=preferred)
    view.world_map.entities.pop(_entity_pos(view, target), None)
    return ToolResult(False, f"Timed out after {max_ticks} ticks.", ticks)


def _use_target(view: GameView, target: EntityInfo, max_ticks: int,
                label: str | None = None) -> Generator[Action, GameView, ToolResult]:
    goto = _goto_target(view, target, max(max_ticks - 2, 0), label)
    ticks = 0
    try:
        action = next(goto)
        while True:
            view = yield action
            ticks += 1
            action = goto.send(view)
    except StopIteration as e:
        result = e.value
        ticks = result.ticks_used
        if not result.success:
            return result

    view = yield Action(name="change_vibe_default")
    ticks += 1
    target = _refresh_entity(view, target)
    if target and target.dist <= 1:
        view = yield Action(name=_move_toward(target.dr, target.dc))
        ticks += 1
        return ToolResult(True, f"Used {label or target.type_name}.", ticks)
    return ToolResult(False, "Lost target after navigating.", ticks)


# ── Instant tools (return result, no ticks consumed) ──────────────


def tool_status(view: GameView) -> str:
    """Get the cog's current status: health, resources, gear, cargo."""
    return view.status_text()


def tool_nearby(view: GameView, max_entities: int = 12) -> str:
    """List nearby visible entities sorted by distance."""
    return view.nearby_summary(max_entities)


def tool_find(view: GameView, type_contains: str,
              max_results: int = 4, max_distance: int = 20) -> str:
    """Find entities matching a type substring within range."""
    found = view.find(type_contains, max_results, max_distance)
    if not found:
        return f"No '{type_contains}' found within distance {max_distance}."
    lines = []
    for e in found:
        extra = ""
        if e.coherence > 0:
            extra += f" coh={e.coherence}"
        if e.creds > 0:
            extra += f" creds={e.creds}"
        lines.append(f"{e.pos_str} d={e.dist} {e.type_name}{extra}")
    return "\n".join(lines)


def tool_combat_eval(view: GameView, dr: int, dc: int) -> str:
    """Evaluate combat against an entity at relative position (dr,dc)."""
    decoded = view.decoded
    cr, cc = decoded.center_row, decoded.center_col
    cell = decoded.cells_by_location.get((cr + dr, cc + dc))
    if cell is None:
        return f"No entity at ({dr:+d},{dc:+d})."
    me = decoded.self_cell
    my_dps = their_dps = 0
    for atk, def_ in CHANNELS:
        my_dps += max(0, inv(me, atk) - inv(cell, def_))
        their_dps += max(0, inv(cell, atk) - inv(me, def_))
    target_coh = max(inv(cell, "coherence"), 1)
    my_coh = max(inv(me, "coherence"), 1)
    hits = (target_coh + max(my_dps, 1) - 1) // max(my_dps, 1) if my_dps > 0 else 9999
    die_in = (my_coh + max(their_dps, 1) - 1) // max(their_dps, 1) if their_dps > 0 else 9999
    win = hits < die_in or (hits == die_in and my_dps >= their_dps)
    cost = min(their_dps * hits, my_coh)
    tn = type_tag(cell)
    return (
        f"Target: {tn} coh={target_coh}\n"
        f"My DPS: {my_dps}, Their DPS: {their_dps}\n"
        f"Hits to kill: {hits}, They kill me in: {die_in}\n"
        f"I win: {win}, Coherence cost: {cost}"
    )


def tool_gear_cost(view: GameView) -> str:
    """Show current gear count and cost of next upgrade."""
    cost = 1 << (2 + view.total_gear)
    affordable = "yes" if view.creds >= cost else "no"
    return f"Gear held: {view.total_gear}, Next cost: {cost}, Can afford: {affordable} (creds={view.creds})"


# ── Blocking tools (generators that yield actions) ────────────────


@dataclass
class ToolResult:
    """Result of a completed blocking tool."""
    success: bool
    message: str
    ticks_used: int


@dataclass(frozen=True)
class CombatEval:
    my_dps: int
    their_dps: int
    hits_to_kill: int
    hits_to_die: int
    i_win: bool
    coh_cost: int


def _combat_eval_entity(view: GameView, target: EntityInfo) -> CombatEval:
    my_dps = their_dps = 0
    for atk, def_ in CHANNELS:
        my_dps += max(0, view.gear.get(atk, 0) - target.inventory.get(def_, 0))
        their_dps += max(0, target.inventory.get(atk, 0) - view.gear.get(def_, 0))
    target_coh = max(target.coherence, 1)
    my_coh = max(view.coherence, 1)
    hits_to_kill = (target_coh + max(my_dps, 1) - 1) // max(my_dps, 1) if my_dps > 0 else 9999
    hits_to_die = (my_coh + max(their_dps, 1) - 1) // max(their_dps, 1) if their_dps > 0 else 9999
    i_win = hits_to_kill < hits_to_die or (hits_to_kill == hits_to_die and my_dps >= their_dps)
    coh_cost = min(their_dps * hits_to_kill, my_coh)
    return CombatEval(my_dps, their_dps, hits_to_kill, hits_to_die, i_win, coh_cost)


def tool_goto(view: GameView, type_contains: str,
              max_ticks: int = 50) -> Generator[Action, GameView, ToolResult]:
    """Walk toward the nearest entity matching type_contains. Yields actions
    until adjacent or max_ticks exceeded."""
    target = view.nearest(type_contains)
    if target is None:
        return ToolResult(False, f"No known '{type_contains}'.", 0)
    return (yield from _goto_target(view, target, max_ticks, type_contains))


def tool_explore(view: GameView,
                 num_ticks: int = 30) -> Generator[Action, GameView, ToolResult]:
    """Explore for num_ticks by walking toward world-map frontiers."""
    direction = ""
    recent: list[tuple[int, int]] = []
    attempted: dict[tuple[int, int], set[str]] = {}
    for _tick in range(num_ticks):
        pos = _center(view)
        open_dirs = _open_dirs(view)
        known = _known_cells(view)
        walls = _absolute_walls(view)
        tried_here = attempted.setdefault(pos, set())
        planned = None
        for action_name, dr, dc in DIRS:
            next_pos = (pos[0] + dr, pos[1] + dc)
            if action_name in open_dirs and action_name not in tried_here and next_pos not in known and next_pos not in walls:
                planned = action_name
                break
        if planned is None:
            planned = _frontier_step(view)
        if planned in open_dirs:
            direction = planned
        elif direction not in open_dirs:
            direction = open_dirs[0]
        attempted.setdefault(pos, set()).add(direction)
        recent.append(pos)
        if len(recent) > 10:
            recent.pop(0)
        if len(recent) >= 8 and len(set(recent)) <= 3:
            alternatives = [
                action
                for action in open_dirs
                if action != direction and action not in attempted.setdefault(pos, set())
            ]
            if not alternatives:
                attempted[pos].clear()
                alternatives = [action for action in open_dirs if action != direction]
            if alternatives:
                direction = alternatives[view.step % len(alternatives)]
                attempted[pos].add(direction)
            recent.clear()
        view = yield Action(name=direction)
    return ToolResult(True, f"Explored for {num_ticks} ticks.", num_ticks)


def tool_explore_compound(view: GameView,
                          max_ticks: int = 80) -> Generator[Action, GameView, ToolResult]:
    """Map the 20x20 area around the hub by steering toward unseen cells.
    Uses the persistent world map to skip already-explored areas."""
    hub = view.nearest("hub")
    ticks = 0
    wm = view.world_map

    # Navigate to hub first if visible but not close.
    if hub and hub.dist > 2:
        goto = tool_goto(view, "hub", min(max_ticks // 2, 30))
        try:
            action = next(goto)
            while True:
                view = yield action
                ticks += 1
                action = goto.send(view)
        except StopIteration as e:
            ticks = e.value.ticks_used

    # Record the hub position as our center.
    cr, cc = view.decoded.center_row, view.decoded.center_col
    hub = view.nearest("hub")
    if hub:
        center_r, center_c = cr + hub.dr, cc + hub.dc
    else:
        center_r, center_c = cr, cc

    stuck = 0
    last_pos = (-1, -1)
    while ticks < max_ticks:
        unseen = wm.unseen_in_area(center_r, center_c, radius=10)
        if not unseen:
            break

        # Pick the closest unseen cell as waypoint.
        cur_r, cur_c = view.decoded.center_row, view.decoded.center_col
        unseen.sort(key=lambda p: abs(p[0] - cur_r) + abs(p[1] - cur_c))
        target_r, target_c = unseen[0]
        dr = target_r - cur_r
        dc = target_c - cur_c

        open_dirs = _open_dirs(view)
        preferred = _step_toward_coord(view, (target_r, target_c), arrive_distance=0)
        if preferred not in open_dirs:
            preferred = open_dirs[view.step % len(open_dirs)]

        pos = (cur_r, cur_c)
        if pos == last_pos:
            stuck += 1
        else:
            stuck = 0
        last_pos = pos
        if stuck >= 4:
            preferred = open_dirs[view.step % len(open_dirs)]
            stuck = 0

        ticks += 1
        view = yield Action(name=preferred)

    summary = wm.summary(center_r, center_c, radius=10)
    return ToolResult(True, f"Compound map:\n{summary}", ticks)


def tool_mine(view: GameView, type_contains: str = "extractor",
              max_ticks: int = 40,
              no_loot: bool = False) -> Generator[Action, GameView, ToolResult]:
    """Go to nearest extractor, attack it until dead, then collect loot."""
    ticks = 0
    vibe_set = False
    while ticks < max_ticks:
        if view.coherence == 0:
            return ToolResult(False, "Died while mining.", ticks)
        dead_targets = [
            entity for entity in view.entities
            if type_contains in entity.type_name and entity.coherence == 0
        ]
        if dead_targets:
            target = min(dead_targets, key=lambda entity: entity.dist)
            if no_loot:
                return ToolResult(True, f"Killed {target.type_name}.", ticks)
            if vibe_set:
                vibe_set = False
                ticks += 1
                view = yield Action(name="change_vibe_default")
                continue
            if target.dist <= 1:
                ticks += 1
                view = yield Action(name=_move_toward(target.dr, target.dc))
                return ToolResult(True, f"Killed and looted {target.type_name}.", ticks)
            preferred = _step_toward_entity(view, target)
            ticks += 1
            view = yield Action(name=preferred)
            continue

        live_targets = [
            entity for entity in view.entities
            if type_contains in entity.type_name and entity.coherence > 0
        ]
        if not live_targets:
            return ToolResult(False, f"No '{type_contains}' visible.", ticks)

        candidates = []
        for entity in live_targets:
            ev = _combat_eval_entity(view, entity)
            if ev.my_dps > 0 and ev.i_win:
                candidates.append((ev, entity))
        if not candidates:
            return ToolResult(
                False,
                f"No winnable '{type_contains}' visible. Upgrade attack or choose another target.",
                ticks,
            )
        candidates.sort(key=lambda item: (item[0].coh_cost, item[1].dist))
        _ev, target = candidates[0]

        if target.dist <= 1:
            if not vibe_set:
                vibe_set = True
                ticks += 1
                view = yield Action(name="change_vibe_attack")
                continue
            ticks += 1
            view = yield Action(name=_move_toward(target.dr, target.dc))
            continue
        vibe_set = False
        preferred = _step_toward_entity(view, target)
        ticks += 1
        view = yield Action(name=preferred)
    return ToolResult(False, f"Mining timed out after {max_ticks} ticks.", ticks)


def tool_use(view: GameView, type_contains: str,
             max_ticks: int = 50) -> Generator[Action, GameView, ToolResult]:
    """Navigate to nearest matching entity, set default vibe, and bump it."""
    target = view.nearest(type_contains)
    if target is None:
        return ToolResult(False, f"No known '{type_contains}'.", 0)
    return (yield from _use_target(view, target, max_ticks, type_contains))


def tool_collect(view: GameView,
                 max_ticks: int = 30) -> Generator[Action, GameView, ToolResult]:
    """Navigate to nearest dead extractor and bump it with default vibe to loot."""
    targets = [
        entity for entity in view.entities
        if "extractor" in entity.type_name and entity.coherence == 0
    ]
    if not targets:
        return ToolResult(False, "No dead extractor visible.", 0)
    target = min(targets, key=lambda entity: entity.dist)
    return (yield from _use_target(view, target, max_ticks, "dead extractor"))


def tool_wait(view: GameView, num_ticks: int = 10) -> Generator[Action, GameView, ToolResult]:
    """Wait (noop) for num_ticks."""
    for _ in range(num_ticks):
        yield Action(name="noop")
    return ToolResult(True, f"Waited {num_ticks} ticks.", num_ticks)


def tool_join_team(view: GameView, name: str = "",
                   max_ticks: int = 30) -> Generator[Action, GameView, ToolResult]:
    """Navigate to the hub and bump it to join the team, claim dividends, and heal."""
    result = yield from tool_use(view, "hub", max_ticks)
    if result.success:
        return ToolResult(True, "Joined team (bumped hub). Check status() for team.", result.ticks_used)
    return result


def tool_go_to_spawn(view: GameView,
                     max_ticks: int = 60) -> Generator[Action, GameView, ToolResult]:
    """Navigate back to the spawn location (starting position / compound)."""
    ticks = 0
    stuck = 0
    last_pos = (-1, -1)
    recent: list[tuple[int, int]] = []
    while ticks < max_ticks:
        cr, cc = view.decoded.center_row, view.decoded.center_col
        dr = view.spawn_r - cr
        dc = view.spawn_c - cc
        dist = abs(dr) + abs(dc)
        if dist <= 1:
            return ToolResult(True, "Arrived at spawn.", ticks)
        open_dirs = _open_dirs(view)
        target = _entity_from_known(view, view.spawn_r, view.spawn_c, "spawn")
        preferred = _step_toward_coord(view, (view.spawn_r, view.spawn_c), arrive_distance=1)
        if preferred not in open_dirs:
            preferred = open_dirs[view.step % len(open_dirs)]
        pos = (cr, cc)
        recent.append(pos)
        if len(recent) > 8:
            recent.pop(0)
        if len(recent) >= 8 and len(set(recent[-8:])) <= 2:
            preferred = open_dirs[view.step % len(open_dirs)]
            recent.clear()
        if pos == last_pos:
            stuck += 1
        else:
            stuck = 0
        last_pos = pos
        ticks += 1
        view = yield Action(name=preferred)
    return ToolResult(False, f"Timed out after {max_ticks} ticks.", ticks)


def tool_align(view: GameView, type_contains: str = "junction",
               max_ticks: int = 50) -> Generator[Action, GameView, ToolResult]:
    """Find a disabled junction/observatory/datacenter, navigate to it, and bump
    it with default vibe to align it to your team. You must be on a team and
    within 25 tiles of an existing aligned entity."""
    if not view.team:
        return ToolResult(False, "Not on a team. Use join_team() first.", 0)
    targets = [e for e in view.entities
               if type_contains in e.type_name and e.coherence == 0]
    if not targets:
        return ToolResult(False, f"No disabled '{type_contains}' visible.", 0)
    target = min(targets, key=lambda e: e.dist)
    result = yield from _use_target(view, target, max_ticks, type_contains)
    if result.success:
        return ToolResult(True, f"Aligned {type_contains} to team {view.team}.", result.ticks_used)
    return result


# ── Tool registry ────────────────────────────────────────────────

INSTANT_TOOLS = {
    "status": tool_status,
    "nearby": tool_nearby,
    "find": tool_find,
    "combat_eval": tool_combat_eval,
    "gear_cost": tool_gear_cost,
}

BLOCKING_TOOLS = {
    "goto": tool_goto,
    "explore": tool_explore,
    "explore_compound": tool_explore_compound,
    "mine": tool_mine,
    "use": tool_use,
    "collect": tool_collect,
    "wait": tool_wait,
    "join_team": tool_join_team,
    "align": tool_align,
    "go_to_spawn": tool_go_to_spawn,
}

TOOL_DESCRIPTIONS = [
    {
        "name": "status",
        "description": "Get the cog's current status: coherence, energy, creds, hearts, cargo, gear stats.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "nearby",
        "description": "List all nearby visible entities sorted by distance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_entities": {"type": "integer", "description": "Max entities to list", "default": 12},
            },
            "required": [],
        },
    },
    {
        "name": "find",
        "description": "Find entities whose type contains a substring. E.g. find('extractor'), find('hub'), find('market'), find('_st') for gear stations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type_contains": {"type": "string", "description": "Substring to match in entity type"},
                "max_results": {"type": "integer", "default": 4},
                "max_distance": {"type": "integer", "default": 20},
            },
            "required": ["type_contains"],
        },
    },
    {
        "name": "combat_eval",
        "description": "Evaluate combat against entity at relative position (dr,dc). Shows DPS, hits to kill, whether you win.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dr": {"type": "integer", "description": "Row offset from self"},
                "dc": {"type": "integer", "description": "Col offset from self"},
            },
            "required": ["dr", "dc"],
        },
    },
    {
        "name": "gear_cost",
        "description": "Show current gear count and cost of next subsystem upgrade.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "goto",
        "description": "Schedule walking toward nearest entity matching type until adjacent or the tick budget ends. E.g. goto('hub'), goto('market_station'), goto('core_a_st'). Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type_contains": {"type": "string"},
                "max_ticks": {"type": "integer", "default": 50},
            },
            "required": ["type_contains"],
        },
    },
    {
        "name": "explore",
        "description": "Schedule frontier walking for N ticks to discover new areas. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "num_ticks": {"type": "integer", "default": 30},
            },
            "required": [],
        },
    },
    {
        "name": "explore_compound",
        "description": "Schedule compound exploration for the tick budget to map the 20x20 area around the hub. Use this first to learn the compound layout. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_ticks": {"type": "integer", "default": 80},
            },
            "required": [],
        },
    },
    {
        "name": "mine",
        "description": "Schedule mining for the tick budget: go to nearest extractor, attack until dead, then auto-collect loot. Pass no_loot=true to skip collection. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type_contains": {"type": "string", "default": "extractor"},
                "max_ticks": {"type": "integer", "default": 40},
                "no_loot": {"type": "boolean", "default": False, "description": "Skip auto-collection after kill"},
            },
            "required": [],
        },
    },
    {
        "name": "use",
        "description": "Schedule navigation to nearest matching entity, set default vibe, and bump it. Use for gear stations, market, hub, heart altar. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type_contains": {"type": "string", "description": "Type to find and use"},
                "max_ticks": {"type": "integer", "default": 50},
            },
            "required": ["type_contains"],
        },
    },
    {
        "name": "collect",
        "description": "Schedule going to nearest dead extractor and looting it with default vibe. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_ticks": {"type": "integer", "default": 30},
            },
            "required": [],
        },
    },
    {
        "name": "wait",
        "description": "Schedule noop for N ticks. Use while rebooting or intentionally waiting. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "num_ticks": {"type": "integer", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "join_team",
        "description": "Schedule going to the hub and bumping it to join the local team, claim dividends, and heal to full. You join whichever team owns the hub you bump. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Team name (red, blue, green, yellow). Informational — you join whichever hub you bump.", "default": ""},
                "max_ticks": {"type": "integer", "default": 30},
            },
            "required": [],
        },
    },
    {
        "name": "align",
        "description": "Schedule finding a disabled junction, observatory, or datacenter, navigating to it, and bumping it to align it to your team. Requires team membership and network range. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type_contains": {"type": "string", "default": "junction", "description": "Entity type to align: 'junction', 'observatory', or 'datacenter'"},
                "max_ticks": {"type": "integer", "default": 50},
            },
            "required": [],
        },
    },
    {
        "name": "go_to_spawn",
        "description": "Schedule navigation back to your starting location. Useful to return for upgrades, selling cargo, or buying hearts. Calling another action policy overrides it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_ticks": {"type": "integer", "default": 60},
            },
            "required": [],
        },
    },
]
