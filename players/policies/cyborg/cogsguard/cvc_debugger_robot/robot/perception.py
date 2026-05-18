"""Perception layer -- parse one tick's raw observation tokens into structured data.

This is the ONLY file that touches obs.tokens and obs.talk. Everything
downstream works with the FrameScan dataclass.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from mettagrid.simulator.interface import AgentObservation

from policies.cyborg.cogsguard.cvc_debugger_robot.robot.types import Coord, TEAM_TAG_PREFIX, coord_add


_TERRITORY_EDGE_DELTAS: dict[str, Coord] = {
  "territory:north": (-1, 0),
  "territory:south": (1, 0),
  "territory:west": (0, -1),
  "territory:east": (0, 1),
}
_OPPOSITE_TERRITORY_EDGE = {
  "territory:north": "territory:south",
  "territory:south": "territory:north",
  "territory:west": "territory:east",
  "territory:east": "territory:west",
}


@dataclass
class SeenEntity:
  abs_pos: Coord
  rel_pos: Coord
  tag_names: list[str]
  tag_ids: set[int]


@dataclass
class HeardMessage:
  agent_id: int
  text: str
  position: Coord
  remaining_steps: int


@dataclass
class FrameScan:
  moved_last_tick: bool
  local_position: Coord | None = None
  walls: set[Coord] = field(default_factory=set)
  entities: list[SeenEntity] = field(default_factory=list)
  territory: dict[Coord, int] = field(default_factory=dict)
  inventory: dict[str, int] = field(default_factory=dict)
  hub_resources: dict[str, int] = field(default_factory=dict)
  own_team_ids: set[int] = field(default_factory=set)
  obs_window: set[Coord] = field(default_factory=set)
  heard_messages: list[HeardMessage] = field(default_factory=list)


def extract_local_position(obs: AgentObservation) -> Coord | None:
  """Extract ground-truth position from local_position obs tokens.

  Returns offset from spawn as (row, col), or None if tokens are absent.
  """
  lp: dict[str, int] = {}
  for token in obs.tokens:
    if token.feature.name.startswith("lp:"):
      lp[token.feature.name] = int(token.value)
  if not lp:
    return None
  return (lp.get("lp:south", 0) - lp.get("lp:north", 0),
          lp.get("lp:east", 0) - lp.get("lp:west", 0))


def parse_observation(
  obs: AgentObservation,
  agent_pos: Coord,
  center: Coord,
  tag_names: dict[int, str],
) -> FrameScan:
  """Parse all tokens in one pass into a structured FrameScan."""

  moved = True
  local_pos: Coord | None = None
  walls: set[Coord] = set()
  raw_entities: dict[Coord, tuple[set[int], list[str], Coord]] = {}
  territory_here: int | None = None
  territory_edges: dict[Coord, dict[str, int]] = {}
  inventory: dict[str, int] = {}
  hub_resources: dict[str, int] = {}
  own_team_ids: set[int] = set()

  for token in obs.tokens:
    fname = token.feature.name

    # Movement feedback (global token, no location)
    if fname == "last_action_move":
      moved = int(token.value) != 0
      continue

    if fname == "territory:here":
      territory_here = int(token.value)
      continue

    # Local position ground-truth (global token, no location)
    if fname.startswith("lp:"):
      if local_pos is None:
        local_pos = extract_local_position(obs)
      continue

    # Inventory tokens sit at the agent's center cell
    if fname.startswith("inv:") and token.location == center:
      _parse_inv_token(fname, token.value, token.feature.normalization, inventory)
      continue

    if fname.startswith("team:"):
      _parse_inv_token(fname, token.value, token.feature.normalization, hub_resources,
                       prefix="team:")
      continue

    if token.location is None:
      continue

    rel = (token.location[0] - center[0], token.location[1] - center[1])
    abs_pos = coord_add(agent_pos, rel)

    if fname in _TERRITORY_EDGE_DELTAS:
      territory_edges.setdefault(abs_pos, {})[fname] = int(token.value)
      continue

    if fname != "tag":
      continue

    tag_id = int(token.value)
    tag_name = tag_names.get(tag_id, "")

    # Tags on the agent's own cell -> extract team identity
    if abs_pos == agent_pos:
      if tag_name.startswith(TEAM_TAG_PREFIX):
        own_team_ids.add(tag_id)
      continue

    # Walls
    if tag_name == "type:wall":
      walls.add(abs_pos)
      continue

    # Everything else is an entity at this position
    if abs_pos not in raw_entities:
      raw_entities[abs_pos] = (set(), [], rel)
    raw_entities[abs_pos][0].add(tag_id)
    raw_entities[abs_pos][1].append(tag_name)

  # Build entity list
  entities = [
    SeenEntity(abs_pos=pos, rel_pos=data[2], tag_names=data[1], tag_ids=data[0])
    for pos, data in raw_entities.items()
  ]

  obs_window = _visible_observation_positions(agent_pos, center)
  territory = (
    _reconstruct_territory_labels(
      center_pos=agent_pos,
      obs_window=obs_window,
      territory_here=territory_here,
      territory_edges=territory_edges,
    )
    if territory_here is not None else {}
  )

  # Parse talk messages from nearby agents
  heard: list[HeardMessage] = []
  for talk in obs.talk:
    rel = (talk.location[0] - center[0], talk.location[1] - center[1])
    abs_pos = coord_add(agent_pos, rel)
    heard.append(HeardMessage(
      agent_id=talk.agent_id,
      text=talk.text,
      position=abs_pos,
      remaining_steps=talk.remaining_steps,
    ))

  return FrameScan(
    moved_last_tick=moved,
    local_position=local_pos,
    walls=walls,
    entities=entities,
    territory=territory,
    inventory=inventory,
    hub_resources=hub_resources,
    own_team_ids=own_team_ids,
    obs_window=obs_window,
    heard_messages=heard,
  )


def _visible_observation_positions(agent_pos: Coord, center: Coord) -> set[Coord]:
  row_radius, col_radius = center
  return {
    coord_add(agent_pos, (row_offset, col_offset))
    for row_offset in range(-row_radius, row_radius + 1)
    for col_offset in range(-col_radius, col_radius + 1)
    if _is_within_observation_shape(
      row_offset=row_offset,
      col_offset=col_offset,
      row_radius=row_radius,
      col_radius=col_radius,
    )
  }


def _is_within_observation_shape(
  *,
  row_offset: int,
  col_offset: int,
  row_radius: int,
  col_radius: int,
) -> bool:
  if row_radius == 0 and col_radius == 0:
    return row_offset == 0 and col_offset == 0
  if row_radius == 0:
    return row_offset == 0 and abs(col_offset) <= col_radius
  if col_radius == 0:
    return col_offset == 0 and abs(row_offset) <= row_radius

  row_sq = row_offset * row_offset
  col_sq = col_offset * col_offset
  row_radius_sq = row_radius * row_radius
  col_radius_sq = col_radius * col_radius

  if row_radius == col_radius:
    dist_sq = row_sq + col_sq
    if dist_sq <= row_radius_sq:
      return True
    return (
      row_radius >= 2
      and dist_sq == row_radius_sq + 1
      and (abs(row_offset) == row_radius or abs(col_offset) == col_radius)
    )

  if row_radius > col_radius:
    return row_sq * col_radius_sq + col_sq * row_radius_sq <= row_radius_sq * col_radius_sq

  return row_sq * col_radius_sq + col_sq * row_radius_sq <= row_radius_sq * col_radius_sq


def _reconstruct_territory_labels(
  *,
  center_pos: Coord,
  obs_window: set[Coord],
  territory_here: int,
  territory_edges: dict[Coord, dict[str, int]],
) -> dict[Coord, int]:
  territory = {center_pos: territory_here}
  queue: deque[Coord] = deque([center_pos])

  while queue:
    current_pos = queue.popleft()
    current_label = territory[current_pos]
    for feature_name, delta in _TERRITORY_EDGE_DELTAS.items():
      neighbor_pos = coord_add(current_pos, delta)
      if neighbor_pos not in obs_window or neighbor_pos in territory:
        continue
      territory[neighbor_pos] = _neighbor_territory_label(
        current_pos=current_pos,
        current_label=current_label,
        neighbor_pos=neighbor_pos,
        feature_name=feature_name,
        territory_edges=territory_edges,
      )
      queue.append(neighbor_pos)

  return territory


def _neighbor_territory_label(
  *,
  current_pos: Coord,
  current_label: int,
  neighbor_pos: Coord,
  feature_name: str,
  territory_edges: dict[Coord, dict[str, int]],
) -> int:
  forward_transition = territory_edges.get(current_pos, {}).get(feature_name)
  if forward_transition is not None:
    from_label, to_label = divmod(forward_transition, 3)
    if from_label == current_label:
      return to_label

  reverse_transition = territory_edges.get(neighbor_pos, {}).get(_OPPOSITE_TERRITORY_EDGE[feature_name])
  if reverse_transition is not None:
    from_label, to_label = divmod(reverse_transition, 3)
    if to_label == current_label:
      return from_label

  return current_label


def _parse_inv_token(
  feature_name: str,
  value: int,
  normalization: float,
  out: dict[str, int],
  prefix: str = "inv:",
) -> None:
  """Parse a single inv:* or team:* token, handling power-suffix encoding.

  Examples:
    inv:carbon       -> carbon, power=0
    inv:carbon:p1    -> carbon, power=1, value *= normalization^1
    inv:own:policy   -> own:policy, power=0 (colon in name, no :pN suffix)
  """
  suffix = feature_name[len(prefix):]
  if not suffix:
    return

  val = int(value)
  if val <= 0:
    return

  item_name, sep, power_str = suffix.rpartition(":p")
  if sep and item_name and power_str.isdigit():
    power = int(power_str)
  else:
    item_name = suffix
    power = 0

  base = max(int(normalization), 1)
  out[item_name] = out.get(item_name, 0) + val * (base ** power)
