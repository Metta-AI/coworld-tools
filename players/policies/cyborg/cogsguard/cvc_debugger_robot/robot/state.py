"""WorldSnapshot builder -- the ONLY file that reads memory internals.

Everything else in robot/ receives a WorldSnapshot and never touches
SpatialMemory, SelfState, or GameClock directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from policies.cyborg.cogsguard.cvc_debugger_robot.robot.types import (
  Coord,
  MacroCommand,
  NavState,
  STALE_THRESHOLD,
  TEAM_TAG_PREFIX,
  HUB_ALIGN_RADIUS,
  JUNCTION_NETWORK_ALIGN_RADIUS,
  manhattan,
)
from policies.cyborg.cogsguard.cvc_debugger_robot.robot.memory import SpatialMemory, SelfState, GameClock


@dataclass
class EntitySummary:
  position: Coord
  tags: list[str]
  distance: int
  stale_ticks: int


@dataclass
class JunctionInfo:
  position: Coord
  owner: str
  distance: int
  alignable: bool = False


@dataclass
class ThreatSummary:
  level: str
  in_friendly_territory: bool
  hp_runway: float
  enemy_count: int


@dataclass
class WorldSnapshot:
  tick: int
  max_steps: int
  phase: str
  position: Coord
  self_state: SelfState
  in_friendly_territory: bool
  nearby_entities: list[EntitySummary]
  known_junctions: list[JunctionInfo]
  nav: NavState
  threat: ThreatSummary
  active_command: Optional[MacroCommand]
  command_history: list[str]
  territory: dict[Coord, int] = field(default_factory=dict)
  role: Optional[str] = None
  agent_id: int = 0
  teammates: dict[int, str] = field(default_factory=dict)
  teammate_positions: list[Coord] = field(default_factory=list)
  shared_extractors: dict[Coord, str] = field(default_factory=dict)
  shared_hub: Optional[Coord] = None
  resource_needs: list[str] = field(default_factory=list)
  hub_resources: dict[str, int] = field(default_factory=dict)

  def is_friendly_territory(self, pos: Coord) -> bool:
    return self.territory.get(pos, 0) == 1

  def is_enemy_territory(self, pos: Coord) -> bool:
    return self.territory.get(pos, 0) == 2

  def to_dict(self) -> dict:
    return {
      "tick": self.tick,
      "max_steps": self.max_steps,
      "phase": self.phase,
      "position": self.position,
      "role": self.role,
      "agent_id": self.agent_id,
      "gear": self.self_state.gear,
      "hp": self.self_state.hp,
      "energy": self.self_state.energy,
      "cargo": self.self_state.cargo,
      "cargo_total": self.self_state.cargo_total,
      "has_heart": self.self_state.has_heart,
      "heart_count": self.self_state.heart_count,
      "in_friendly_territory": self.in_friendly_territory,
      "in_enemy_territory": self.is_enemy_territory(self.position),
      "nav_status": self.nav.status.name,
      "nav_target": self.nav.target,
      "nav_distance": self.nav.distance_remaining,
      "threat_level": self.threat.level,
      "enemy_count": self.threat.enemy_count,
      "junctions": [
        {"pos": j.position, "owner": j.owner, "dist": j.distance}
        for j in self.known_junctions
      ],
      "entities_nearby": len(self.nearby_entities),
      "entities": [
        {"pos": e.position, "tags": e.tags, "dist": e.distance, "stale": e.stale_ticks}
        for e in self.nearby_entities
      ],
      "teammates": self.teammates,
      "teammate_positions": [list(p) for p in self.teammate_positions],
      "active_command": self.active_command.reason if self.active_command else None,
    }

  def to_prompt(self) -> str:
    ss = self.self_state
    parts = [
      f"Tick {self.tick}/{self.max_steps} ({self.phase}).",
      f"Agent {self.agent_id}, role: {self.role or 'unassigned'}.",
      f"Pos {self.position}.",
    ]

    if ss.gear:
      cargo_str = ", ".join(f"{v} {k}" for k, v in ss.cargo.items()) if ss.cargo else "empty"
      parts.append(f"Gear: {ss.gear}, cargo: {cargo_str}.")
    else:
      parts.append("No gear equipped.")

    parts.append(f"HP {ss.hp}, Energy {ss.energy}.")

    if ss.has_heart:
      parts.append("Carrying heart.")

    territory = "Friendly" if self.in_friendly_territory else ("Enemy" if self.is_enemy_territory(self.position) else "Neutral")
    parts.append(f"{territory} territory.")

    if self.teammates:
      team_str = ", ".join(f"#{aid}={r}" for aid, r in self.teammates.items())
      parts.append(f"Team: {team_str}.")

    if self.nav.target:
      parts.append(
        f"Nav: {self.nav.status.name} -> {self.nav.target}, "
        f"{self.nav.distance_remaining} steps."
      )

    n_own = sum(1 for j in self.known_junctions if j.owner == "own")
    n_neutral = sum(1 for j in self.known_junctions if j.owner == "neutral")
    n_enemy = sum(1 for j in self.known_junctions if j.owner in ("enemy", "clips"))
    if self.known_junctions:
      parts.append(f"Junctions: {n_own} own, {n_neutral} neutral, {n_enemy} enemy.")

    parts.append(f"Threat: {self.threat.level}.")

    if self.active_command:
      parts.append(f"Doing: {self.active_command.reason}")

    return " ".join(parts)


def build_snapshot(
  mem: SpatialMemory,
  self_state: SelfState,
  clock: GameClock,
  nav: NavState,
  active_cmd: Optional[MacroCommand],
  cmd_history: list[str],
  tag_names: dict[int, str],
  role: Optional[str] = None,
  agent_id: int = 0,
  teammates: Optional[dict[int, str]] = None,
  teammate_positions: Optional[list[Coord]] = None,
  shared_extractors: Optional[dict[Coord, str]] = None,
  shared_hub: Optional[Coord] = None,
  resource_needs: Optional[list[str]] = None,
  hub_resources: Optional[dict[str, int]] = None,
) -> WorldSnapshot:
  """Assemble the full world picture from memory. Called once per tick."""

  pos = mem.position
  tick = clock.tick

  # Nearby entities (within staleness threshold)
  nearby: list[EntitySummary] = []
  for epos, rec in mem.entities.items():
    stale = tick - rec.last_seen
    if stale > STALE_THRESHOLD:
      continue
    nearby.append(EntitySummary(
      position=epos,
      tags=list(rec.tag_names),
      distance=manhattan(pos, epos),
      stale_ticks=stale,
    ))
  nearby.sort(key=lambda e: e.distance)

  # Junctions with ownership
  junctions = _classify_junctions(mem, tag_names, pos)

  # Threat assessment
  threat = _assess_threat(mem, self_state, tag_names)

  return WorldSnapshot(
    tick=tick,
    max_steps=clock.max_steps,
    phase=clock.phase,
    position=pos,
    self_state=self_state,
    in_friendly_territory=mem.in_friendly_territory(),
    nearby_entities=nearby,
    known_junctions=junctions,
    nav=nav,
    threat=threat,
    active_command=active_cmd,
    command_history=list(cmd_history),
    territory=dict(mem.territory),
    role=role,
    agent_id=agent_id,
    teammates=teammates or {},
    teammate_positions=teammate_positions or [],
    shared_extractors=shared_extractors or {},
    shared_hub=shared_hub,
    resource_needs=resource_needs or [],
    hub_resources=hub_resources or {},
  )


def _classify_junctions(
  mem: SpatialMemory,
  tag_names: dict[int, str],
  pos: Coord,
) -> list[JunctionInfo]:
  """Find all known junctions and classify ownership + alignability.

  A neutral junction is alignable only if it is within HUB_ALIGN_RADIUS of
  a hub or JUNCTION_NETWORK_ALIGN_RADIUS of a junction already on our network.
  Without this check, the aligner walks to junctions the game engine will
  refuse to capture.
  """
  junction_tag_ids: set[int] = set()
  hub_tag_ids: set[int] = set()
  all_team_ids: set[int] = set()
  clips_ids: set[int] = set()

  for tid, name in tag_names.items():
    if name in ("junction", "type:junction"):
      junction_tag_ids.add(tid)
    if name in ("hub", "type:hub"):
      hub_tag_ids.add(tid)
    if name.startswith(TEAM_TAG_PREFIX):
      all_team_ids.add(tid)
      if name == "team:clips":
        clips_ids.add(tid)

  # Collect hub positions (our team's hubs)
  hub_positions: list[Coord] = []
  for epos, rec in mem.entities.items():
    if (mem.tick - rec.last_seen) > STALE_THRESHOLD:
      continue
    if rec.tag_ids & hub_tag_ids and rec.tag_ids & mem.own_team_ids:
      hub_positions.append(epos)

  # First pass: classify junctions and collect own-junction positions
  raw_junctions: list[tuple[Coord, str, int]] = []
  own_junction_positions: list[Coord] = []

  for epos, rec in mem.entities.items():
    if (mem.tick - rec.last_seen) > STALE_THRESHOLD:
      continue
    if not (rec.tag_ids & junction_tag_ids):
      continue

    if rec.tag_ids & mem.own_team_ids:
      owner = "own"
      own_junction_positions.append(epos)
    elif rec.tag_ids & clips_ids:
      owner = "clips"
    elif rec.tag_ids & all_team_ids:
      owner = "enemy"
    else:
      owner = "neutral"

    raw_junctions.append((epos, owner, manhattan(pos, epos)))

  # Second pass: compute alignability for neutral junctions
  junctions: list[JunctionInfo] = []
  for epos, owner, dist in raw_junctions:
    alignable = False
    if owner == "neutral":
      if hub_positions and min(manhattan(epos, h) for h in hub_positions) <= HUB_ALIGN_RADIUS:
        alignable = True
      elif own_junction_positions and min(manhattan(epos, j) for j in own_junction_positions) <= JUNCTION_NETWORK_ALIGN_RADIUS:
        alignable = True
    junctions.append(JunctionInfo(
      position=epos, owner=owner, distance=dist, alignable=alignable,
    ))

  junctions.sort(key=lambda j: j.distance)
  return junctions


def _assess_threat(
  mem: SpatialMemory,
  self_state: SelfState,
  tag_names: dict[int, str],
) -> ThreatSummary:
  """Compute a simple threat level from current state."""
  in_friendly = mem.in_friendly_territory()

  # Count nearby enemies
  all_team_ids: set[int] = set()
  for tid, name in tag_names.items():
    if name.startswith(TEAM_TAG_PREFIX):
      all_team_ids.add(tid)
  enemy_ids = all_team_ids - mem.own_team_ids

  enemy_count = 0
  for rec in mem.entities.values():
    if (mem.tick - rec.last_seen) > 5:
      continue
    if rec.tag_ids & enemy_ids:
      enemy_count += 1

  # HP runway
  if self_state.hp_delta < 0:
    hp_runway = self_state.hp / max(abs(self_state.hp_delta), 1)
  else:
    hp_runway = 999.0

  # Determine threat level
  if self_state.hp <= 5:
    level = "CRITICAL"
  elif self_state.hp <= 15 or hp_runway < 5:
    level = "HIGH"
  elif not in_friendly and self_state.energy <= 5:
    level = "HIGH"
  elif enemy_count >= 2:
    level = "MEDIUM"
  elif not in_friendly and self_state.hp < 50:
    level = "LOW"
  else:
    level = "NONE"

  return ThreatSummary(
    level=level,
    in_friendly_territory=in_friendly,
    hp_runway=hp_runway,
    enemy_count=enemy_count,
  )
