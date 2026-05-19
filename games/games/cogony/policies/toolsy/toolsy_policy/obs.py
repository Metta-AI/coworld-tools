"""Observation decoding helpers for toolsy policy."""

from __future__ import annotations

from dataclasses import dataclass, field

from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent.runtime.observation import (
    DecodedObservation,
    ObservationCell,
    ObservationEnvelope,
    decode_observation,
)
from mettagrid.simulator import AgentObservation
from mettagrid.simulator.interface import Location

ELEMENTS = ["carbon", "oxygen", "germanium", "silicon"]
GEAR_STATS = ["core_a", "core_d", "os_a", "os_d", "gen_a", "gen_d", "storage_a", "storage_d"]
ATK_STATS = ["core_a", "os_a", "gen_a", "storage_a"]
DEF_STATS = ["core_d", "os_d", "gen_d", "storage_d"]
CHANNELS = list(zip(ATK_STATS, DEF_STATS, strict=True))

COMPOUND_STATION_OFFSETS = {
    "core_a_station": (7, -9),
    "storage_a_station": (7, -5),
    "os_a_station": (5, -7),
    "gen_a_station": (9, -7),
    "core_d_station": (7, 5),
    "storage_d_station": (7, 9),
    "os_d_station": (5, 7),
    "gen_d_station": (9, 7),
    "stake_buy_station": (-2, -3),
    "stake_sell_station": (2, -3),
    "market_station": (0, 3),
}

HEART_OFFSETS_BY_TEAM = {
    "red": (25, 25),
    "blue": (25, -23),
    "green": (-23, 25),
    "yellow": (-23, -23),
}

CENTER_OBSERVATORY_OFFSETS = [(-2, 0), (0, -2), (2, 0), (0, 2)]


def inv(cell: ObservationCell, key: str) -> int:
    return cell.features.get(f"inv:{key}", 0)


def type_tag(cell: ObservationCell) -> str:
    for t in cell.tags:
        if t.startswith("type:"):
            return t[5:]
    return ""


def team_tag(cell: ObservationCell) -> str:
    for t in cell.tags:
        if t.startswith("team:cogs_"):
            return t[10:]
    return ""


def entity_level(cell: ObservationCell) -> int:
    level = inv(cell, "level")
    if level:
        return level
    return sum(inv(cell, gear_name) for gear_name in GEAR_STATS)


@dataclass
class EntityInfo:
    type_name: str
    dr: int
    dc: int
    dist: int
    coherence: int = 0
    creds: int = 0
    level: int = 0
    inventory: dict = field(default_factory=dict)
    row: int | None = None
    col: int | None = None
    visible: bool = True
    team: str = ""

    @property
    def pos_str(self) -> str:
        return f"({self.dr:+d},{self.dc:+d})"


@dataclass
class EntityMemory:
    last_seen_step: int
    level: int = 0
    alignment: str = ""
    team: str = ""


class WorldMap:
    """Persistent map of discovered entities and seen cells."""

    def __init__(self):
        self.seen: set[tuple[int, int]] = set()
        self.entities: dict[tuple[int, int], str] = {}
        self.entity_metadata: dict[tuple[int, int], EntityMemory] = {}
        self.walls: set[tuple[int, int]] = set()
        self.current_step: int = 0

    def update(self, view_decoded: DecodedObservation):
        self.current_step = int(view_decoded.step)
        for (r, c), cell in view_decoded.cells_by_location.items():
            self.seen.add((r, c))
            tn = type_tag(cell)
            if tn == "wall":
                self.walls.add((r, c))
                self.entities.pop((r, c), None)
                self.entity_metadata.pop((r, c), None)
            elif tn == "agent":
                self.walls.discard((r, c))
                self.entities.pop((r, c), None)
                self.entity_metadata.pop((r, c), None)
            elif tn:
                self.walls.discard((r, c))
                self.entities[(r, c)] = tn
                self.entity_metadata[(r, c)] = EntityMemory(
                    last_seen_step=self.current_step,
                    level=entity_level(cell),
                    alignment=team_tag(cell) if tn == "junction" else "",
                    team=team_tag(cell) if tn == "hub" else "",
                )
            else:
                self.walls.discard((r, c))
                self.entities.pop((r, c), None)
                self.entity_metadata.pop((r, c), None)
        self._infer_compound_stations()
        self._infer_center_from_team_hubs()

    def _infer_compound_stations(self) -> None:
        hubs = [pos for pos, type_name in self.entities.items() if type_name == "hub"]
        markets = [pos for pos, type_name in self.entities.items() if type_name == "market_station"]
        for hub in hubs:
            for market in markets:
                transform = _compound_transform_from_market_offset(market[0] - hub[0], market[1] - hub[1])
                if transform is None:
                    continue
                for type_name, offset in COMPOUND_STATION_OFFSETS.items():
                    dr, dc = transform(offset)
                    self.entities.setdefault((hub[0] + dr, hub[1] + dc), type_name)
                break

    def _infer_center_from_team_hubs(self) -> None:
        for hub, type_name in tuple(self.entities.items()):
            if type_name != "hub":
                continue
            metadata = self.entity_metadata.get(hub)
            if metadata is None or metadata.team not in HEART_OFFSETS_BY_TEAM:
                continue
            heart_offset = HEART_OFFSETS_BY_TEAM[metadata.team]
            heart_pos = (hub[0] + heart_offset[0], hub[1] + heart_offset[1])
            self.entities.setdefault(heart_pos, "heart_station")
            for dr, dc in CENTER_OBSERVATORY_OFFSETS:
                self.entities.setdefault((heart_pos[0] + dr, heart_pos[1] + dc), "observatory")

    def unseen_in_area(self, center_r: int, center_c: int,
                       radius: int = 10) -> list[tuple[int, int]]:
        unseen = []
        for r in range(center_r - radius, center_r + radius + 1):
            for c in range(center_c - radius, center_c + radius + 1):
                if (r, c) not in self.seen:
                    unseen.append((r, c))
        return unseen

    def summary(self, center_r: int, center_c: int,
                radius: int = 10) -> str:
        by_type: dict[str, list[str]] = {}
        for (r, c), tn in self.entities.items():
            rel_r, rel_c = r - center_r, c - center_c
            if abs(rel_r) <= radius and abs(rel_c) <= radius:
                if tn not in by_type:
                    by_type[tn] = []
                by_type[tn].append(f"({rel_r:+d},{rel_c:+d})")
        total_cells = (2 * radius + 1) ** 2
        seen_count = sum(1 for r in range(center_r - radius, center_r + radius + 1)
                         for c in range(center_c - radius, center_c + radius + 1)
                         if (r, c) in self.seen)
        lines = [f"Coverage: {seen_count}/{total_cells} cells seen"]
        for etype, positions in sorted(by_type.items()):
            lines.append(f"  {etype}: {', '.join(positions[:6])}")
        return "\n".join(lines)

    def snapshot(self, center_r: int, center_c: int, max_entities: int | None = None) -> dict:
        entities = []
        for (row, col), type_name in sorted(
            self.entities.items(),
            key=lambda item: (
                abs(item[0][0] - center_r) + abs(item[0][1] - center_c),
                item[1],
                item[0],
            ),
        ):
            dr, dc = row - center_r, col - center_c
            entity = {
                "type": type_name,
                "row": row,
                "col": col,
                "dr": dr,
                "dc": dc,
                "dist": abs(dr) + abs(dc),
            }
            metadata = self.entity_metadata.get((row, col), EntityMemory(last_seen_step=self.current_step))
            entity["age"] = max(0, self.current_step - metadata.last_seen_step)
            entity["level"] = metadata.level
            entity["alignment"] = metadata.alignment
            if metadata.team:
                entity["team"] = metadata.team
            entities.append(entity)
        walls = []
        for row, col in sorted(
            self.walls,
            key=lambda pos: (
                abs(pos[0] - center_r) + abs(pos[1] - center_c),
                pos,
            ),
        ):
            dr, dc = row - center_r, col - center_c
            walls.append({
                "row": row,
                "col": col,
                "dr": dr,
                "dc": dc,
                "dist": abs(dr) + abs(dc),
            })
        seen_bounds = {}
        if self.seen:
            rows = [row for row, _col in self.seen]
            cols = [col for _row, col in self.seen]
            seen_bounds = {
                "min_row": min(rows),
                "max_row": max(rows),
                "min_col": min(cols),
                "max_col": max(cols),
            }
        return {
            "center": [center_r, center_c],
            "seen_count": len(self.seen),
            "seen_bounds": seen_bounds,
            "wall_count": len(self.walls),
            "walls": walls,
            "entity_count": len(self.entities),
            "entities": entities[:max_entities],
        }


def _compound_transform_from_market_offset(dr: int, dc: int):
    if (dr, dc) == (0, 3):
        return lambda offset: (offset[0], offset[1])
    if (dr, dc) == (0, -3):
        return lambda offset: (offset[0], -offset[1])
    if (dr, dc) == (3, 0):
        return lambda offset: (offset[1], offset[0])
    if (dr, dc) == (-3, 0):
        return lambda offset: (-offset[1], offset[0])
    return None


@dataclass
class GameView:
    """Decoded game state from one agent's observation."""
    step: int
    coherence: int
    energy: int
    creds: int
    heart: int
    cargo: dict[str, int]
    total_cargo: int
    max_cargo: int
    gear: dict[str, int]
    total_atk: int
    total_def: int
    total_gear: int
    vibe: str
    team: str
    spawn_r: int
    spawn_c: int
    world_map: WorldMap
    entities: list[EntityInfo]
    walls: list[tuple[int, int]]
    decoded: DecodedObservation
    inventory: dict[str, int] = field(default_factory=dict)

    def find(self, type_contains: str, max_results: int = 10,
             max_distance: int = 99) -> list[EntityInfo]:
        results = []
        needle = type_contains.lower()
        cr, cc = self.decoded.center_row, self.decoded.center_col
        visible_positions = set()
        for e in self.entities:
            row = e.row if e.row is not None else cr + e.dr
            col = e.col if e.col is not None else cc + e.dc
            visible_positions.add((row, col))
            if needle in e.type_name.lower() and e.dist <= max_distance:
                results.append(e)

        for (row, col), type_name in self.world_map.entities.items():
            if (row, col) in visible_positions:
                continue
            dr, dc = row - cr, col - cc
            dist = abs(dr) + abs(dc)
            if needle in type_name.lower() and dist <= max_distance:
                results.append(EntityInfo(
                    type_name=type_name,
                    dr=dr,
                    dc=dc,
                    dist=dist,
                    row=row,
                    col=col,
                    visible=False,
                ))

        results.sort(key=lambda e: (e.dist, not e.visible))
        return results[:max_results]

    def nearest(self, type_contains: str, max_distance: int = 99) -> EntityInfo | None:
        found = self.find(type_contains, max_results=1, max_distance=max_distance)
        return found[0] if found else None

    def status_text(self) -> str:
        gear_str = " ".join(f"{k}={v}" for k, v in self.gear.items() if v > 0)
        cargo_str = " ".join(f"{k}={v}" for k, v in self.cargo.items() if v > 0)
        team_str = self.team or "none"
        return (
            f"team={team_str} coh={self.coherence} energy={self.energy} creds={self.creds} "
            f"heart={self.heart} cargo={self.total_cargo}/{self.max_cargo} "
            f"atk={self.total_atk} def={self.total_def}\n"
            f"gear: {gear_str or 'none'}\n"
            f"cargo: {cargo_str or 'empty'}"
        )

    def nearby_summary(self, max_entities: int = 8) -> str:
        lines = []
        for e in self.entities[:max_entities]:
            extra = ""
            if e.coherence > 0:
                extra += f" coh={e.coherence}"
            if e.creds > 0:
                extra += f" creds={e.creds}"
            lines.append(f"  {e.pos_str} d={e.dist} {e.type_name}{extra}")
        if len(self.entities) > max_entities:
            lines.append(f"  ...and {len(self.entities) - max_entities} more")
        return "\n".join(lines) if lines else "  (nothing visible)"


def decode_view(
    obs: AgentObservation,
    pei: PolicyEnvInterface,
    step: int,
    spawn: tuple[int, int] = (0, 0),
    world_map: WorldMap | None = None,
) -> GameView:
    decoded = decode_observation(
        ObservationEnvelope(raw_observation=obs, policy_env_info=pei, step=step)
    )
    decoded = _remap_decoded_to_local_position(decoded, spawn)
    return _game_view_from_decoded(decoded, step, spawn, world_map)


def decode_view_from_agent_state(
    agent_state: dict,
    *,
    spawn: tuple[int, int] = (0, 0),
    world_map: WorldMap | None = None,
) -> GameView:
    step = int(agent_state.get("step", 0) or 0)
    center_row, center_col = _agent_state_center(agent_state)
    center = Location(center_row, center_col)
    cells_by_location: dict[tuple[int, int], ObservationCell] = {}
    obs_grid = agent_state.get("obs") or agent_state.get("last_obs") or {}
    for relative_location, raw_cell in obs_grid.items():
        dr, dc = _parse_relative_location(str(relative_location))
        row = center_row + dr
        col = center_col + dc
        tags = tuple(sorted(str(tag) for tag in raw_cell.get("tags", ())))
        raw_features = raw_cell.get("feats", raw_cell.get("features", {}))
        features = {str(name): int(value) for name, value in raw_features.items()}
        cells_by_location[(row, col)] = ObservationCell(
            location=Location(row, col),
            center=center,
            tags=tags,
            features=features,
        )
    decoded = DecodedObservation(
        observation=None,
        policy_env_info=None,
        step=step,
        center_row=center_row,
        center_col=center_col,
        cells_by_location=cells_by_location,
        global_features={},
    )
    return _game_view_from_decoded(decoded, step, spawn, world_map)


def _agent_state_center(agent_state: dict) -> tuple[int, int]:
    center = _agent_state_obs_center(agent_state)
    if center is not None:
        return center
    agent = agent_state.get("agent") or {}
    location = agent.get("location")
    if location is None:
        return 0, 0
    return int(location[0]), int(location[1])


def _agent_state_obs_center(agent_state: dict) -> tuple[int, int] | None:
    for container in (
        agent_state,
        agent_state.get("policy_infos") or {},
        (agent_state.get("agent") or {}).get("policy_infos") or {},
    ):
        center = container.get("obs_center") or container.get("__obs_center__")
        if center is not None:
            return int(center[0]), int(center[1])
    return None


def _parse_relative_location(value: str) -> tuple[int, int]:
    dr, dc = value.split(",", 1)
    return int(dr), int(dc)


def _local_position_from_globals(global_features: dict[str, int]) -> tuple[int, int] | None:
    keys = ("lp:north", "lp:south", "lp:west", "lp:east")
    if not any(key in global_features for key in keys):
        return None
    row = int(global_features.get("lp:south", 0)) - int(global_features.get("lp:north", 0))
    col = int(global_features.get("lp:east", 0)) - int(global_features.get("lp:west", 0))
    return row, col


def _remap_decoded_to_local_position(
    decoded: DecodedObservation,
    spawn: tuple[int, int],
) -> DecodedObservation:
    local_pos = _local_position_from_globals(decoded.global_features)
    if local_pos is None:
        return decoded

    old_center = Location(decoded.center_row, decoded.center_col)
    new_center = Location(spawn[0] + local_pos[0], spawn[1] + local_pos[1])
    dr = new_center.row - old_center.row
    dc = new_center.col - old_center.col
    if dr == 0 and dc == 0:
        return decoded

    cells_by_location: dict[tuple[int, int], ObservationCell] = {}
    for (row, col), cell in decoded.cells_by_location.items():
        location = Location(row + dr, col + dc)
        cells_by_location[(location.row, location.col)] = ObservationCell(
            location=location,
            center=new_center,
            tags=cell.tags,
            features=cell.features,
        )
    return DecodedObservation(
        observation=decoded.observation,
        policy_env_info=decoded.policy_env_info,
        step=decoded.step,
        center_row=new_center.row,
        center_col=new_center.col,
        cells_by_location=cells_by_location,
        global_features=decoded.global_features,
    )


def _game_view_from_decoded(
    decoded: DecodedObservation,
    step: int,
    spawn: tuple[int, int],
    world_map: WorldMap | None,
) -> GameView:
    me = decoded.self_cell
    cr, cc = decoded.center_row, decoded.center_col

    entities = []
    walls = []
    for (r, c), cell in decoded.cells_by_location.items():
        dr, dc = r - cr, c - cc
        if dr == 0 and dc == 0:
            continue
        tn = type_tag(cell)
        if tn == "wall":
            walls.append((dr, dc))
            continue
        if not tn:
            continue
        e = EntityInfo(
            type_name=tn, dr=dr, dc=dc,
            dist=abs(dr) + abs(dc),
            coherence=inv(cell, "coherence"),
            creds=inv(cell, "creds"),
            level=inv(cell, "level"),
            row=r,
            col=c,
            team=team_tag(cell),
        )
        for feat_name, feat_val in cell.features.items():
            if feat_name.startswith("inv:") and feat_val != 0:
                e.inventory[feat_name[4:]] = feat_val
        entities.append(e)

    entities.sort(key=lambda e: e.dist)

    inventory = {
        feat_name[4:]: feat_val
        for feat_name, feat_val in me.features.items()
        if feat_name.startswith("inv:") and feat_val != 0
    }
    cargo = {e: inv(me, e) for e in ELEMENTS}
    gear = {g: inv(me, g) for g in GEAR_STATS}

    if world_map is None:
        world_map = WorldMap()
    world_map.update(decoded)

    return GameView(
        step=step,
        coherence=inv(me, "coherence"),
        energy=inv(me, "energy"),
        creds=inv(me, "creds"),
        heart=inv(me, "heart"),
        cargo=cargo,
        total_cargo=sum(cargo.values()),
        max_cargo=max(inv(me, "max_cargo"), 1),
        gear=gear,
        total_atk=sum(gear.get(a, 0) for a in ATK_STATS),
        total_def=sum(gear.get(d, 0) for d in DEF_STATS),
        total_gear=sum(gear.values()),
        vibe="default",
        team=team_tag(me),
        spawn_r=spawn[0],
        spawn_c=spawn[1],
        world_map=world_map,
        entities=entities,
        walls=walls,
        decoded=decoded,
        inventory=inventory,
    )
