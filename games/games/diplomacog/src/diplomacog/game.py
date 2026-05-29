"""Game configuration for a station-based diplomacy mission."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, Self, cast

from mettagrid.cogame.core import CoGameMission, CoGameMissionVariant
from mettagrid.config.action_config import ActionsConfig, MoveActionConfig, NoopActionConfig
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import GameValueFilter, HandlerTarget, actorHasAnyOf, anyOf, isNot
from mettagrid.config.game_value import AnyGameValue, QueryInventoryValue, SumGameValue, max_value, stat, val
from mettagrid.config.handler_config import (
    AllOf,
    AnyHandler,
    FirstMatch,
    Handler,
    actorHas,
    allOf,
    firstMatch,
    targetHas,
    updateActor,
    updateTarget,
)
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    WallConfig,
)
from mettagrid.config.mutation.query_inventory_mutation import queryDelta
from mettagrid.config.mutation.stats_mutation import StatsMutation, logActorAgentStat, logStatToGame
from mettagrid.config.obs_config import GlobalObsConfig, ObsConfig
from mettagrid.config.query import query
from mettagrid.config.render_config import RenderConfig
from mettagrid.config.tag import typeTag
from mettagrid.mapgen.mapgen import MapGen
from mettagrid.mapgen.scene import Scene, SceneConfig
from pydantic import Field

COUNTRIES = ("country_a", "country_b", "country_c")
COUNTRY_HUBS = tuple(f"{country}_hub" for country in COUNTRIES)
COUNTRY_STATIONS = tuple(f"{country}_station" for country in COUNTRIES)

QUEUE_RESOURCES = ("queue_diplomacy", "queue_trade")
CORE_RESOURCES = ("power_cell", "intel", "influence", "sabotage_kit")
INCIDENT_RESOURCES = ("incident_pending", "incident_window")
CAMPAIGN_RESOURCES = (
    "campaign_year",
    "season_spring",
    "season_fall",
    "phase_orders",
    "phase_retreat",
    "phase_adjustment",
    "capture_window",
)

RESOURCE_NAMES = [
    *CORE_RESOURCES,
    *COUNTRIES,
    *QUEUE_RESOURCES,
    *INCIDENT_RESOURCES,
    *CAMPAIGN_RESOURCES,
    "stability",
    "crisis",
]
STATIONS = [
    "reactor_station",
    "comms_station",
    "diplomacy_station",
    "sabotage_station",
    "supply_center",
    *COUNTRY_STATIONS,
]
RIVAL_COUNTRY_BY_TARGET = {
    "country_a": "country_b",
    "country_b": "country_c",
    "country_c": "country_a",
}

CAMPAIGN_START_YEAR = 1901
SPRING_ORDERS_LENGTH = 20
SPRING_RETREAT_LENGTH = 6
FALL_ORDERS_LENGTH = 20
FALL_RETREAT_LENGTH = 6
WINTER_ADJUSTMENT_LENGTH = 10
CAMPAIGN_YEAR_LENGTH = (
    SPRING_ORDERS_LENGTH + SPRING_RETREAT_LENGTH + FALL_ORDERS_LENGTH + FALL_RETREAT_LENGTH + WINTER_ADJUSTMENT_LENGTH
)
WINTER_STABILITY_PER_CENTER = 1

# Discussion-first pacing trades early summit time for fewer late-cycle collapses, so the
# terminal score bands are lower than the original station-loop implementation.
MISSION_VICTORY_SCORE = -190
MISSION_DEFEAT_PRESSURE = 120


def named_first_match(handlers: dict[str, Handler]) -> AnyHandler | None:
    return firstMatch([handler.model_copy(update={"name": name}) for name, handler in handlers.items()])


def find_named_handler(handler: AnyHandler | None, name: str) -> Handler | None:
    if handler is None:
        return None
    if isinstance(handler, Handler):
        return handler if handler.name == name else None
    for child in handler.handlers:
        found = find_named_handler(child, name)
        if found is not None:
            return found
    return None


def drop_named_handler(handler: AnyHandler | None, name: str) -> AnyHandler | None:
    if handler is None:
        return None
    if isinstance(handler, Handler):
        return None if handler.name == name else handler
    remaining = [child for nested in handler.handlers if (child := drop_named_handler(nested, name)) is not None]
    if isinstance(handler, FirstMatch):
        return firstMatch(remaining)
    if isinstance(handler, AllOf):
        return allOf(remaining)
    return handler


@dataclass(frozen=True)
class CountryProfile:
    initial_stability: int
    crisis_start: int
    crisis_period: int
    crisis_delta: int
    diplomacy_resolve: int
    trade_resolve: int
    sabotage_impact: int


COUNTRY_PROFILES: dict[str, CountryProfile] = {
    "country_a": CountryProfile(
        initial_stability=30,
        crisis_start=2,
        crisis_period=30,
        crisis_delta=1,
        diplomacy_resolve=3,
        trade_resolve=1,
        sabotage_impact=2,
    ),
    "country_b": CountryProfile(
        initial_stability=25,
        crisis_start=6,
        crisis_period=24,
        crisis_delta=1,
        diplomacy_resolve=2,
        trade_resolve=2,
        sabotage_impact=3,
    ),
    "country_c": CountryProfile(
        initial_stability=22,
        crisis_start=10,
        crisis_period=20,
        crisis_delta=2,
        diplomacy_resolve=2,
        trade_resolve=1,
        sabotage_impact=4,
    ),
}


@dataclass(slots=True)
class DiplomacySettings:
    max_steps: int
    map_width: int
    map_height: int
    placement_variant: Literal["balanced", "compact", "world"]
    spawn_focus: Literal["distributed", "summit"]

    @classmethod
    def from_mission(cls, mission: DiplomacyGame) -> DiplomacySettings:
        map_builder = mission.map_builder
        width = getattr(map_builder, "width", 60)
        height = getattr(map_builder, "height", 60)
        instance = getattr(map_builder, "instance", None)
        placement_variant = getattr(instance, "placement_variant", "world")
        spawn_focus = getattr(instance, "spawn_focus", "distributed")
        return cls(
            max_steps=mission.max_steps,
            map_width=int(width),
            map_height=int(height),
            placement_variant=cast(Literal["balanced", "compact", "world"], placement_variant),
            spawn_focus=cast(Literal["distributed", "summit"], spawn_focus),
        )


class SupportsModifyMission(Protocol):
    def modify_mission(self, mission: DiplomacySettings) -> None: ...


def _normalize_diplomacy_variant_names(names: Sequence[str]) -> list[str]:
    from diplomacog.variants import normalize_variant_names  # noqa: PLC0415

    return normalize_variant_names(names)


def _diplomacy_hidden_variant_names() -> frozenset[str]:
    from diplomacog.variants import DIPLOMACY_HIDDEN_VARIANT_NAMES  # noqa: PLC0415

    return DIPLOMACY_HIDDEN_VARIANT_NAMES


def _resolve_diplomacy_variant_selection(names: Sequence[str]):
    from diplomacog.variants import resolve_variant_selection  # noqa: PLC0415

    return resolve_variant_selection(names)


class DiplomacyAdjacencyBoardConfig(SceneConfig):
    spawn_count: int
    include_core_stations: bool = True
    include_country_stations: bool = True
    include_country_hubs: bool = True
    include_supply_centers: bool = True
    include_sabotage_station: bool = True
    placement_variant: Literal["balanced", "compact", "world"] = "balanced"
    spawn_focus: Literal["distributed", "summit"] = "distributed"


class DiplomacyAdjacencyBoard(Scene[DiplomacyAdjacencyBoardConfig]):
    """Deterministic diplomacy board with country sectors and explicit adjacency gates."""

    def _paint_disk(self, x: int, y: int, radius: int, value: str) -> None:
        radius_sq = radius * radius
        y0 = max(0, y - radius)
        y1 = min(self.height - 1, y + radius)
        x0 = max(0, x - radius)
        x1 = min(self.width - 1, x + radius)
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                dx = xx - x
                dy = yy - y
                if dx * dx + dy * dy <= radius_sq:
                    self.grid[yy, xx] = value

    def _draw_wall_line(self, start: tuple[int, int], end: tuple[int, int], thickness: int = 3) -> None:
        x0, y0 = start
        x1, y1 = end
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        brush = max(1, thickness // 2)
        while True:
            self._paint_disk(x0, y0, brush, "wall")
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _carve_path_line(self, start: tuple[int, int], end: tuple[int, int], thickness: int = 2) -> None:
        x0, y0 = start
        x1, y1 = end
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        brush = max(1, thickness // 2)
        while True:
            self._paint_disk(x0, y0, brush, "empty")
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def _carve_gate_on_line(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        t: float,
        radius: int = 3,
    ) -> None:
        x = int(round(start[0] + (end[0] - start[0]) * t))
        y = int(round(start[1] + (end[1] - start[1]) * t))
        self._paint_disk(x, y, radius, "empty")

    def _draw_wall_polyline(self, points: list[tuple[int, int]], thickness: int = 3) -> None:
        for start, end in zip(points[:-1], points[1:], strict=True):
            self._draw_wall_line(start, end, thickness=thickness)

    def _carve_path_polyline(self, points: list[tuple[int, int]], thickness: int = 2) -> None:
        for start, end in zip(points[:-1], points[1:], strict=True):
            self._carve_path_line(start, end, thickness=thickness)

    def _relative_point(self, x_frac: float, y_frac: float) -> tuple[int, int]:
        x = int(round((self.width - 1) * x_frac))
        y = int(round((self.height - 1) * y_frac))
        return x, y

    def _place_object(self, name: str, pos: tuple[int, int]) -> None:
        x, y = pos
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError(f"Object {name} at {(x, y)} is outside map bounds {self.width}x{self.height}")
        self.grid[y, x] = "empty"
        self.grid[y, x] = name

    def _pick_spawn_positions(
        self,
        count: int,
        center: tuple[int, int],
        focus_points: list[tuple[int, int]],
        *,
        prioritize_center_lane: bool = False,
    ) -> list[tuple[int, int]]:
        cx, cy = center
        selected: list[tuple[int, int]] = []
        used: set[tuple[int, int]] = set()

        all_empty: list[tuple[int, int]] = []
        center_lane: list[tuple[int, int]] = []
        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y, x] != "empty":
                    continue
                all_empty.append((x, y))
                center_dist = abs(x - cx) + abs(y - cy)
                if 4 <= center_dist <= 12:
                    center_lane.append((x, y))

        focus_buckets: list[list[tuple[int, int]]] = []
        for fx, fy in focus_points:
            bucket: list[tuple[int, int]] = []
            for y in range(max(0, fy - 4), min(self.height, fy + 5)):
                for x in range(max(0, fx - 4), min(self.width, fx + 5)):
                    if self.grid[y, x] != "empty":
                        continue
                    if abs(x - fx) + abs(y - fy) <= 4:
                        bucket.append((x, y))
            if bucket:
                self.rng.shuffle(bucket)
                focus_buckets.append(bucket)

        if prioritize_center_lane:
            self.rng.shuffle(center_lane)
            for candidate in center_lane:
                if len(selected) >= count:
                    break
                if candidate in used:
                    continue
                selected.append(candidate)
                used.add(candidate)

        while len(selected) < count and focus_buckets:
            progress = False
            for bucket in focus_buckets:
                while bucket and bucket[-1] in used:
                    bucket.pop()
                if not bucket:
                    continue
                candidate = bucket.pop()
                selected.append(candidate)
                used.add(candidate)
                progress = True
                if len(selected) >= count:
                    break
            if not progress:
                break

        if not prioritize_center_lane:
            self.rng.shuffle(center_lane)
            for candidate in center_lane:
                if len(selected) >= count:
                    break
                if candidate in used:
                    continue
                selected.append(candidate)
                used.add(candidate)

        self.rng.shuffle(all_empty)
        for candidate in all_empty:
            if len(selected) >= count:
                break
            if candidate in used:
                continue
            selected.append(candidate)
            used.add(candidate)

        if len(selected) < count:
            raise ValueError(f"Unable to place {count} spawn pads; only {len(selected)} empty cells available")

        return selected

    def render(self) -> None:
        cfg = self.config
        self.grid[:, :] = "empty"

        cx, cy = self.width // 2, self.height // 2
        short_side = min(self.width, self.height)
        if cfg.placement_variant == "compact":
            hub_offset_x = max(9, short_side // 5)
            hub_north_offset_y = max(7, short_side // 7)
            hub_south_offset_y = max(11, short_side // 5)
            station_offset_x = max(7, hub_offset_x // 2 + 1)
            station_north_offset_y = max(3, hub_north_offset_y // 2)
            station_south_offset_y = max(8, hub_south_offset_y // 2)
            plaza_radius = max(7, short_side // 10)
            frontier_thickness = 2
            coast_thickness = 2
            lane_thickness = 2
            core_dx = 4
            core_dy = 2
            sabotage_dy = 6
            ring_thickness = 1
            gate_radius = 2
        elif cfg.placement_variant == "world":
            hub_offset_x = max(16, short_side // 3)
            hub_north_offset_y = max(12, short_side // 4)
            hub_south_offset_y = max(18, short_side // 3)
            station_offset_x = max(11, short_side // 5)
            station_north_offset_y = max(7, hub_north_offset_y // 2)
            station_south_offset_y = max(13, short_side // 4)
            plaza_radius = max(9, short_side // 8)
            frontier_thickness = 3
            coast_thickness = 3
            lane_thickness = 3
            core_dx = 6
            core_dy = 1
            sabotage_dy = 8
            ring_thickness = 2
            gate_radius = 3
        else:
            # Baseline profile keeps travel distances short enough for reliable scripted
            # mechanic coverage while preserving clear tri-country separation.
            hub_offset_x = max(10, short_side // 5 + 1)
            hub_north_offset_y = max(7, short_side // 7)
            hub_south_offset_y = max(12, short_side // 5 + 1)
            station_offset_x = max(8, hub_offset_x // 2 + 1)
            station_north_offset_y = max(4, hub_north_offset_y // 3 + 1)
            station_south_offset_y = max(9, hub_south_offset_y // 2)
            plaza_radius = max(7, short_side // 10)
            frontier_thickness = 2
            coast_thickness = 2
            lane_thickness = 2
            core_dx = 4
            core_dy = 2
            sabotage_dy = 6
            ring_thickness = 1
            gate_radius = 2

        country_hubs = {
            "country_a_hub": (cx - hub_offset_x, cy - hub_north_offset_y),
            "country_b_hub": (cx + hub_offset_x, cy - hub_north_offset_y),
            "country_c_hub": (cx, cy + hub_south_offset_y),
        }
        country_stations = {
            "country_a_station": (cx - station_offset_x, cy - station_north_offset_y),
            "country_b_station": (cx + station_offset_x, cy - station_north_offset_y),
            "country_c_station": (cx, cy + station_south_offset_y),
        }
        core_stations: dict[str, tuple[int, int]] = {}
        if cfg.include_core_stations:
            core_stations = {
                "reactor_station": (cx, cy),
                "comms_station": (cx - core_dx, cy + core_dy),
                "diplomacy_station": (cx + core_dx, cy + core_dy),
            }
            if cfg.include_sabotage_station:
                core_stations["sabotage_station"] = (cx, cy + sabotage_dy)

        coastline_chains = [
            [
                self._relative_point(0.12, 0.17),
                self._relative_point(0.16, 0.28),
                self._relative_point(0.14, 0.39),
            ],
            [
                self._relative_point(0.88, 0.17),
                self._relative_point(0.84, 0.28),
                self._relative_point(0.86, 0.39),
            ],
            [
                self._relative_point(0.14, 0.72),
                self._relative_point(0.22, 0.84),
                self._relative_point(0.33, 0.9),
            ],
            [
                self._relative_point(0.86, 0.72),
                self._relative_point(0.78, 0.84),
                self._relative_point(0.67, 0.9),
            ],
        ]
        for chain in coastline_chains:
            self._draw_wall_polyline(chain, thickness=coast_thickness)
        island_radius = 1 if cfg.placement_variant == "compact" else 2
        for x_frac, y_frac in ((0.47, 0.14), (0.53, 0.14), (0.5, 0.2), (0.2, 0.58), (0.8, 0.58)):
            self._paint_disk(*self._relative_point(x_frac, y_frac), island_radius, "wall")

        north_frontier_y = country_hubs["country_a_hub"][1] + max(2, station_north_offset_y // 2 + 1)
        south_frontier_y = country_stations["country_c_station"][1] - max(3, station_south_offset_y // 3 + 1)
        north_frontier = [
            (country_hubs["country_a_hub"][0] + max(4, hub_offset_x // 4), north_frontier_y),
            (cx - max(4, station_offset_x // 2), north_frontier_y - 1),
            (cx + max(4, station_offset_x // 2), north_frontier_y - 1),
            (country_hubs["country_b_hub"][0] - max(4, hub_offset_x // 4), north_frontier_y),
        ]
        west_frontier = [
            (country_hubs["country_a_hub"][0] + max(4, hub_offset_x // 4), north_frontier_y + 1),
            (country_stations["country_a_station"][0] + max(3, station_offset_x // 3), cy - max(1, core_dy - 1)),
            (cx - max(6, station_offset_x // 2 + 2), cy + max(4, core_dy + 2)),
            (cx - max(5, station_offset_x // 2 + 1), south_frontier_y),
        ]
        east_frontier = [
            (country_hubs["country_b_hub"][0] - max(4, hub_offset_x // 4), north_frontier_y + 1),
            (country_stations["country_b_station"][0] - max(3, station_offset_x // 3), cy - max(1, core_dy - 1)),
            (cx + max(6, station_offset_x // 2 + 2), cy + max(4, core_dy + 2)),
            (cx + max(5, station_offset_x // 2 + 1), south_frontier_y),
        ]
        for frontier in (north_frontier, west_frontier, east_frontier):
            self._draw_wall_polyline(frontier, thickness=frontier_thickness)

        self._carve_gate_on_line(north_frontier[0], north_frontier[1], t=0.55, radius=gate_radius)
        self._carve_gate_on_line(north_frontier[1], north_frontier[2], t=0.50, radius=gate_radius)
        self._carve_gate_on_line(north_frontier[2], north_frontier[3], t=0.45, radius=gate_radius)
        self._carve_gate_on_line(west_frontier[0], west_frontier[1], t=0.45, radius=gate_radius)
        self._carve_gate_on_line(west_frontier[1], west_frontier[2], t=0.55, radius=gate_radius)
        self._carve_gate_on_line(west_frontier[2], west_frontier[3], t=0.55, radius=gate_radius)
        self._carve_gate_on_line(east_frontier[0], east_frontier[1], t=0.45, radius=gate_radius)
        self._carve_gate_on_line(east_frontier[1], east_frontier[2], t=0.55, radius=gate_radius)
        self._carve_gate_on_line(east_frontier[2], east_frontier[3], t=0.55, radius=gate_radius)

        self._paint_disk(cx, cy + 1, plaza_radius, "empty")
        self._paint_disk(cx, cy - max(2, core_dy), max(3, plaza_radius - 3), "empty")

        if core_stations:
            self._carve_path_polyline(
                [
                    country_hubs["country_a_hub"],
                    country_stations["country_a_station"],
                    core_stations["reactor_station"],
                ],
                thickness=lane_thickness,
            )
            self._carve_path_polyline(
                [
                    country_hubs["country_b_hub"],
                    country_stations["country_b_station"],
                    core_stations["reactor_station"],
                ],
                thickness=lane_thickness,
            )
            self._carve_path_polyline(
                [
                    country_hubs["country_c_hub"],
                    country_stations["country_c_station"],
                    core_stations["reactor_station"],
                ],
                thickness=lane_thickness,
            )
        self._carve_path_polyline(
            [
                country_stations["country_a_station"],
                (cx, cy - max(2, station_north_offset_y // 2)),
                country_stations["country_b_station"],
            ],
            thickness=ring_thickness,
        )
        self._carve_path_polyline(
            [
                country_stations["country_b_station"],
                (cx + max(3, station_offset_x // 3), cy + max(3, core_dy + 1)),
                country_stations["country_c_station"],
            ],
            thickness=ring_thickness,
        )
        self._carve_path_polyline(
            [
                country_stations["country_c_station"],
                (cx - max(3, station_offset_x // 3), cy + max(3, core_dy + 1)),
                country_stations["country_a_station"],
            ],
            thickness=ring_thickness,
        )
        if core_stations:
            self._carve_path_line(
                core_stations["reactor_station"],
                core_stations["comms_station"],
                thickness=lane_thickness,
            )
            self._carve_path_line(
                core_stations["reactor_station"], core_stations["diplomacy_station"], thickness=lane_thickness
            )
            if "sabotage_station" in core_stations:
                self._carve_path_line(
                    core_stations["reactor_station"],
                    core_stations["sabotage_station"],
                    thickness=lane_thickness,
                )

        supply_center_positions = [
            (cx, cy - max(2, station_north_offset_y // 2)),
            (cx + max(3, station_offset_x // 3), cy + max(3, core_dy + 1)),
            (cx - max(3, station_offset_x // 3), cy + max(3, core_dy + 1)),
        ]

        placed_objects: dict[str, tuple[int, int]] = {}
        if cfg.include_country_hubs:
            placed_objects.update(country_hubs)
        if cfg.include_country_stations:
            placed_objects.update(country_stations)
        placed_objects.update(core_stations)

        for name, pos in placed_objects.items():
            self._place_object(name, pos)
        if cfg.include_supply_centers:
            for pos in supply_center_positions:
                self._place_object("supply_center", pos)

        focus_points = list(placed_objects.values())
        if cfg.include_supply_centers:
            focus_points.extend(supply_center_positions)
        if not focus_points:
            focus_points = [(cx, cy)]
        spawn_positions = self._pick_spawn_positions(
            cfg.spawn_count,
            center=(cx, cy),
            focus_points=focus_points,
            prioritize_center_lane=(cfg.spawn_focus == "summit"),
        )
        if getattr(self, "use_instance_id_for_team_assignment", False) and self.instance_id is not None:
            spawn_symbol = f"agent.team_{self.instance_id}"
        else:
            spawn_symbol = "agent.agent"
        for x, y in spawn_positions:
            self.grid[y, x] = spawn_symbol


def campaign_anchor_hub() -> str:
    return f"{COUNTRIES[0]}_hub"


def campaign_anchor_query():
    return query(typeTag(campaign_anchor_hub()))


def campaign_phase_value(item: str) -> AnyGameValue:
    return QueryInventoryValue(query=campaign_anchor_query(), item=item)


def diplomacy_control_count_value(country: str) -> AnyGameValue:
    return QueryInventoryValue(query=query("supply_center"), item=country)


def diplomacy_campaign_leader_value() -> AnyGameValue:
    return max_value([diplomacy_control_count_value(country) for country in COUNTRIES])


def diplomacy_display_year_value() -> AnyGameValue:
    return SumGameValue(values=[campaign_phase_value("campaign_year"), val(CAMPAIGN_START_YEAR - 1)])


def diplomacy_queue_value() -> AnyGameValue:
    return SumGameValue(
        values=[
            QueryInventoryValue(query=query("country_hub"), item="queue_diplomacy"),
            QueryInventoryValue(query=query("country_hub"), item="queue_trade"),
        ],
    )


def diplomacy_win_score_value() -> AnyGameValue:
    return SumGameValue(
        values=[
            QueryInventoryValue(query=query("country_hub"), item="stability"),
            QueryInventoryValue(query=query("country_hub"), item="crisis"),
            diplomacy_queue_value(),
            diplomacy_campaign_leader_value(),
        ],
        weights=[1.0, -3.0, -1.0, 6.0],
    )


def diplomacy_defeat_pressure_value() -> AnyGameValue:
    return SumGameValue(
        values=[
            QueryInventoryValue(query=query("country_hub"), item="crisis"),
            diplomacy_queue_value(),
        ],
        weights=[1.0, 1.0],
    )


def _set_game_stat(stat_name: str, value: AnyGameValue) -> StatsMutation:
    return StatsMutation(stat=stat_name, source=value)


def diplomacy_stats_handler() -> Handler:
    win_score = diplomacy_win_score_value()
    defeat_pressure = diplomacy_defeat_pressure_value()
    anchor_query = campaign_anchor_query()
    return Handler(
        name="track_diplomacy_stats",
        mutations=[
            _set_game_stat("diplomacy/win_score", win_score),
            _set_game_stat("diplomacy/defeat_pressure", defeat_pressure),
            _set_game_stat("diplomacy/queue_pressure", diplomacy_queue_value()),
            _set_game_stat("diplomacy/stability", QueryInventoryValue(query=query("country_hub"), item="stability")),
            _set_game_stat("diplomacy/crisis", QueryInventoryValue(query=query("country_hub"), item="crisis")),
            _set_game_stat(
                "diplomacy/incidents_pending",
                QueryInventoryValue(query=query("country_hub"), item="incident_pending"),
            ),
            logStatToGame("diplomacy/win_score_integral", source=win_score),
            logStatToGame("diplomacy/defeat_pressure_integral", source=defeat_pressure),
            _set_game_stat("diplomacy/year", diplomacy_display_year_value()),
            _set_game_stat("diplomacy/season_spring", QueryInventoryValue(query=anchor_query, item="season_spring")),
            _set_game_stat("diplomacy/season_fall", QueryInventoryValue(query=anchor_query, item="season_fall")),
            _set_game_stat("diplomacy/phase_orders", QueryInventoryValue(query=anchor_query, item="phase_orders")),
            _set_game_stat("diplomacy/phase_retreat", QueryInventoryValue(query=anchor_query, item="phase_retreat")),
            _set_game_stat(
                "diplomacy/phase_adjustment",
                QueryInventoryValue(query=anchor_query, item="phase_adjustment"),
            ),
            _set_game_stat("diplomacy/country_a_centers", diplomacy_control_count_value("country_a")),
            _set_game_stat("diplomacy/country_b_centers", diplomacy_control_count_value("country_b")),
            _set_game_stat("diplomacy/country_c_centers", diplomacy_control_count_value("country_c")),
            _set_game_stat("diplomacy/campaign_leader", diplomacy_campaign_leader_value()),
            _set_game_stat("diplomacy/centers_captured", stat("game.centers_captured")),
            _set_game_stat("diplomacy/incidents_telegraphed", stat("game.incidents_telegraphed")),
            _set_game_stat("diplomacy/incidents_escalated", stat("game.incidents_escalated")),
            _set_game_stat("diplomacy/mission_victory", stat("game.mission_victory")),
            _set_game_stat("diplomacy/mission_defeat", stat("game.mission_defeat")),
        ],
    )


def reactor_station_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="reactor_station",
        on_use_handler=named_first_match(
            {
                "charge_cell": Handler(filters=[], mutations=[updateActor({"power_cell": 1})]),
            }
        ),
    )


def comms_station_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="comms_station",
        on_use_handler=named_first_match(
            {
                "encode_signal": Handler(
                    filters=[actorHas({"power_cell": 1})],
                    mutations=[updateActor({"power_cell": -1, "intel": 1})],
                ),
                "no_cell": Handler(filters=[], mutations=[]),
            }
        ),
    )


def diplomacy_station_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="diplomacy_station",
        on_use_handler=named_first_match(
            {
                "deliver_brief": Handler(
                    filters=[actorHas({"intel": 1})],
                    mutations=[
                        updateActor({"intel": -1, "influence": 1}),
                        logActorAgentStat("treaties_signed"),
                    ],
                ),
                "no_intel": Handler(filters=[], mutations=[]),
            }
        ),
    )


def sabotage_station_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="sabotage_station",
        on_use_handler=named_first_match(
            {
                "craft_kit": Handler(
                    filters=[actorHas({"intel": 1})],
                    mutations=[updateActor({"intel": -1, "sabotage_kit": 1})],
                ),
                "no_intel": Handler(filters=[], mutations=[]),
            }
        ),
    )


def country_station_config(country: str) -> GridObjectConfig:
    return GridObjectConfig(
        name=f"{country}_station",
        on_use_handler=named_first_match(
            {
                "has_country": Handler(
                    filters=[actorHasAnyOf(list(COUNTRIES))],
                    mutations=[],
                ),
                "assign_country": Handler(
                    filters=[],
                    mutations=[updateActor({country: 1})],
                ),
            }
        ),
    )


def supply_center_config() -> GridObjectConfig:
    handlers: dict[str, Handler] = {}
    capture_clear = {name: -8 for name in COUNTRIES}
    for country in COUNTRIES:
        capture_deltas = {other: delta for other, delta in capture_clear.items() if other != country}
        capture_deltas[country] = 1
        handlers[f"{country}_capture_center"] = Handler(
            filters=[
                actorHas({country: 1}),
                isNot(targetHas({country: 1})),
                targetHas({"capture_window": 1}),
            ],
            mutations=[
                updateTarget(capture_deltas),
                logActorAgentStat("centers_captured"),
                logActorAgentStat("fall_campaigns"),
                logStatToGame("centers_captured"),
            ],
        )

    handlers["idle"] = Handler(filters=[], mutations=[])

    return GridObjectConfig(
        name="supply_center",
        tags=["supply_center", "frontier_center"],
        inventory=InventoryConfig(default_limit=8),
        on_use_handler=named_first_match(handlers),
    )


def country_hub_config(country: str, profile: CountryProfile, *, campaign_anchor: bool = False) -> GridObjectConfig:
    rival_country = RIVAL_COUNTRY_BY_TARGET[country]
    initial_inventory = {"stability": profile.initial_stability, country: 1}
    if campaign_anchor:
        initial_inventory.update(
            {
                "campaign_year": 1,
                "season_spring": 1,
                "phase_orders": 1,
            }
        )

    return GridObjectConfig(
        name=f"{country}_hub",
        tags=["country_hub", "supply_center", f"country:{country}"],
        inventory=InventoryConfig(
            initial=initial_inventory,
            default_limit=200,
        ),
        on_use_handler=named_first_match(
            {
                "assign_country": Handler(
                    filters=[isNot(actorHasAnyOf(list(COUNTRIES)))],
                    mutations=[updateActor({country: 1})],
                ),
                "home_incident_response": Handler(
                    filters=[
                        actorHas({country: 1, "influence": 1}),
                        targetHas({"incident_pending": 1, "incident_window": 1}),
                    ],
                    mutations=[
                        updateActor({"influence": -1}),
                        updateTarget({"incident_pending": -1, "incident_window": -1, "stability": 2}),
                        logActorAgentStat("incidents_resolved"),
                    ],
                ),
                "foreign_incident_response": Handler(
                    filters=[
                        actorHas({"influence": 1}),
                        actorHasAnyOf(list(COUNTRIES)),
                        isNot(actorHas({country: 1})),
                        targetHas({"incident_pending": 1, "incident_window": 1}),
                    ],
                    mutations=[
                        updateActor({"influence": -1}),
                        updateTarget({"incident_pending": -1, "incident_window": -1, "stability": 1}),
                        logActorAgentStat("incidents_resolved"),
                        logActorAgentStat("cross_treaties"),
                    ],
                ),
                "home_enqueue_diplomacy": Handler(
                    filters=[actorHas({country: 1, "influence": 1})],
                    mutations=[
                        updateActor({"influence": -1}),
                        updateTarget({"queue_diplomacy": 1, "stability": 1}),
                        logActorAgentStat("queue_submitted"),
                        logActorAgentStat("home_reforms"),
                    ],
                ),
                "foreign_treaty": Handler(
                    filters=[
                        actorHas({"influence": 1}),
                        actorHasAnyOf(list(COUNTRIES)),
                        isNot(actorHas({country: 1})),
                    ],
                    mutations=[
                        updateActor({"influence": -1}),
                        updateTarget({"queue_diplomacy": 1}),
                        logActorAgentStat("queue_submitted"),
                        logActorAgentStat("cross_treaties"),
                    ],
                ),
                "home_enqueue_trade": Handler(
                    filters=[actorHas({country: 1, "intel": 1})],
                    mutations=[
                        updateActor({"intel": -1}),
                        updateTarget({"queue_trade": 1, "stability": 1}),
                        logActorAgentStat("queue_submitted"),
                        logActorAgentStat("home_trade_routes"),
                    ],
                ),
                "foreign_enqueue_trade": Handler(
                    filters=[
                        actorHas({"intel": 1}),
                        actorHasAnyOf(list(COUNTRIES)),
                        isNot(actorHas({country: 1})),
                    ],
                    mutations=[
                        updateActor({"intel": -1}),
                        updateTarget({"queue_trade": 1}),
                        logActorAgentStat("queue_submitted"),
                        logActorAgentStat("cross_trade_routes"),
                    ],
                ),
                "home_counter_ops": Handler(
                    filters=[actorHas({country: 1, "sabotage_kit": 1}), targetHas({"crisis": 1})],
                    mutations=[
                        updateActor({"sabotage_kit": -1}),
                        updateTarget({"crisis": -1, "stability": 1}),
                        logActorAgentStat("counter_ops"),
                    ],
                ),
                "rival_sabotage_hub": Handler(
                    filters=[actorHas({"sabotage_kit": 1, rival_country: 1})],
                    mutations=[
                        updateActor({"sabotage_kit": -1}),
                        updateTarget(
                            {
                                "crisis": profile.sabotage_impact + 1,
                                "stability": -(profile.sabotage_impact + 1),
                            }
                        ),
                        logActorAgentStat("sabotage_executed"),
                        logActorAgentStat("rival_strikes"),
                    ],
                ),
                "sabotage_hub": Handler(
                    filters=[actorHas({"sabotage_kit": 1}), isNot(actorHas({country: 1}))],
                    mutations=[
                        updateActor({"sabotage_kit": -1}),
                        updateTarget({"crisis": profile.sabotage_impact, "stability": -profile.sabotage_impact}),
                        logActorAgentStat("sabotage_executed"),
                    ],
                ),
                "no_payload": Handler(filters=[], mutations=[]),
            }
        ),
    )


def build_country_events(
    max_steps: int,
    country_profiles: dict[str, CountryProfile] | None = None,
) -> dict[str, EventConfig]:
    profiles = country_profiles or COUNTRY_PROFILES
    events: dict[str, EventConfig] = {}
    anchor_query = campaign_anchor_query()

    for year_idx, year_start in enumerate(range(0, max_steps + 1, CAMPAIGN_YEAR_LENGTH)):
        spring_retreat_start = year_start + SPRING_ORDERS_LENGTH
        fall_orders_start = spring_retreat_start + SPRING_RETREAT_LENGTH
        fall_retreat_start = fall_orders_start + FALL_ORDERS_LENGTH
        winter_start = fall_retreat_start + FALL_RETREAT_LENGTH
        next_spring_start = year_start + CAMPAIGN_YEAR_LENGTH

        if spring_retreat_start <= max_steps:
            events[f"campaign_{year_idx}_spring_retreat"] = EventConfig(
                name=f"campaign_{year_idx}_spring_retreat",
                target_query=anchor_query,
                timesteps=[spring_retreat_start],
                mutations=[updateTarget({"phase_orders": -1, "phase_retreat": 1})],
                max_targets=1,
            )
        if fall_orders_start <= max_steps:
            events[f"campaign_{year_idx}_fall_orders"] = EventConfig(
                name=f"campaign_{year_idx}_fall_orders",
                target_query=anchor_query,
                timesteps=[fall_orders_start],
                mutations=[
                    updateTarget({"phase_retreat": -1, "season_spring": -1, "season_fall": 1, "phase_orders": 1}),
                    queryDelta(query("supply_center"), {"capture_window": 1}),
                ],
                max_targets=1,
            )
        if fall_retreat_start <= max_steps:
            events[f"campaign_{year_idx}_fall_retreat"] = EventConfig(
                name=f"campaign_{year_idx}_fall_retreat",
                target_query=anchor_query,
                timesteps=[fall_retreat_start],
                mutations=[
                    updateTarget({"phase_orders": -1, "phase_retreat": 1}),
                    queryDelta(query("supply_center"), {"capture_window": -1}),
                ],
                max_targets=1,
            )
        if winter_start <= max_steps:
            events[f"campaign_{year_idx}_winter_adjustment"] = EventConfig(
                name=f"campaign_{year_idx}_winter_adjustment",
                target_query=anchor_query,
                timesteps=[winter_start],
                mutations=[updateTarget({"phase_retreat": -1, "phase_adjustment": 1})],
                max_targets=1,
            )
            for country in profiles:
                events[f"campaign_{year_idx}_{country}_winter_stability"] = EventConfig(
                    name=f"campaign_{year_idx}_{country}_winter_stability",
                    target_query=query("supply_center"),
                    timesteps=[winter_start],
                    filters=[targetHas({country: 1})],
                    mutations=[
                        queryDelta(query(typeTag(f"{country}_hub")), {"stability": WINTER_STABILITY_PER_CENTER}),
                        logStatToGame("winter_adjustments"),
                    ],
                )
        if next_spring_start <= max_steps:
            events[f"campaign_{year_idx}_next_spring"] = EventConfig(
                name=f"campaign_{year_idx}_next_spring",
                target_query=anchor_query,
                timesteps=[next_spring_start],
                mutations=[
                    updateTarget(
                        {
                            "phase_adjustment": -1,
                            "season_fall": -1,
                            "season_spring": 1,
                            "phase_orders": 1,
                            "campaign_year": 1,
                        }
                    )
                ],
                max_targets=1,
            )

    for country, profile in profiles.items():
        hub = f"{country}_hub"
        hub_query = query(typeTag(hub))
        events[f"{country}_crisis_wave"] = EventConfig(
            name=f"{country}_crisis_wave",
            target_query=hub_query,
            timesteps=periodic(start=profile.crisis_start, period=profile.crisis_period, end=max_steps),
            mutations=[updateTarget({"crisis": profile.crisis_delta, "stability": -profile.crisis_delta})],
            max_targets=1,
        )
        events[f"{country}_process_diplomacy_queue"] = EventConfig(
            name=f"{country}_process_diplomacy_queue",
            target_query=hub_query,
            timesteps=periodic(start=0, period=5, end=max_steps),
            filters=[targetHas({"queue_diplomacy": 1}), targetHas({"crisis": 1})],
            mutations=[
                updateTarget(
                    {
                        "queue_diplomacy": -1,
                        "crisis": -1,
                        "stability": profile.diplomacy_resolve,
                    }
                )
            ],
            max_targets=1,
        )
        events[f"{country}_process_trade_queue"] = EventConfig(
            name=f"{country}_process_trade_queue",
            target_query=hub_query,
            timesteps=periodic(start=0, period=7, end=max_steps),
            filters=[targetHas({"queue_trade": 1})],
            mutations=[updateTarget({"queue_trade": -1, "stability": profile.trade_resolve})],
            max_targets=1,
        )
        events[f"{country}_incident_telegraph"] = EventConfig(
            name=f"{country}_incident_telegraph",
            target_query=hub_query,
            timesteps=periodic(
                start=profile.crisis_start + 4,
                period=max(8, profile.crisis_period // 2),
                end=max_steps,
            ),
            mutations=[
                updateTarget({"incident_pending": 1, "incident_window": 2, "queue_trade": 1}),
                logStatToGame("incidents_telegraphed"),
            ],
            max_targets=1,
        )
        events[f"{country}_incident_tickdown"] = EventConfig(
            name=f"{country}_incident_tickdown",
            target_query=hub_query,
            timesteps=periodic(start=profile.crisis_start + 6, period=4, end=max_steps),
            filters=[targetHas({"incident_pending": 1, "incident_window": 1})],
            mutations=[updateTarget({"incident_window": -1})],
            max_targets=1,
        )
        events[f"{country}_incident_escalate"] = EventConfig(
            name=f"{country}_incident_escalate",
            target_query=hub_query,
            timesteps=periodic(start=profile.crisis_start + 8, period=4, end=max_steps),
            filters=[targetHas({"incident_pending": 1}), isNot(targetHas({"incident_window": 1}))],
            mutations=[
                updateTarget(
                    {
                        "incident_pending": -1,
                        "crisis": profile.crisis_delta + 1,
                        "stability": -(profile.crisis_delta + 1),
                        "queue_diplomacy": 1,
                    }
                ),
                logStatToGame("incidents_escalated"),
            ],
            max_targets=1,
        )

    outcome_anchor_country = next(iter(profiles.keys()), COUNTRIES[0])
    outcome_anchor_query = query(typeTag(f"{outcome_anchor_country}_hub"))
    events["mission_victory_check"] = EventConfig(
        name="mission_victory_check",
        target_query=outcome_anchor_query,
        timesteps=[max_steps],
        filters=[
            GameValueFilter(
                target=HandlerTarget.TARGET,
                value=diplomacy_win_score_value(),
                min=MISSION_VICTORY_SCORE,
            ),
            isNot(
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=diplomacy_defeat_pressure_value(),
                    min=MISSION_DEFEAT_PRESSURE,
                )
            ),
        ],
        mutations=[logStatToGame("mission_victory")],
        max_targets=1,
    )
    events["mission_defeat_check"] = EventConfig(
        name="mission_defeat_check",
        target_query=outcome_anchor_query,
        timesteps=[max_steps],
        filters=[
            anyOf(
                [
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=diplomacy_defeat_pressure_value(),
                        min=MISSION_DEFEAT_PRESSURE,
                    ),
                    isNot(
                        GameValueFilter(
                            target=HandlerTarget.TARGET,
                            value=diplomacy_win_score_value(),
                            min=MISSION_VICTORY_SCORE,
                        )
                    ),
                ]
            )
        ],
        mutations=[logStatToGame("mission_defeat")],
        max_targets=1,
    )
    return events


def diplomacy_global_obs() -> dict[str, AnyGameValue]:
    win_score = diplomacy_win_score_value()
    defeat_pressure = diplomacy_defeat_pressure_value()
    values: dict[str, AnyGameValue] = {
        "global.stability": QueryInventoryValue(query=query("country_hub"), item="stability"),
        "global.crisis": QueryInventoryValue(query=query("country_hub"), item="crisis"),
        "global.queue": diplomacy_queue_value(),
        "global.incident_pending": QueryInventoryValue(query=query("country_hub"), item="incident_pending"),
        "global.win_score": win_score,
        "global.defeat_pressure": defeat_pressure,
        "global.victory_margin": SumGameValue(values=[win_score, val(-MISSION_VICTORY_SCORE)]),
        "global.defeat_margin": SumGameValue(values=[defeat_pressure, val(-MISSION_DEFEAT_PRESSURE)]),
        "global.mission_victory": stat("game.mission_victory"),
        "global.mission_defeat": stat("game.mission_defeat"),
        "global.campaign_year": diplomacy_display_year_value(),
        "global.season_spring": campaign_phase_value("season_spring"),
        "global.season_fall": campaign_phase_value("season_fall"),
        "global.phase_orders": campaign_phase_value("phase_orders"),
        "global.phase_retreat": campaign_phase_value("phase_retreat"),
        "global.phase_adjustment": campaign_phase_value("phase_adjustment"),
        "global.campaign_leader": diplomacy_campaign_leader_value(),
    }
    for country in COUNTRIES:
        hub = f"{country}_hub"
        values[f"{country}.crisis"] = QueryInventoryValue(query=query(typeTag(hub)), item="crisis")
        values[f"{country}.queue"] = QueryInventoryValue(query=query(typeTag(hub)), item="queue_diplomacy")
        values[f"{country}.centers"] = diplomacy_control_count_value(country)
    return values


class DiplomacyGame(CoGameMission):
    max_steps: int = Field(default=400)
    default_variant: str | None = Field(default="world_layout")

    @classmethod
    def variant_module_prefixes(cls) -> tuple[str, ...]:
        return ("diplomacog.variants.",)

    @classmethod
    def create(cls, num_agents: int, max_steps: int) -> DiplomacyGame:
        return cls(
            name="basic",
            description="Station-loop diplomacy mission with country queues and crises",
            map_builder=cls._map(num_agents),
            num_cogs=num_agents,
            min_cogs=1,
            max_cogs=num_agents,
            max_steps=max_steps,
        )

    def with_variants(self, variants: Sequence[str | CoGameMissionVariant]) -> Self:
        copy = super().with_variants(variants)
        requested_names = _normalize_diplomacy_variant_names(
            [variant.name if isinstance(variant, CoGameMissionVariant) else variant for variant in variants]
        )
        if any(name in _diplomacy_hidden_variant_names() for name in requested_names):
            copy.default_variant = None
        return copy

    def _active_variant_names(self) -> list[str]:
        names: list[str] = []
        if self.default_variant:
            names.append(self.default_variant)
        names.extend(self._base_variants)
        return _normalize_diplomacy_variant_names(names)

    def _resolved_settings(self) -> DiplomacySettings:
        self._variant_registry = _resolve_diplomacy_variant_selection(self._active_variant_names())
        settings = DiplomacySettings.from_mission(self)
        for variant in self._variant_registry.configured():
            if hasattr(variant, "modify_mission"):
                cast(SupportsModifyMission, variant).modify_mission(settings)
        return settings

    def make_base_env(self) -> MettaGridConfig:
        settings = self._resolved_settings()
        num_cogs = cast(int, self.num_cogs)
        map_builder = self.map_builder.model_copy(deep=True)
        map_builder.width = settings.map_width
        map_builder.height = settings.map_height
        map_instance = getattr(map_builder, "instance", None)
        if map_instance is not None:
            if hasattr(map_instance, "placement_variant"):
                map_instance.placement_variant = settings.placement_variant
            if hasattr(map_instance, "spawn_count"):
                map_instance.spawn_count = num_cogs
            if hasattr(map_instance, "spawn_focus"):
                map_instance.spawn_focus = settings.spawn_focus
        game = GameConfig(
            map_builder=map_builder,
            max_steps=settings.max_steps,
            num_agents=num_cogs,
            resource_names=[],
            events={},
            obs=ObsConfig(
                global_obs=GlobalObsConfig(
                    local_position=True,
                    last_action_move=True,
                    obs={},
                ),
            ),
            actions=ActionsConfig(move=MoveActionConfig(), noop=NoopActionConfig()),
            agents=[
                AgentConfig(
                    inventory=InventoryConfig(limits={}),
                    rewards={},
                )
                for _ in range(num_cogs)
            ],
            objects={"wall": WallConfig(name="wall")},
            render=RenderConfig(
                assets={},
                agent_huds={},
                object_status={"agent": {}},
            ),
        )
        return MettaGridConfig(game=game)

    def make_env(self) -> MettaGridConfig:
        env = self.make_base_env()
        self._variant_registry.apply_to_env(self, env)
        env.label = self.full_name()
        return env

    def full_name(self) -> str:
        return f"diplomacog.{self.name}"

    @staticmethod
    def _map(num_agents: int) -> MapGen.Config:
        return MapGen.Config(
            width=60,
            height=60,
            border_width=2,
            instance=DiplomacyAdjacencyBoard.Config(
                spawn_count=num_agents,
                include_sabotage_station=True,
                placement_variant="world",
            ),
        )


def make_diplomacog_mission(num_agents: int = 24, max_steps: int = 400) -> DiplomacyGame:
    return DiplomacyGame.create(num_agents, max_steps)
