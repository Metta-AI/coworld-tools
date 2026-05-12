"""Draft-based role negotiation and teammate tracking.

DraftBoard -- shared across all agents. Tracks an ideal team composition
and lets agents claim roles on a first-come basis. When a slot is full,
the agent is bumped to the next best available role.

TeammateMemory -- per-agent, tracks heard talk messages and teammate roles.

Draft protocol (ticks 0-14):
  Each agent claims a preferred role on the shared board.
  The board enforces target counts -- if miner slots are full, you get
  reassigned. Agents announce their pick via talk ("draft:miner"), and
  if they hear a conflict (another agent took their role first), they
  re-claim on the next tick and announce the switch ("switch:aligner").
  By tick 15, the draft is finalized and agents lock in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_policies.policies.cyborg.cogsguard.cvc_debugger_robot.robot.types import Coord, GEAR_TYPES

DRAFT_DEADLINE = 1

TALK_PREFIX_DRAFT = "draft:"
TALK_PREFIX_SWITCH = "switch:"
TALK_PREFIX_ROLE = "role:"
TALK_PREFIX_INTEL = "intel:"
TALK_PREFIX_NEED = "need:"

# Ideal composition scaled by team size.
# Each entry: (role, fraction of team that should have this role).
# Fractions are converted to counts by rounding, with at least 1 of each
# role assigned up to team size.
COMPOSITION_WEIGHTS = [
  ("aligner", 0.5),
  ("miner", 0.3),
  ("scrambler", 0.2),
]

# Per-agent preference rotation so agents naturally spread out.
# Agent i's preference list starts at index i in this cycle.
PREFERENCE_CYCLE = ["aligner", "miner", "scrambler"]


EXPLICIT_TARGETS = {
  2: {"miner": 1, "aligner": 1},
  3: {"miner": 1, "aligner": 2},
  4: {"miner": 1, "aligner": 2, "scrambler": 1},
  5: {"miner": 2, "aligner": 2, "scrambler": 1},
  6: {"miner": 2, "aligner": 3, "scrambler": 1},
  7: {"miner": 2, "aligner": 4, "scrambler": 1},
  8: {"miner": 2, "aligner": 5, "scrambler": 1},
}


def _build_target_counts(num_agents: int) -> dict[str, int]:
  """Compute ideal role counts for a given team size."""
  if num_agents <= 1:
    return {}

  if num_agents in EXPLICIT_TARGETS:
    return dict(EXPLICIT_TARGETS[num_agents])

  # For larger teams, use weighted distribution
  targets: dict[str, int] = {}
  remaining = num_agents

  for role, weight in COMPOSITION_WEIGHTS:
    count = max(1, round(weight * num_agents))
    count = min(count, remaining)
    if count > 0:
      targets[role] = count
      remaining -= count
    if remaining <= 0:
      break

  idx = 0
  while remaining > 0:
    role = COMPOSITION_WEIGHTS[idx % len(COMPOSITION_WEIGHTS)][0]
    targets[role] = targets.get(role, 0) + 1
    remaining -= 1
    idx += 1

  return targets


def _preference_list(agent_id: int) -> list[str]:
  """Rotated preference list so agents naturally spread across roles."""
  n = len(PREFERENCE_CYCLE)
  start = agent_id % n
  return PREFERENCE_CYCLE[start:] + PREFERENCE_CYCLE[:start]


class DraftBoard:
  """Shared draft board -- one instance per RobotPolicy.

  Agents claim roles during ticks 0-14. The board enforces target counts
  and resolves conflicts by bumping agents to their next preference.
  After tick 15, roles are locked.
  """

  def __init__(self, num_agents: int):
    self._num_agents = num_agents
    self._targets = _build_target_counts(num_agents)
    self._claims: dict[int, str] = {}
    self._finalized = False

  @property
  def is_solo(self) -> bool:
    return self._num_agents <= 1

  @property
  def is_finalized(self) -> bool:
    return self._finalized

  def claim(self, agent_id: int, preferred: str | None = None) -> str:
    """Claim a role. Returns the actual role assigned.

    If preferred is None, uses the agent's natural preference list.
    If preferred slot is full, bumps to next available role.
    """
    if self.is_solo:
      self._claims[agent_id] = "solo"
      return "solo"

    prefs = _preference_list(agent_id)
    if preferred and preferred in GEAR_TYPES:
      prefs = [preferred] + [r for r in prefs if r != preferred]

    role = self._find_open_role(prefs, agent_id)
    self._claims[agent_id] = role
    return role

  def reclaim(self, agent_id: int, preferred: str) -> str | None:
    """Try to switch to a different role during draft. Returns new role
    if the switch succeeded, None if it didn't change."""
    if self._finalized or self.is_solo:
      return None

    old = self._claims.get(agent_id)
    if old == preferred:
      return None

    if not self._slot_available(preferred, agent_id):
      return None

    self._claims[agent_id] = preferred
    return preferred

  def finalize(self) -> None:
    self._finalized = True

  def get_role(self, agent_id: int) -> str | None:
    return self._claims.get(agent_id)

  def get_all_claims(self) -> dict[int, str]:
    return dict(self._claims)

  def role_counts(self) -> dict[str, int]:
    counts: dict[str, int] = {}
    for role in self._claims.values():
      counts[role] = counts.get(role, 0) + 1
    return counts

  def targets(self) -> dict[str, int]:
    return dict(self._targets)

  def _find_open_role(self, prefs: list[str], agent_id: int) -> str:
    for role in prefs:
      if self._slot_available(role, agent_id):
        return role
    # All slots full -- force the first preference (shouldn't happen
    # if targets sum to num_agents, but safety fallback)
    return prefs[0]

  def _slot_available(self, role: str, exclude_agent: int) -> bool:
    target = self._targets.get(role, 0)
    if target <= 0:
      return False
    current = sum(
      1 for aid, r in self._claims.items()
      if r == role and aid != exclude_agent
    )
    return current < target


# ---------------------------------------------------------------------------
# Teammate memory (unchanged interface, extended message parsing)
# ---------------------------------------------------------------------------

@dataclass
class TeammateRecord:
  agent_id: int
  role: str | None = None
  last_position: Coord = (0, 0)
  last_seen: int = 0


@dataclass
class ResourceNeed:
  """A teammate's broadcast that the hub is low on a specific resource."""
  element: str
  tick: int


class TeammateMemory:
  """Per-agent memory of observed teammates from talk messages.

  Parses role announcements, extractor intel, hub location, and
  resource need alerts from the compact talk protocol.
  """

  def __init__(self):
    self._records: dict[int, TeammateRecord] = {}
    self._shared_extractors: dict[Coord, tuple[str, int]] = {}
    self._shared_hub: Coord | None = None
    self._resource_needs: list[ResourceNeed] = []

  def hear(self, agent_id: int, text: str, position: Coord, tick: int) -> None:
    rec = self._records.get(agent_id)
    if rec is None:
      rec = TeammateRecord(agent_id=agent_id)
      self._records[agent_id] = rec

    rec.last_position = position
    rec.last_seen = tick

    for prefix in (TALK_PREFIX_DRAFT, TALK_PREFIX_SWITCH, TALK_PREFIX_ROLE):
      if text.startswith(prefix):
        payload = text[len(prefix):]
        role = payload.split(",")[0]
        if role in GEAR_TYPES:
          rec.role = role
        break

    if text.startswith(TALK_PREFIX_INTEL):
      self._parse_intel(text[len(TALK_PREFIX_INTEL):], tick)

    if text.startswith(TALK_PREFIX_NEED):
      self._parse_need(text[len(TALK_PREFIX_NEED):], tick)

  def _parse_intel(self, payload: str, tick: int) -> None:
    """Parse intel messages: 'intel:hub@r,c,cX@r,c,oX@r,c,...'"""
    for token in payload.split(","):
      if token.startswith("hub@"):
        parts = token[4:].split("/")
        if len(parts) == 2:
          try:
            self._shared_hub = (int(parts[0]), int(parts[1]))
          except ValueError:
            pass
      elif "@" in token and len(token) >= 4:
        at_idx = token.index("@")
        resource_code = token[:at_idx]
        coords = token[at_idx + 1:].split("/")
        if len(coords) == 2:
          try:
            pos: Coord = (int(coords[0]), int(coords[1]))
            self._shared_extractors[pos] = (resource_code, tick)
          except ValueError:
            pass

  def _parse_need(self, payload: str, tick: int) -> None:
    """Parse need messages: 'need:carbon,silicon'"""
    for elem in payload.split(","):
      elem = elem.strip()
      if elem and any(elem.startswith(e) for e in ("carbon", "oxygen", "germanium", "silicon")):
        self._resource_needs = [
          n for n in self._resource_needs if n.element != elem
        ]
        self._resource_needs.append(ResourceNeed(element=elem, tick=tick))

  def get_teammates(self) -> dict[int, TeammateRecord]:
    return dict(self._records)

  def get_role(self, agent_id: int) -> str | None:
    rec = self._records.get(agent_id)
    return rec.role if rec else None

  def known_roles(self) -> dict[int, str]:
    return {
      aid: rec.role
      for aid, rec in self._records.items()
      if rec.role is not None
    }

  def get_shared_extractors(self, max_stale: int = 200) -> dict[Coord, str]:
    """Return extractor positions reported by teammates, pruning stale ones."""
    current_tick = max((r.last_seen for r in self._records.values()), default=0)
    result: dict[Coord, str] = {}
    for pos, (resource, tick) in self._shared_extractors.items():
      if current_tick - tick <= max_stale:
        result[pos] = resource
    return result

  def get_shared_hub(self) -> Coord | None:
    return self._shared_hub

  def get_resource_needs(self, max_age: int = 100) -> list[str]:
    """Return elements the team has broadcast as hub-starved, newest first."""
    current_tick = max((r.last_seen for r in self._records.values()), default=0)
    return [
      n.element for n in sorted(self._resource_needs, key=lambda n: -n.tick)
      if current_tick - n.tick <= max_age
    ]
