"""Persistent state across ticks -- the agent's memory of the world.

Three subsystems:
  SpatialMemory -- wall map, entity map, territory, open cells, visited
  SelfState     -- gear, HP, energy, cargo, deltas
  GameClock     -- tick counter, phase, urgency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from robot.types import (
  Coord,
  ELEMENTS,
  GEAR_TYPES,
  MOVE_DELTAS,
  NET_TAG_PREFIX,
  STALE_THRESHOLD,
  TEAM_TAG_PREFIX,
  coord_add,
)
from robot.perception import FrameScan


# ---------------------------------------------------------------------------
# Entity record stored in spatial memory
# ---------------------------------------------------------------------------

@dataclass
class EntityRecord:
  tag_ids: set[int] = field(default_factory=set)
  tag_names: list[str] = field(default_factory=list)
  last_seen: int = 0


# ---------------------------------------------------------------------------
# SpatialMemory -- the agent's internal map
# ---------------------------------------------------------------------------

class SpatialMemory:
  """Persistent map built incrementally from egocentric observations."""

  def __init__(self, center: Coord, tag_names: dict[int, str]):
    self.center = center
    self.tag_names = tag_names

    self.position: Coord = (0, 0)
    self.walls: dict[Coord, int] = {}
    self.entities: dict[Coord, EntityRecord] = {}
    self.territory: dict[Coord, int] = {}
    self.open_cells: set[Coord] = {(0, 0)}
    self.visited: set[Coord] = {(0, 0)}

    self.own_team_ids: set[int] = set()
    self.tick: int = 0

  def update(self, frame: FrameScan, pending_move: str | None, tick: int) -> None:
    """Called once per tick. Integrates new observation into persistent map."""
    self.tick = tick

    # Step 1: apply movement feedback using ground-truth position when
    # available.  last_action_move can report True for bump interactions
    # where the agent stays in place (e.g. using a gear station), so we
    # prefer local_position for accuracy.
    if frame.local_position is not None:
      self._apply_move_from_local_position(frame.local_position, pending_move)
    else:
      self._apply_move(frame.moved_last_tick, pending_move)

    # Step 2: record team identity
    if frame.own_team_ids:
      self.own_team_ids = frame.own_team_ids

    # Step 3: integrate walls
    for pos in frame.walls:
      self.walls[pos] = tick
      self.entities.pop(pos, None)
      self.open_cells.discard(pos)

    # Step 4: integrate entities
    visible_entity_positions: set[Coord] = set()
    occupied_structures: set[Coord] = set()
    for ent in frame.entities:
      pos = ent.abs_pos
      visible_entity_positions.add(pos)
      self.walls.pop(pos, None)
      self.entities[pos] = EntityRecord(
        tag_ids=set(ent.tag_ids),
        tag_names=list(ent.tag_names),
        last_seen=tick,
      )
      is_agent = any(n == "type:agent" for n in ent.tag_names)
      if not is_agent:
        occupied_structures.add(pos)

    # Step 5: integrate territory labels (1=friendly, 2=enemy, 0=neutral)
    for pos, val in frame.territory.items():
      self.territory[pos] = val

    # Step 6: mark open cells in observation window
    for pos in frame.obs_window:
      if pos not in frame.walls and pos not in occupied_structures:
        self.open_cells.add(pos)

    # Step 7: remove stale agents that are no longer visible
    for pos in list(self.entities):
      if pos not in frame.obs_window:
        continue
      if pos in visible_entity_positions:
        continue
      rec = self.entities[pos]
      if any(n == "type:agent" for n in rec.tag_names):
        del self.entities[pos]

  def _apply_move_from_local_position(
    self, local_pos: Coord, pending_move: str | None,
  ) -> None:
    """Use ground-truth local_position to track movement."""
    moved = local_pos != self.position
    self.position = local_pos

    if moved:
      self.visited.add(local_pos)
      self.open_cells.add(local_pos)
    elif pending_move is not None and pending_move in MOVE_DELTAS:
      target = coord_add(self.position, MOVE_DELTAS[pending_move])
      if target not in self.entities:
        self.walls[target] = self.tick

  def _apply_move(self, moved: bool, pending_move: str | None) -> None:
    if pending_move is None or pending_move not in MOVE_DELTAS:
      return

    target = coord_add(self.position, MOVE_DELTAS[pending_move])

    if moved:
      self.position = target
      self.visited.add(target)
      self.open_cells.add(target)
    else:
      self.walls[target] = self.tick

  def is_wall(self, pos: Coord) -> bool:
    return pos in self.walls

  def is_structure(self, pos: Coord) -> bool:
    """Non-agent entity at this position (impassable)."""
    rec = self.entities.get(pos)
    if rec is None:
      return False
    if (self.tick - rec.last_seen) > STALE_THRESHOLD:
      return False
    return not any(n == "type:agent" for n in rec.tag_names)

  def is_blocked(self, pos: Coord) -> bool:
    return self.is_wall(pos) or self.is_structure(pos)

  def is_passable_strict(self, pos: Coord) -> bool:
    """Passable only through confirmed open cells."""
    if self.is_blocked(pos):
      return False
    return pos in self.open_cells or pos in self.visited

  def is_passable_optimistic(self, pos: Coord) -> bool:
    """Passable if not blocked -- treats unknown cells as passable."""
    return not self.is_blocked(pos)

  def danger_level(self, pos: Coord) -> int:
    val = self.territory.get(pos, 0)
    if val == 1:
      return 0  # friendly
    if val == 2:
      return 2  # enemy
    return 1    # neutral/unknown

  def is_passable_safe(self, pos: Coord) -> bool:
    """Passable and not hostile territory. For miners/non-combatants."""
    if self.is_wall(pos):
      return False
    return self.danger_level(pos) < 2

  def has_recent_agent(self, pos: Coord, max_stale: int = 3) -> bool:
    """True if pos has an agent seen within max_stale ticks."""
    rec = self.entities.get(pos)
    if rec is None:
      return False
    if (self.tick - rec.last_seen) > max_stale:
      return False
    return any(n == "type:agent" for n in rec.tag_names)

  def in_friendly_territory(self) -> bool:
    return self.territory.get(self.position, 0) == 1

  def in_enemy_territory(self) -> bool:
    return self.territory.get(self.position, 0) == 2

  def own_net_ids(self) -> set[int]:
    result: set[int] = set()
    for tid in self.own_team_ids:
      tname = self.tag_names.get(tid, "")
      if tname.startswith(TEAM_TAG_PREFIX):
        net = NET_TAG_PREFIX + tname[len(TEAM_TAG_PREFIX):]
        for nid, nname in self.tag_names.items():
          if nname == net:
            result.add(nid)
    return result

  def stats(self) -> dict:
    """Summary counts for observability dashboard."""
    return {
      "walls_known": len(self.walls),
      "entities_tracked": len(self.entities),
      "cells_explored": len(self.open_cells),
      "cells_visited": len(self.visited),
      "territory_cells": len(self.territory),
    }

  def map_data(self) -> dict:
    """Full grid state for the observability dashboard map."""
    entities = []
    for pos, rec in self.entities.items():
      tags = rec.tag_names
      etype = "unknown"
      team = "neutral"
      for t in tags:
        if t == "type:agent":
          etype = "agent"
        elif t.startswith("type:"):
          etype = t[5:]
        if t.startswith("team:"):
          team = t[5:]
      entities.append({
        "pos": list(pos),
        "type": etype,
        "team": team,
        "stale": self.tick - rec.last_seen,
        "tags": tags,
      })

    return {
      "walls": [list(p) for p in self.walls],
      "open": [list(p) for p in self.open_cells],
      "visited": [list(p) for p in self.visited],
      "territory": [[p[0], p[1], v] for p, v in self.territory.items()],
      "entities": entities,
      "position": list(self.position),
    }

  def reset(self) -> None:
    self.position = (0, 0)
    self.walls.clear()
    self.entities.clear()
    self.territory.clear()
    self.open_cells = {(0, 0)}
    self.visited = {(0, 0)}
    self.own_team_ids = set()
    self.tick = 0


# ---------------------------------------------------------------------------
# SelfState -- the agent's own vitals
# ---------------------------------------------------------------------------

@dataclass
class SelfState:
  gear: Optional[str] = None
  hp: int = 999
  energy: int = 999
  cargo: dict[str, int] = field(default_factory=dict)
  cargo_total: int = 0
  has_heart: bool = False
  heart_count: int = 0
  hp_delta: int = 0
  energy_delta: int = 0

  @staticmethod
  def from_inventory(inv: dict[str, int], prev: SelfState) -> SelfState:
    gear: Optional[str] = None
    for g in GEAR_TYPES:
      if inv.get(g, 0) > 0:
        gear = g
        break

    cargo = {e: inv.get(e, 0) for e in ELEMENTS if inv.get(e, 0) > 0}
    cargo_total = sum(cargo.values())
    hp = inv.get("hp", 999)
    energy = inv.get("energy", 999)

    # On first tick, prev has sentinel defaults (999) -- don't compute deltas
    hp_delta = 0 if prev.hp == 999 and hp != 999 else hp - prev.hp
    energy_delta = 0 if prev.energy == 999 and energy != 999 else energy - prev.energy

    heart_count = inv.get("heart", 0)
    return SelfState(
      gear=gear,
      hp=hp,
      energy=energy,
      cargo=cargo,
      cargo_total=cargo_total,
      has_heart=heart_count > 0,
      heart_count=heart_count,
      hp_delta=hp_delta,
      energy_delta=energy_delta,
    )


# ---------------------------------------------------------------------------
# GameClock -- tick, phase, urgency
# ---------------------------------------------------------------------------

class GameClock:
  def __init__(self, max_steps: int = 10000):
    self.tick: int = 0
    self.max_steps = max_steps

  def advance(self) -> None:
    self.tick += 1

  @property
  def phase(self) -> str:
    t = self.tick
    if t < 200:
      return "OPENING"
    if t < 500:
      return "EARLY"
    if t < 2000:
      return "MID"
    if t < 4000:
      return "LATE"
    return "CLOSING"

  @property
  def urgency(self) -> float:
    return min(self.tick / max(self.max_steps, 1), 1.0)

  def reset(self) -> None:
    self.tick = 0
