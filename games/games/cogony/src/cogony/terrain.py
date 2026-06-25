from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Any, Literal, override

import numpy as np
from pydantic import Field

from mettagrid.cogame.core import CoGameMissionVariant, Deps

if TYPE_CHECKING:
    from cogony.mission import CogonyMission
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.map_builder import MapBuilderConfig
from mettagrid.mapgen.area import AreaWhere
from mettagrid.mapgen.mapgen import MapGen, MapGenConfig
from mettagrid.mapgen.random.int import IntConstantDistribution
from mettagrid.mapgen.scene import (
    AnySceneConfig,
    ChildrenAction,
    GridTransform,
    Scene,
    SceneConfig,
)
from mettagrid.mapgen.scenes.asteroid_mask import AsteroidMaskConfig
from mettagrid.mapgen.scenes.biome_caves import BiomeCavesConfig
from mettagrid.mapgen.scenes.biome_city import BiomeCityConfig
from mettagrid.mapgen.scenes.biome_desert import BiomeDesertConfig
from mettagrid.mapgen.scenes.biome_forest import BiomeForestConfig
from mettagrid.mapgen.scenes.biome_plains import BiomePlainsConfig
from mettagrid.mapgen.scenes.bounded_layout import BoundedLayout
from mettagrid.mapgen.scenes.bsp import BSPConfig, BSPLayout
from mettagrid.mapgen.scenes.building_distributions import (
    DistributionConfig,
    UniformExtractorParams,
)
from mettagrid.mapgen.scenes.compound import CompoundConfig
from mettagrid.mapgen.scenes.four_corner_compounds import FourCornerCompoundsConfig
from mettagrid.mapgen.scenes.make_connected import MakeConnected
from mettagrid.mapgen.scenes.maze import MazeConfig
from mettagrid.mapgen.scenes.radial_maze import RadialMaze
from mettagrid.mapgen.scenes.random_scene import RandomScene, RandomSceneCandidate, RandomSceneConfig

HubBundle = Literal["extractors", "none", "custom"]


class MapCornerPlacementsConfig(SceneConfig):
    """Place objects at map corners. Corner indices: 0=TL, 1=TR, 2=BL, 3=BR."""

    placements: list[tuple[str, int]] = []
    offset: int = 2


class MapCornerPlacements(Scene[MapCornerPlacementsConfig]):
    def render(self) -> None:
        cfg = self.config
        h, w = self.height, self.width
        offset = max(0, int(cfg.offset))
        corners = [
            (offset, offset),
            (offset, w - 1 - offset),
            (h - 1 - offset, offset),
            (h - 1 - offset, w - 1 - offset),
        ]
        for obj_name, corner_idx in cfg.placements:
            if 0 <= corner_idx < 4 and obj_name:
                r, c = corners[corner_idx]
                if 0 <= r < h and 0 <= c < w:
                    self.grid[r, c] = obj_name


class MapCenterPlacementsConfig(SceneConfig):
    """Place objects at the exact center of the map."""

    objects: list[str] = []


class MapCenterPlacements(Scene[MapCenterPlacementsConfig]):
    def render(self) -> None:
        h, w = self.height, self.width
        cy, cx = h // 2, w // 2
        offsets = [(0, 0), (0, -2), (0, 2), (-2, 0), (2, 0)]
        for i, obj_name in enumerate(self.config.objects):
            dy, dx = offsets[i] if i < len(offsets) else (0, i)
            y, x = cy + dy, cx + dx
            if 0 <= y < h and 0 <= x < w:
                self.grid[y, x] = obj_name


class MapEdgeMidpointPlacementsConfig(SceneConfig):
    """Place objects at the midpoints of the 4 inner-arena edges.

    Accounts for cave_border so objects land between corner compounds,
    not inside the cave wall. Order: top, right, bottom, left.
    """

    objects: list[str] = []
    cave_border: int = 0


class MapEdgeMidpointPlacements(Scene[MapEdgeMidpointPlacementsConfig]):
    def render(self) -> None:
        cfg = self.config
        h, w = self.height, self.width
        b = max(0, cfg.cave_border)
        midpoints = [
            (b, w // 2),          # top edge of inner arena
            (h // 2, w - 1 - b),  # right edge of inner arena
            (h - 1 - b, w // 2),  # bottom edge of inner arena
            (h // 2, b),          # left edge of inner arena
        ]
        for i, obj_name in enumerate(cfg.objects):
            if i >= len(midpoints) or not obj_name:
                continue
            r, c = midpoints[i]
            if 0 <= r < h and 0 <= c < w:
                self.grid[r, c] = obj_name


class CaveBorderConfig(SceneConfig):
    """Fill the outer border ring with cellular-automata caves.

    The inner rectangle (inset by `border` from each edge) is left
    untouched. The outer ring is carved into connected cave passages.
    A small clearing is cut at the exact map center.
    """

    border: int = 40
    fill_prob: float = 0.42
    steps: int = 4
    birth_limit: int = 5
    death_limit: int = 3
    clearing_radius: int = 5
    corridor_width: int = 3


class CaveBorder(Scene[CaveBorderConfig]):
    def render(self) -> None:
        cfg = self.config
        h, w = self.height, self.width
        b = cfg.border
        cy, cx = h // 2, w // 2

        # Generate cave pattern for the full map
        rock = (self.rng.random((h, w)) < cfg.fill_prob).astype(np.uint8)

        def count_neighbors(a):
            a_p = np.pad(a, 1, mode="constant", constant_values=1)
            return (
                a_p[0:h, 1:w+1] + a_p[2:h+2, 1:w+1] +
                a_p[1:h+1, 0:w] + a_p[1:h+1, 2:w+2] +
                a_p[0:h, 0:w] + a_p[0:h, 2:w+2] +
                a_p[2:h+2, 0:w] + a_p[2:h+2, 2:w+2]
            )

        for _ in range(cfg.steps):
            nb = count_neighbors(rock)
            birth = nb > cfg.birth_limit
            death = nb < cfg.death_limit
            rock = np.where(birth | ((~death) & (rock == 1)), 1, 0).astype(np.uint8)

        # Only apply caves to the outer border ring — leave inner area alone
        inner_y0, inner_y1 = b, h - b
        inner_x0, inner_x1 = b, w - b

        for r in range(h):
            for c in range(w):
                if inner_y0 <= r < inner_y1 and inner_x0 <= c < inner_x1:
                    continue  # skip inner arena
                if rock[r, c] == 1:
                    self.grid[r, c] = "wall"
                else:
                    if self.grid[r, c] == "wall" or self.grid[r, c] == "empty":
                        self.grid[r, c] = "empty"

        # Cut corridors from inner arena edges to cave border (N, S, E, W)
        cw = cfg.corridor_width
        half_cw = cw // 2
        # North corridor
        for r in range(0, inner_y0 + 2):
            for dc in range(-half_cw, half_cw + 1):
                c = cx + dc
                if 0 <= c < w:
                    self.grid[r, c] = "empty"
        # South corridor
        for r in range(inner_y1 - 2, h):
            for dc in range(-half_cw, half_cw + 1):
                c = cx + dc
                if 0 <= c < w:
                    self.grid[r, c] = "empty"
        # West corridor
        for c in range(0, inner_x0 + 2):
            for dr in range(-half_cw, half_cw + 1):
                r = cy + dr
                if 0 <= r < h:
                    self.grid[r, c] = "empty"
        # East corridor
        for c in range(inner_x1 - 2, w):
            for dr in range(-half_cw, half_cw + 1):
                r = cy + dr
                if 0 <= r < h:
                    self.grid[r, c] = "empty"

        # Clear a small circle at the exact center
        cr = cfg.clearing_radius
        for dr in range(-cr, cr + 1):
            for dc in range(-cr, cr + 1):
                if dr * dr + dc * dc <= cr * cr:
                    r, c = cy + dr, cx + dc
                    if 0 <= r < h and 0 <= c < w:
                        self.grid[r, c] = "empty"


class PerimeterPlacementsConfig(SceneConfig):
    """Place objects randomly on the map perimeter at a fixed offset from edges."""

    placements: list[tuple[str, int]] = []
    offset: int = 2


class PerimeterPlacements(Scene[PerimeterPlacementsConfig]):
    """Place configured objects on unique random cells along an inset perimeter ring."""

    def render(self) -> None:
        cfg = self.config
        h, w = self.height, self.width
        offset = max(0, int(cfg.offset))

        perimeter_positions = (
            [(offset, c) for c in range(offset, w - offset)]
            + [(h - 1 - offset, c) for c in range(offset, w - offset)]
            + [(r, offset) for r in range(offset + 1, h - 1 - offset)]
            + [(r, w - 1 - offset) for r in range(offset + 1, h - 1 - offset)]
        )
        available_positions = list(dict.fromkeys(perimeter_positions))
        if not available_positions:
            return

        for obj_name, count in cfg.placements:
            spawn_count = min(max(0, int(count)), len(available_positions))
            if not obj_name or spawn_count <= 0:
                continue
            chosen = self.rng.choice(len(available_positions), size=spawn_count, replace=False)
            for idx in sorted((int(i) for i in np.atleast_1d(chosen)), reverse=True):
                r, c = available_positions.pop(idx)
                self.grid[r, c] = obj_name


class EnsureHubReachableJunctionConfig(SceneConfig):
    """Ensure each hub/ship has at least one nearby neutral junction."""

    anchor_suffixes: list[str] = [":hub", ":ship"]
    anchor_names: list[str] = ["hub", "ship"]
    junction_name: str = "junction"
    min_distance: int = 4
    max_distance: int = 15


class EnsureHubReachableJunction(Scene[EnsureHubReachableJunctionConfig]):
    def _is_hub_cell(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        return (
            any(value.endswith(s) or f"{s}:" in value for s in self.config.anchor_suffixes)
            or value in self.config.anchor_names
        )

    def _is_passable(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        if value == "empty":
            return True
        if value == self.config.junction_name:
            return True
        return self._is_hub_cell(value)

    def _reachable_cells(self, start_r: int, start_c: int) -> set[tuple[int, int]]:
        grid = self.grid
        h, w = self.height, self.width
        if not (0 <= start_r < h and 0 <= start_c < w):
            return set()
        if not self._is_passable(grid[start_r, start_c]):
            return set()

        q = deque([(start_r, start_c)])
        seen = {(start_r, start_c)}
        while q:
            r, c = q.popleft()
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr = r + dr
                nc = c + dc
                if nr < 0 or nr >= h or nc < 0 or nc >= w:
                    continue
                if (nr, nc) in seen:
                    continue
                if not self._is_passable(grid[nr, nc]):
                    continue
                seen.add((nr, nc))
                q.append((nr, nc))
        return seen

    def render(self) -> None:
        cfg = self.config
        grid = self.grid
        h, w = self.height, self.width

        hubs: list[tuple[int, int]] = []
        junctions: list[tuple[int, int]] = []
        for r in range(h):
            for c in range(w):
                cell = grid[r, c]
                if self._is_hub_cell(cell):
                    hubs.append((r, c))
                elif cell == cfg.junction_name:
                    junctions.append((r, c))

        if not hubs:
            return

        min_r2 = cfg.min_distance * cfg.min_distance
        max_r2 = cfg.max_distance * cfg.max_distance

        for hr, hc in hubs:
            reachable = self._reachable_cells(hr, hc)
            has_reachable_nearby_junction = any(
                (jr - hr) * (jr - hr) + (jc - hc) * (jc - hc) <= max_r2 and (jr, jc) in reachable
                for jr, jc in junctions
            )
            if has_reachable_nearby_junction:
                continue

            candidates: list[tuple[int, int, int]] = []
            r0 = max(0, hr - cfg.max_distance)
            r1 = min(h, hr + cfg.max_distance + 1)
            c0 = max(0, hc - cfg.max_distance)
            c1 = min(w, hc + cfg.max_distance + 1)
            for r in range(r0, r1):
                for c in range(c0, c1):
                    if grid[r, c] != "empty":
                        continue
                    if (r, c) not in reachable:
                        continue
                    d2 = (r - hr) * (r - hr) + (c - hc) * (c - hc)
                    if d2 < min_r2 or d2 > max_r2:
                        continue
                    candidates.append((d2, r, c))

            if not candidates:
                continue

            candidates.sort(key=lambda x: x[0])
            best_d2 = candidates[0][0]
            best = [(r, c) for d2, r, c in candidates if d2 == best_d2]
            idx = int(self.rng.integers(0, len(best)))
            rr, cc = best[idx]
            grid[rr, cc] = cfg.junction_name
            junctions.append((rr, cc))


def find_arena(builder: MapBuilderConfig | SceneConfig) -> ArenaConfig | None:
    """Unwrap nested MapGen.Config layers and return the ArenaConfig, if any."""
    if not isinstance(builder, MapGen.Config) or builder.instance is None:
        return None
    inst = builder.instance
    if isinstance(inst, MapGen.Config) and inst.instance is not None:
        inst = inst.instance
    return inst if isinstance(inst, ArenaConfig) else None


class ArenaConfig(SceneConfig):
    # Core composition
    spawn_count: int

    # Biome / dungeon structure
    base_biome: str = "plains"
    base_biome_config: dict[str, Any] = {}

    #### Building placement ####

    # How much of the map is covered by buildings
    building_coverage: float = 0.05
    # Resource placement (building-based API)
    # Defines the set of buildings that can be placed on the map
    building_names: list[str] | None = None
    # What proportion of buildings are of a type, falls back to default if not set
    # If building_names is not set, this is used to determine the buildings
    building_weights: dict[str, float] | None = None

    # Hub config. `spawn_count` will be set based on `spawn_count` in this config.
    # Used when `compounds` is empty (default single-hub layout).
    hub: CompoundConfig = CompoundConfig(
        hub_object="empty",
        corner_bundle="none",
        cross_bundle="none",
        cross_distance=7,
    )

    # Multi-compound layout. Each entry is (location, CompoundConfig).
    # Locations: "center", "nw", "ne", "sw", "se".
    # "center" places the compound in the full area (default single-hub layout).
    # Corner locations use FourCornerCompounds for quadrant placement.
    compounds: list[tuple[str, CompoundConfig]] = Field(
        default_factory=lambda: [
            (
                "center",
                CompoundConfig(
                    hub_object="empty",
                    corner_bundle="none",
                    cross_bundle="none",
                    cross_distance=7,
                ),
            )
        ]
    )

    # Optional asteroid-shaped boundary mask.
    asteroid_mask: AsteroidMaskConfig | None = None

    # Objects to place at map corners (not Compound corners). List of (object_name, corner_index).
    # Corner indices: 0=top-left, 1=top-right, 2=bottom-left, 3=bottom-right.
    map_corner_placements: list[tuple[str, int]] = []
    # Inset used for map_corner_placements.
    map_corner_offset: int = 2
    # Objects to place randomly on the perimeter (object_name, count).
    map_perimeter_placements: list[tuple[str, int]] = []
    # Objects to place at the exact center of the map.
    map_center_objects: list[str] = []
    # Objects to place at midpoints of the 4 map edges (top, right, bottom, left).
    map_edge_midpoint_objects: list[str] = []
    # Width of cave border ring around the inner arena (0 = disabled).
    cave_border: int = 0

    #### Layers ####

    biome_weights: dict[str, float] | None = None
    dungeon_weights: dict[str, float] | None = None
    biome_count: int | None = None
    dungeon_count: int | None = None
    density_scale: float = 0.9
    max_biome_zone_fraction: float = 0.27
    max_dungeon_zone_fraction: float = 0.2

    #### Distributions ####

    # How buildings are distributed on the map
    distribution: DistributionConfig = DistributionConfig()

    # How buildings are distributed on the map per building type, falls back to global distribution if not set
    building_distributions: dict[str, DistributionConfig] | None = None


class Arena(Scene[ArenaConfig]):
    def render(self) -> None:
        # No direct drawing; composition is done via children actions
        return

    def get_children(self) -> list[ChildrenAction]:
        cfg = self.config

        # Base biome map
        biome_map: dict[str, type[SceneConfig]] = {
            "caves": BiomeCavesConfig,
            "forest": BiomeForestConfig,
            "desert": BiomeDesertConfig,
            "city": BiomeCityConfig,
            "plains": BiomePlainsConfig,
        }
        if cfg.base_biome not in biome_map:
            raise ValueError(f"Unknown base_biome '{cfg.base_biome}'. Valid: {sorted(biome_map)}")
        BaseCfgModel: type[SceneConfig] = biome_map[cfg.base_biome]
        base_cfg: SceneConfig = BaseCfgModel.model_validate(cfg.base_biome_config or {})

        # Building weights
        default_building_weights: dict[str, float] = {}

        weights_dict: dict[str, float] = (
            {str(k): v for k, v in cfg.building_weights.items()} if cfg.building_weights is not None else {}
        )
        if not weights_dict:
            if cfg.building_names is not None:
                weights_dict = {name: default_building_weights.get(name, 1.0) for name in cfg.building_names}
            else:
                weights_dict = {k: v for k, v in default_building_weights.items()}

        building_names_final = list(dict.fromkeys(list((cfg.building_names or list(weights_dict)))))
        building_weights_final = {
            name: weights_dict.get(name, default_building_weights.get(name, 1.0)) for name in building_names_final
        }

        # Autoscale counts
        def _autoscale_zone_counts(
            w: int, h: int, *, biome_density: float = 1.0, dungeon_density: float = 1.0
        ) -> tuple[int, int]:
            area = max(1, w * h)
            biome_divisor = max(800, int(1600 / max(0.1, biome_density)))
            dungeon_divisor = max(800, int(1500 / max(0.1, dungeon_density)))
            biomes = max(3, min(48, area // biome_divisor))
            dungeons = max(3, min(48, area // dungeon_divisor))
            return int(biomes), int(dungeons)

        biome_count = cfg.biome_count
        dungeon_count = cfg.dungeon_count
        if biome_count is None or dungeon_count is None:
            auto_biomes, auto_dungeons = _autoscale_zone_counts(
                self.width, self.height, biome_density=cfg.density_scale, dungeon_density=cfg.density_scale
            )
            biome_count = auto_biomes if biome_count is None else biome_count
            dungeon_count = auto_dungeons if dungeon_count is None else dungeon_count

        def _min_count_for_fraction(frac: float) -> int:
            if frac <= 0:
                return 1
            return int(np.ceil(1.0 / min(0.9, max(0.02, float(frac)))))

        biome_count = max(int(biome_count), _min_count_for_fraction(cfg.max_biome_zone_fraction))
        dungeon_count = max(int(dungeon_count), _min_count_for_fraction(cfg.max_dungeon_zone_fraction))

        # Candidates
        def _make_biome_candidates(weights: dict[str, float] | None) -> list[RandomSceneCandidate]:
            defaults = {"caves": 0.0, "forest": 1.0, "desert": 1.0, "city": 1.0, "plains": 1.0}
            w = {**defaults, **(weights or {})}
            cands: list[RandomSceneCandidate] = []
            if w.get("caves", 0) > 0:
                cands.append(RandomSceneCandidate(scene=BiomeCavesConfig(), weight=w["caves"]))
            if w.get("forest", 0) > 0:
                cands.append(RandomSceneCandidate(scene=BiomeForestConfig(), weight=w["forest"]))
            if w.get("desert", 0) > 0:
                cands.append(RandomSceneCandidate(scene=BiomeDesertConfig(), weight=w["desert"]))
            if w.get("city", 0) > 0:
                cands.append(RandomSceneCandidate(scene=BiomeCityConfig(), weight=w["city"]))
            if w.get("plains", 0) > 0:
                cands.append(RandomSceneCandidate(scene=BiomePlainsConfig(), weight=w["plains"]))
            return cands

        def _make_dungeon_candidates(weights: dict[str, float] | None) -> list[RandomSceneCandidate]:
            defaults = {"bsp": 0.0, "maze": 1.0, "radial": 1.0}
            w = {**defaults, **(weights or {})}
            cands: list[RandomSceneCandidate] = []
            if w.get("bsp", 0) > 0:
                cands.append(
                    RandomSceneCandidate(
                        scene=BSPConfig(
                            rooms=4,
                            min_room_size=6,
                            min_room_size_ratio=0.35,
                            max_room_size_ratio=0.75,
                        ),
                        weight=w["bsp"],
                    )
                )
            if w.get("maze", 0) > 0:
                maze_weight = w["maze"]
                cands.append(
                    RandomSceneCandidate(
                        scene=MazeConfig(
                            algorithm="dfs",
                            room_size=IntConstantDistribution(value=3),
                            wall_size=IntConstantDistribution(value=1),
                        ),
                        weight=maze_weight * 0.6,
                    )
                )
                cands.append(
                    RandomSceneCandidate(
                        scene=MazeConfig(
                            algorithm="kruskal",
                            room_size=IntConstantDistribution(value=3),
                            wall_size=IntConstantDistribution(value=1),
                        ),
                        weight=maze_weight * 0.4,
                    )
                )
            if w.get("radial", 0) > 0:
                cands.append(
                    RandomSceneCandidate(
                        scene=RadialMaze.Config(arms=8, arm_width=1, clear_background=False, outline_walls=False),
                        weight=w["radial"],
                    )
                )
            return cands

        biome_max_w = max(10, int(min(self.width * cfg.max_biome_zone_fraction, self.width // 2)))
        biome_max_h = max(10, int(min(self.height * cfg.max_biome_zone_fraction, self.height // 2)))
        dungeon_max_w = max(10, int(min(self.width * cfg.max_dungeon_zone_fraction, self.width // 2)))
        dungeon_max_h = max(10, int(min(self.height * cfg.max_dungeon_zone_fraction, self.height // 2)))

        def _wrap_in_layout(scene_cfg: SceneConfig, tag: str, max_w: int, max_h: int) -> SceneConfig:
            return BoundedLayout.Config(
                max_width=max_w,
                max_height=max_h,
                tag=tag,
                children=[
                    ChildrenAction(
                        scene=scene_cfg,
                        where=AreaWhere(tags=[tag]),
                        limit=1,
                        order_by="first",
                    )
                ],
            )

        biome_layer: ChildrenAction | None = None
        biome_cands = _make_biome_candidates(cfg.biome_weights)
        if biome_cands:
            biome_fill_count = max(1, int(biome_count * 0.6))
            biome_layer = ChildrenAction(
                scene=BSPLayout.Config(
                    area_count=biome_count,
                    children=[
                        ChildrenAction(
                            scene=_wrap_in_layout(
                                RandomScene.Config(candidates=biome_cands),
                                tag="biome.zone",
                                max_w=biome_max_w,
                                max_h=biome_max_h,
                            ),
                            where=AreaWhere(tags=["zone"]),
                            order_by="random",
                            limit=biome_fill_count,
                        )
                    ],
                ),
                where="full",
            )

        dungeon_layer: ChildrenAction | None = None
        dungeon_cands = _make_dungeon_candidates(cfg.dungeon_weights)
        if dungeon_cands:
            dungeon_fill_count = max(1, int(dungeon_count * 0.5))
            dungeon_layer = ChildrenAction(
                scene=BSPLayout.Config(
                    area_count=dungeon_count,
                    children=[
                        ChildrenAction(
                            scene=_wrap_in_layout(
                                RandomSceneConfig(candidates=dungeon_cands),
                                tag="dungeon.zone",
                                max_w=dungeon_max_w,
                                max_h=dungeon_max_h,
                            ),
                            where=AreaWhere(tags=["zone"]),
                            order_by="random",
                            limit=dungeon_fill_count,
                        )
                    ],
                ),
                where="full",
                order_by="first",
                limit=1,
            )

        children: list[ChildrenAction] = []

        # Base shell first
        children.append(ChildrenAction(scene=base_cfg, where="full"))

        if biome_layer is not None:
            children.append(biome_layer)
        if dungeon_layer is not None:
            children.append(dungeon_layer)

        asteroid_mask = cfg.asteroid_mask
        if asteroid_mask is None and min(self.width, self.height) >= 80:
            asteroid_mask = AsteroidMaskConfig()
        if asteroid_mask is not None:
            children.append(ChildrenAction(scene=asteroid_mask, where="full"))

        if building_names_final:
            children.append(
                ChildrenAction(
                    scene=UniformExtractorParams(
                        target_coverage=cfg.building_coverage,
                        building_names=building_names_final,
                        building_weights=building_weights_final,
                        clear_existing=False,
                        distribution=cfg.distribution,
                        building_distributions=cfg.building_distributions,
                    ),
                    where="full",
                )
            )

        # Connectivity + hub
        children.append(
            ChildrenAction(
                scene=cfg.hub.model_copy(deep=True, update={"spawn_count": cfg.spawn_count}),
                where="full",
            )
        )

        children.append(
            ChildrenAction(
                scene=MakeConnected.Config(),
                where="full",
            )
        )

        if cfg.map_perimeter_placements:
            children.append(
                ChildrenAction(
                    scene=PerimeterPlacements.Config(placements=cfg.map_perimeter_placements, offset=2),
                    where="full",
                )
            )
        if cfg.map_corner_placements:
            children.append(
                ChildrenAction(
                    scene=MapCornerPlacements.Config(
                        placements=cfg.map_corner_placements,
                        offset=cfg.map_corner_offset,
                    ),
                    where="full",
                )
            )
        if cfg.map_center_objects:
            children.append(
                ChildrenAction(
                    scene=MapCenterPlacementsConfig(objects=cfg.map_center_objects),
                    where="full",
                )
            )
        if cfg.map_edge_midpoint_objects:
            children.append(
                ChildrenAction(
                    scene=MapEdgeMidpointPlacementsConfig(objects=cfg.map_edge_midpoint_objects, cave_border=cfg.cave_border),
                    where="full",
                )
            )

        return children


class SequentialArenaConfig(ArenaConfig):
    _scene_cls = None


class SequentialArena(Scene[SequentialArenaConfig]):
    def render(self) -> None:
        pass

    def get_children(self) -> list[ChildrenAction]:
        cfg = self.config
        biome_map: dict[str, type[SceneConfig]] = {
            "caves": BiomeCavesConfig,
            "forest": BiomeForestConfig,
            "desert": BiomeDesertConfig,
            "city": BiomeCityConfig,
            "plains": BiomePlainsConfig,
        }
        BaseCfgModel = biome_map.get(cfg.base_biome)
        if BaseCfgModel is None:
            raise ValueError(f"Unknown base_biome '{cfg.base_biome}'. Valid: {sorted(biome_map)}")
        base_cfg: SceneConfig = BaseCfgModel.model_validate(cfg.base_biome_config or {})
        default_building_weights: dict[str, float] = {}
        weights_dict: dict[str, float] = {str(k): v for k, v in (cfg.building_weights or {}).items()}
        if not weights_dict:
            names = cfg.building_names or list(default_building_weights)
            weights_dict = {name: default_building_weights.get(name, 1.0) for name in names}
        building_names_final = list(dict.fromkeys(cfg.building_names or list(weights_dict)))
        building_weights_final = {
            name: weights_dict.get(name, default_building_weights.get(name, 1.0)) for name in building_names_final
        }

        def _make_biomes(weights: dict[str, float] | None) -> list[SceneConfig]:
            if weights is not None and "none" in weights:
                return []
            defaults = {"caves": 0.0, "forest": 1.0, "desert": 1.0, "city": 1.0, "plains": 1.0}
            w = {**defaults, **(weights or {})}
            biome_defs = [
                ("caves", BiomeCavesConfig()),
                ("forest", BiomeForestConfig()),
                ("desert", BiomeDesertConfig()),
                ("city", BiomeCityConfig()),
                ("plains", BiomePlainsConfig()),
            ]
            return [cfg for key, cfg in biome_defs if float(w.get(key, 0.0)) > 0]

        def _make_dungeons(weights: dict[str, float] | None) -> list[SceneConfig]:
            if weights is not None and "none" in weights:
                return []
            defaults = {"maze": 1.0, "radial": 1.0}
            w = {**defaults, **(weights or {})}
            dungeons: list[SceneConfig] = []
            if float(w.get("maze", 0.0)) > 0:
                dungeons.append(
                    RandomScene.Config(
                        candidates=[
                            RandomSceneCandidate(
                                scene=MazeConfig(
                                    algorithm="dfs",
                                    room_size=IntConstantDistribution(value=3),
                                    wall_size=IntConstantDistribution(value=1),
                                ),
                                weight=0.6,
                            ),
                            RandomSceneCandidate(
                                scene=MazeConfig(
                                    algorithm="kruskal",
                                    room_size=IntConstantDistribution(value=3),
                                    wall_size=IntConstantDistribution(value=1),
                                ),
                                weight=0.4,
                            ),
                        ]
                    )
                )
            if float(w.get("radial", 0.0)) > 0:
                dungeons.append(RadialMaze.Config(arms=8, arm_width=1, clear_background=False, outline_walls=False))
            return dungeons

        biome_max_w = max(10, int(min(self.width * cfg.max_biome_zone_fraction, self.width // 2)))
        biome_max_h = max(10, int(min(self.height * cfg.max_biome_zone_fraction, self.height // 2)))
        dungeon_max_w = max(10, int(min(self.width * cfg.max_dungeon_zone_fraction, self.width // 2)))
        dungeon_max_h = max(10, int(min(self.height * cfg.max_dungeon_zone_fraction, self.height // 2)))

        def _wrap_in_layout(scene_cfg: SceneConfig, tag: str, max_w: int, max_h: int) -> SceneConfig:
            return BoundedLayout.Config(
                max_width=max_w,
                max_height=max_h,
                tag=tag,
                children=[
                    ChildrenAction(
                        scene=scene_cfg,
                        where=AreaWhere(tags=[tag]),
                        limit=1,
                        order_by="first",
                    )
                ],
            )

        def _make_layer(
            configs: list[SceneConfig],
            tag: str,
            max_w: int,
            max_h: int,
        ) -> ChildrenAction | None:
            if not configs:
                return None
            children = [
                ChildrenAction(
                    scene=_wrap_in_layout(scene_cfg, tag=tag, max_w=max_w, max_h=max_h),
                    where=AreaWhere(tags=["zone"]),
                    order_by="random",
                    limit=1,
                    lock=tag,
                )
                for scene_cfg in configs
            ]
            return ChildrenAction(
                scene=BSPLayout.Config(
                    area_count=len(configs),
                    children=children,
                ),
                where="full",
            )

        biomes = _make_biomes(cfg.biome_weights)
        dungeons = _make_dungeons(cfg.dungeon_weights)
        biome_layer = _make_layer(biomes, "biome.zone", biome_max_w, biome_max_h) if biomes else None
        dungeon_layer = _make_layer(dungeons, "dungeon.zone", dungeon_max_w, dungeon_max_h) if dungeons else None
        children: list[ChildrenAction] = []
        children.append(ChildrenAction(scene=base_cfg, where="full"))
        if biome_layer is not None:
            children.append(biome_layer)
        if dungeon_layer is not None:
            children.append(dungeon_layer)
        asteroid_mask = cfg.asteroid_mask
        if asteroid_mask is None and min(self.width, self.height) >= 80:
            asteroid_mask = AsteroidMaskConfig()
        if asteroid_mask is not None:
            children.append(ChildrenAction(scene=asteroid_mask, where="full"))
        if building_names_final:
            children.append(
                ChildrenAction(
                    scene=UniformExtractorParams(
                        target_coverage=cfg.building_coverage,
                        building_names=building_names_final,
                        building_weights=building_weights_final,
                        clear_existing=False,
                        distribution=cfg.distribution,
                        building_distributions=cfg.building_distributions,
                    ),
                    where="full",
                )
            )
        # Separate center compounds (placed directly) from corner compounds (quadrant layout).
        center_compounds = [(loc, c) for loc, c in cfg.compounds if loc == "center"]
        corner_compounds = [(loc, c) for loc, c in cfg.compounds if loc != "center"]

        if corner_compounds:
            loc_to_index = {"nw": 0, "ne": 1, "sw": 2, "se": 3}
            compound_cfgs: list[tuple[int, CompoundConfig]] = [
                (loc_to_index[loc], compound.model_copy(deep=True)) for loc, compound in corner_compounds
            ]
            spawns_per_compound = max(1, cfg.spawn_count // max(1, len(compound_cfgs)))
            fcc = FourCornerCompoundsConfig(
                compound=compound_cfgs[0][1],
                num_compounds=len(compound_cfgs),
                spawn_count=spawns_per_compound,
                inset=cfg.cave_border,
            )
            fcc.hub_objects = [c.hub_object for _, c in compound_cfgs]
            fcc.spawn_symbols = [c.spawn_symbol for _, c in compound_cfgs]
            fcc.stations_per_compound = [list(c.stations) for _, c in compound_cfgs]
            fcc.station_offsets_per_compound = [
                list(c.station_offsets) if c.station_offsets else [] for _, c in compound_cfgs
            ]
            children.append(ChildrenAction(scene=fcc, where="full"))

        for _loc, _compound in center_compounds:
            # Center compounds use cfg.hub (which variants like TeamHubVariant modify).
            children.append(
                ChildrenAction(
                    scene=cfg.hub.model_copy(deep=True, update={"spawn_count": cfg.spawn_count}),
                    where="full",
                )
            )
        if cfg.cave_border > 0:
            children.append(
                ChildrenAction(
                    scene=CaveBorderConfig(border=cfg.cave_border),
                    where="full",
                )
            )
        children.append(
            ChildrenAction(
                scene=MakeConnected.Config(),
                where="full",
            )
        )
        if cfg.map_perimeter_placements:
            children.append(
                ChildrenAction(
                    scene=PerimeterPlacements.Config(placements=cfg.map_perimeter_placements, offset=2),
                    where="full",
                )
            )
        if cfg.map_corner_placements:
            children.append(
                ChildrenAction(
                    scene=MapCornerPlacements.Config(
                        placements=cfg.map_corner_placements,
                        offset=cfg.map_corner_offset,
                    ),
                    where="full",
                )
            )
        if cfg.map_center_objects:
            children.append(
                ChildrenAction(
                    scene=MapCenterPlacementsConfig(objects=cfg.map_center_objects),
                    where="full",
                )
            )
        if cfg.map_edge_midpoint_objects:
            children.append(
                ChildrenAction(
                    scene=MapEdgeMidpointPlacementsConfig(objects=cfg.map_edge_midpoint_objects, cave_border=cfg.cave_border),
                    where="full",
                )
            )
        children.append(
            ChildrenAction(
                scene=EnsureHubReachableJunctionConfig(max_distance=15),
                where="full",
            )
        )
        return children


class RandomTransformConfig(SceneConfig):
    scene: AnySceneConfig


class RandomTransform(Scene[RandomTransformConfig]):
    def render(self) -> None:
        return

    def get_children(self) -> list[ChildrenAction]:
        return [
            ChildrenAction(
                scene=self.config.scene.model_copy(
                    update={"transform": GridTransform(self.rng.choice(list(GridTransform)))}
                ),
                where="full",
            )
        ]


class EnvNodeVariant[T](CoGameMissionVariant, ABC):
    @abstractmethod
    def extract_node(self, env: MettaGridConfig) -> T: ...

    @abstractmethod
    def modify_node(self, node: T): ...

    @override
    def modify_env(self, mission, env) -> None:
        node = self.extract_node(env)
        self.modify_node(node)


class MapGenVariant(EnvNodeVariant[MapGenConfig]):
    @classmethod
    def extract_node(cls, env: MettaGridConfig) -> MapGenConfig:
        map_builder = env.game.map_builder
        if not isinstance(map_builder, MapGen.Config):
            raise TypeError("MapGenConfigVariant can only be applied to MapGen.Config builders")
        return map_builder


class MapSeedVariant(MapGenVariant):
    """Variant that sets the MapGen seed for deterministic map generation.

    This is primarily meant for programmatic control from experiments / pipelines:

        mission = base_mission.with_variants([MapSeedVariant(seed=1234)])
        env_cfg = mission.make_env()

    """

    name: str = "map_seed"
    description: str = "Set MapGen seed for deterministic map generation."
    seed: int

    @override
    def modify_node(self, node: MapGenConfig) -> None:
        node.seed = int(self.seed)


class ArenaVariant(EnvNodeVariant[ArenaConfig]):
    def compat(self, mission: CogonyMission) -> bool:
        env = mission.make_env()
        return isinstance(env.game.map_builder, MapGen.Config) and isinstance(
            env.game.map_builder.instance, Arena.Config
        )

    @classmethod
    def extract_node(cls, env: MettaGridConfig) -> ArenaConfig:
        assert isinstance(env.game.map_builder, MapGen.Config)
        assert isinstance(env.game.map_builder.instance, Arena.Config)
        return env.game.map_builder.instance


class SequentialArenaVariant(EnvNodeVariant[SequentialArenaConfig]):
    def compat(self, mission: CogonyMission) -> bool:
        env = mission.make_env()
        return isinstance(env.game.map_builder, MapGen.Config) and isinstance(
            env.game.map_builder.instance, SequentialArena.Config
        )

    @classmethod
    def extract_node(cls, env: MettaGridConfig) -> SequentialArenaConfig:
        assert isinstance(env.game.map_builder, MapGen.Config)
        assert isinstance(env.game.map_builder.instance, SequentialArena.Config)
        return env.game.map_builder.instance


CompoundLocation = Literal["center", "nw", "ne", "sw", "se"]


class TerrainVariant(CoGameMissionVariant):
    """Configure map size and compound placements for a base arena.

    Default: single compound in the center (standard base).
    Override compounds to place multiple compounds at corners.
    """

    name: str = "terrain"
    description: str = "Map size and compound layout."
    map_width: int = Field(default=88)
    map_height: int = Field(default=88)
    building_coverage_scale: float = Field(default=1.0)
    compound_placements: list[tuple[CompoundLocation, CompoundConfig]] = Field(default_factory=list)
    cave_border: int = Field(default=0, description="Width of cave ring around the inner arena (0 = disabled)")

    @override
    def dependencies(self) -> Deps:
        from cogony.game.teams.gear_stations import TeamGearStationsVariant  # noqa: PLC0415
        from cogony.game.teams.team import TeamVariant  # noqa: PLC0415

        return Deps(required=[TeamVariant], optional=[TeamGearStationsVariant])

    @override
    def modify_env(self, mission, env: MettaGridConfig) -> None:
        arena = find_arena(env.game.map_builder)
        if arena is None:
            return

        # Resize map.
        map_builder = env.game.map_builder
        if isinstance(map_builder, MapGen.Config):
            map_builder.width = self.map_width
            map_builder.height = self.map_height
            if self.compound_placements:
                map_builder.set_team_by_instance = True

        # Scale building density.
        if self.building_coverage_scale != 1.0:
            arena.building_coverage = arena.building_coverage * self.building_coverage_scale

        # Cave border ring.
        if self.cave_border > 0:
            arena.cave_border = self.cave_border

        # Set compound placements. When empty, the arena uses its default single hub.
        if self.compound_placements:
            hub_stations = list(arena.hub.stations)
            placements: list[tuple[str, CompoundConfig]] = []
            for loc, compound in self.compound_placements:
                compound = compound.model_copy(deep=True)
                prefix = compound.hub_object.split(":")[0] + ":"
                # Build station list from hub_stations that match this team's prefix.
                team_stations = [s for s in hub_stations if s.startswith(prefix)]
                # Rebuild offsets by matching station suffixes to the original offset map.
                orig_offset_map: dict[str, tuple[int, int]] = {}
                if compound.station_offsets is not None:
                    for s, o in zip(compound.stations, compound.station_offsets):
                        orig_offset_map[s] = o
                compound.stations = team_stations
                if orig_offset_map:
                    compound.station_offsets = [orig_offset_map.get(s, (0, 0)) for s in team_stations]
                placements.append((loc, compound))
            arena.compounds = placements
