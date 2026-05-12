"""Behavior evaluation missions.

Small deterministic CogsGuard environments for testing scripted agents.
Each mission loads a custom ASCII map from this package's
``maps/planky_evals/`` directory.
and applies generous energy/resources so the agent can focus on demonstrating the target behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from cogsguard.game.clips import ClipsConfig, ClipsVariant
from cogsguard.game.damage import DamageVariant
from cogsguard.game.energy import EnergyVariant
from cogsguard.missions.mission import CvCMission as Mission
from pydantic import Field

from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.map_builder.map_builder import MapBuilderConfig
from mettagrid.mapgen.mapgen import MapGen, MapGenConfig

MAPS_DIR = Path(__file__).resolve().parent / "maps"
_PLANKY_RESOURCES = ("carbon", "oxygen", "germanium", "silicon")

_PLANKY_EVALS_MAP_BUILDER = MapGen.Config(
    instance=MapBuilderConfig.from_uri(str(MAPS_DIR / "planky_evals" / "miner_gear.map")),
    instances=1,
    fixed_spawn_order=True,
    instance_border_width=0,
)


def _get_planky_map(map_name: str) -> MapGenConfig:
    """Load a map from the planky_evals directory."""
    map_path = MAPS_DIR / "planky_evals" / map_name
    if not map_path.exists():
        raise FileNotFoundError(f"Planky eval map not found: {map_path}")
    return MapGen.Config(
        instance=MapBuilderConfig.from_uri(str(map_path)),
        instances=1,
        fixed_spawn_order=True,
        instance_border_width=0,
    )


class _PlankyDiagnosticBase(Mission):
    """Base class for Planky behavior evaluation missions.

    Provides:
    - Custom ASCII map loading from ``planky_evals/`` directory
    - Generous energy (255 capacity + 255 regen per tick)
    - Generous team hub resources (100 of each element, 50 hearts)
    - Inventory seed support (per-mission starting items)
    - ``configure_env()`` hook for per-mission customization
    """

    map_builder: MapGenConfig = _PLANKY_EVALS_MAP_BUILDER  # type: ignore[assignment]
    min_cogs: int = 1
    max_cogs: int = 8
    map_name: str = Field(default="miner_gear.map")
    max_steps: int = Field(default=300)
    num_agents: int = 1
    num_cogs: int | None = 1

    # Per-mission inventory seed (applied to agent starting inventory)
    inventory_seed: Dict[str, int] = Field(default_factory=dict)

    # Generous team hub resources — must stay at or below the
    # _TEAM_SUFFICIENT_THRESHOLD (100) to avoid miners auto-converting to aligners.
    wealth: int = Field(default=4)

    clips_enabled: bool = Field(default=False, description="Whether clips are active in this eval")
    clips_initial_start: int = Field(default=99999)
    clips_scramble_start: int = Field(default=99999)
    clips_align_start: int = Field(default=99999)
    clips_align_all_neutral: bool = Field(default=False)
    clips_align_unlimited_targets: bool = Field(default=False)

    def configure_env(self, cfg: MettaGridConfig) -> None:
        """Hook for per-mission environment customization."""

    def make_env(self) -> MettaGridConfig:
        custom_map = _get_planky_map(self.map_name)
        mission = self.model_copy(update={"map_builder": custom_map}, deep=True).with_variants(
            [
                EnergyVariant(limit=255, initial=255),
                DamageVariant(limit=100, initial=100, regen=0),
                ClipsVariant(
                    clips_config=ClipsConfig(
                        disabled=not self.clips_enabled,
                        initial_clips_start=self.clips_initial_start,
                        scramble_start=self.clips_scramble_start,
                        align_start=self.clips_align_start,
                    )
                ),
            ]
        )
        cfg = Mission.make_env(mission)
        cfg.game.map_builder = custom_map
        cfg.game.max_steps = self.max_steps
        self._apply_hub_inventory(cfg)

        if self.inventory_seed:
            cfg.game.agent.inventory.initial = {**cfg.game.agent.inventory.initial, **self.inventory_seed}

        self.configure_env(cfg)
        return cfg

    def _apply_hub_inventory(self, cfg: MettaGridConfig) -> None:
        hub = cfg.game.objects.get("c:hub")
        if hub is None:
            return
        per_element = self.num_agents * 3 * self.wealth
        hub.inventory.initial = {
            **hub.inventory.initial,
            **{resource: per_element for resource in _PLANKY_RESOURCES},
            "heart": 5 * self.wealth,
        }


# ==============================================================================
# Miner Missions
# ==============================================================================


class PlankyMinerGear(_PlankyDiagnosticBase):
    name: str = "planky_miner_gear"
    description: str = "Miner navigates to miner station and gets gear."
    map_name: str = "miner_gear.map"
    max_steps: int = Field(default=100)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"miner": 1})


class PlankyMinerExtract(_PlankyDiagnosticBase):
    name: str = "planky_miner_extract"
    description: str = "Miner gets gear and extracts carbon from extractor."
    map_name: str = "miner_extract.map"
    max_steps: int = Field(default=200)


class PlankyMinerBestResource(_PlankyDiagnosticBase):
    name: str = "planky_miner_best_resource"
    description: str = "Miner prefers carbon (more extractors) over oxygen."
    map_name: str = "miner_best_resource.map"
    max_steps: int = Field(default=300)


class PlankyMinerDeposit(_PlankyDiagnosticBase):
    name: str = "planky_miner_deposit"
    description: str = "Miner with cargo deposits at hub."
    map_name: str = "miner_deposit.map"
    max_steps: int = Field(default=200)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"carbon": 10, "oxygen": 5})


class PlankyMinerFullCycle(_PlankyDiagnosticBase):
    name: str = "planky_miner_full_cycle"
    description: str = "Miner completes gear -> extract -> deposit cycle."
    map_name: str = "miner_full_cycle.map"
    max_steps: int = Field(default=400)


# ==============================================================================
# Aligner Missions
# ==============================================================================


class PlankyAlignerGear(_PlankyDiagnosticBase):
    name: str = "planky_aligner_gear"
    description: str = "Aligner navigates to aligner station and gets gear."
    map_name: str = "aligner_gear.map"
    max_steps: int = Field(default=100)


class PlankyAlignerHearts(_PlankyDiagnosticBase):
    name: str = "planky_aligner_hearts"
    description: str = "Aligner with gear gets hearts from hub."
    map_name: str = "aligner_hearts.map"
    max_steps: int = Field(default=200)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"aligner": 1})


class PlankyAlignerJunction(_PlankyDiagnosticBase):
    name: str = "planky_aligner_junction"
    description: str = "Aligner with gear and hearts approaches neutral junction."
    map_name: str = "aligner_junction.map"
    max_steps: int = Field(default=300)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"aligner": 1, "heart": 3})


class PlankyAlignerAvoidAOE(_PlankyDiagnosticBase):
    name: str = "planky_aligner_avoid_aoe"
    description: str = "Aligner prefers safe junction over clips-aligned one."
    map_name: str = "aligner_avoid_aoe.map"
    max_steps: int = Field(default=400)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"aligner": 1, "heart": 3})
    clips_enabled: bool = Field(default=True)
    clips_initial_start: int = Field(default=10)
    clips_scramble_start: int = Field(default=99999)
    clips_align_start: int = Field(default=99999)


class PlankyCommanderAlign(_PlankyDiagnosticBase):
    name: str = "planky_commander_align"
    description: str = "Miner sees heart-vibed junction and aligns it (commander directive)."
    map_name: str = "commander_align.map"
    max_steps: int = Field(default=400)

    def configure_env(self, cfg: MettaGridConfig) -> None:
        # Set vibe=1 (heart) on neutral junctions so the agent sees a commander directive.
        for obj in cfg.game.objects.values():
            if "junction" in obj.name and not obj.name.startswith("c:"):
                obj.vibe = 1


class PlankyCommanderScramble(_PlankyDiagnosticBase):
    name: str = "planky_commander_scramble"
    description: str = "Miner sees scrambler-vibed enemy junction and scrambles it."
    map_name: str = "commander_scramble.map"
    max_steps: int = Field(default=400)
    clips_enabled: bool = Field(default=True)
    clips_initial_start: int = Field(default=0)
    clips_scramble_start: int = Field(default=99999)
    clips_align_start: int = Field(default=0)

    def configure_env(self, cfg: MettaGridConfig) -> None:
        # Set vibe=3 (scrambler) on junctions so the agent sees a commander directive.
        # The clips:ship AoE will make the nearby junction clips-aligned at runtime.
        for obj in cfg.game.objects.values():
            if obj.name == "junction":
                obj.vibe = 3


# ==============================================================================
# Scrambler Missions
# ==============================================================================


class PlankyScramblerGear(_PlankyDiagnosticBase):
    name: str = "planky_scrambler_gear"
    description: str = "Scrambler navigates to scrambler station and gets gear."
    map_name: str = "scrambler_gear.map"
    max_steps: int = Field(default=100)


class PlankyScramblerTarget(_PlankyDiagnosticBase):
    name: str = "planky_scrambler_target"
    description: str = "Scrambler with gear and hearts approaches clips junction."
    map_name: str = "scrambler_target.map"
    max_steps: int = Field(default=300)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"scrambler": 1, "heart": 3})
    clips_enabled: bool = Field(default=True)
    clips_align_start: int = Field(default=1)
    clips_initial_start: int = Field(default=1)
    clips_scramble_start: int = Field(default=99999)
    clips_align_all_neutral: bool = Field(default=True)
    clips_align_unlimited_targets: bool = Field(default=True)


# ==============================================================================
# Scout Missions
# ==============================================================================


class PlankyScoutGear(_PlankyDiagnosticBase):
    name: str = "planky_scout_gear"
    description: str = "Scout navigates to scout station and gets gear."
    map_name: str = "scout_gear.map"
    max_steps: int = Field(default=100)


class PlankyScoutExplore(_PlankyDiagnosticBase):
    name: str = "planky_scout_explore"
    description: str = "Scout with gear explores an open area."
    map_name: str = "scout_explore.map"
    max_steps: int = Field(default=200)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"scout": 1})


# ==============================================================================
# Cross-cutting Missions
# ==============================================================================


class PlankySurviveRetreat(_PlankyDiagnosticBase):
    name: str = "planky_survive_retreat"
    description: str = "Agent with low HP retreats toward hub safety."
    map_name: str = "survive_retreat.map"
    max_steps: int = Field(default=200)


class PlankyMultiRole(_PlankyDiagnosticBase):
    name: str = "planky_multi_role"
    description: str = "Four agents with different roles work together."
    map_name: str = "multi_role.map"
    max_steps: int = Field(default=300)
    num_agents: int = 4
    num_cogs: int | None = 4


# ==============================================================================
# Navigation + Exploration Missions
# ==============================================================================


class PlankyMaze(_PlankyDiagnosticBase):
    name: str = "planky_maze"
    description: str = "Miner navigates maze to reach extractor."
    map_name: str = "maze.map"
    max_steps: int = Field(default=400)


class PlankyExplorationDistant(_PlankyDiagnosticBase):
    name: str = "planky_exploration_distant"
    description: str = "Miner finds extractor outside initial FOV."
    map_name: str = "exploration_distant.map"
    max_steps: int = Field(default=400)


class PlankyStuckCorridor(_PlankyDiagnosticBase):
    name: str = "planky_stuck_corridor"
    description: str = "Miner navigates winding corridor to reach target."
    map_name: str = "stuck_corridor.map"
    max_steps: int = Field(default=400)


# ==============================================================================
# Full Cycle Missions
# ==============================================================================


class PlankyAlignerFullCycle(_PlankyDiagnosticBase):
    name: str = "planky_aligner_full_cycle"
    description: str = "Aligner: gear -> hearts -> junction approach."
    map_name: str = "aligner_full_cycle.map"
    max_steps: int = Field(default=400)


class PlankyScramblerFullCycle(_PlankyDiagnosticBase):
    name: str = "planky_scrambler_full_cycle"
    description: str = "Scrambler: gear -> hearts -> scramble junction."
    map_name: str = "scrambler_full_cycle.map"
    max_steps: int = Field(default=400)
    clips_enabled: bool = Field(default=True)
    clips_align_start: int = Field(default=1)
    clips_initial_start: int = Field(default=1)
    clips_scramble_start: int = Field(default=99999)
    clips_align_all_neutral: bool = Field(default=True)
    clips_align_unlimited_targets: bool = Field(default=True)


class PlankyResourceChain(_PlankyDiagnosticBase):
    name: str = "planky_resource_chain"
    description: str = "Miner: mine resources -> deposit at hub end-to-end."
    map_name: str = "resource_chain.map"
    max_steps: int = Field(default=500)


# ==============================================================================
# Recovery Missions (reuse existing maps with different inventory seeds)
# ==============================================================================


class PlankyMinerReGear(_PlankyDiagnosticBase):
    name: str = "planky_miner_re_gear"
    description: str = "Miner without gear re-acquires gear then mines."
    map_name: str = "miner_extract.map"
    max_steps: int = Field(default=300)
    # No gear seed — must get gear from station first


class PlankyAlignerReGear(_PlankyDiagnosticBase):
    name: str = "planky_aligner_re_gear"
    description: str = "Aligner without gear re-acquires gear."
    map_name: str = "aligner_full_cycle.map"
    max_steps: int = Field(default=400)
    # No gear seed — must get gear from station first


class PlankyAlignerReHearts(_PlankyDiagnosticBase):
    name: str = "planky_aligner_re_hearts"
    description: str = "Aligner with gear but no hearts re-acquires hearts."
    map_name: str = "aligner_full_cycle.map"
    max_steps: int = Field(default=400)
    inventory_seed: Dict[str, int] = Field(default_factory=lambda: {"aligner": 1})


class PlankyScramblerRecovery(_PlankyDiagnosticBase):
    name: str = "planky_scrambler_recovery"
    description: str = "Scrambler without gear/hearts recovers both."
    map_name: str = "scrambler_full_cycle.map"
    max_steps: int = Field(default=400)
    clips_enabled: bool = Field(default=True)
    clips_align_start: int = Field(default=1)
    clips_initial_start: int = Field(default=1)
    clips_scramble_start: int = Field(default=99999)
    clips_align_all_neutral: bool = Field(default=True)
    clips_align_unlimited_targets: bool = Field(default=True)


# ==============================================================================
# All missions list
# ==============================================================================

PLANKY_BEHAVIOR_EVALS: list[type[_PlankyDiagnosticBase]] = [
    # Miner
    PlankyMinerGear,
    PlankyMinerExtract,
    PlankyMinerBestResource,
    PlankyMinerDeposit,
    PlankyMinerFullCycle,
    # Aligner
    PlankyAlignerGear,
    PlankyAlignerHearts,
    PlankyAlignerJunction,
    PlankyAlignerAvoidAOE,
    # Scrambler
    PlankyScramblerGear,
    PlankyScramblerTarget,
    # Scout
    PlankyScoutGear,
    PlankyScoutExplore,
    # Cross-cutting
    PlankySurviveRetreat,
    PlankyMultiRole,
    # Navigation
    PlankyMaze,
    PlankyExplorationDistant,
    PlankyStuckCorridor,
    # Full cycles
    PlankyAlignerFullCycle,
    PlankyScramblerFullCycle,
    PlankyResourceChain,
    # Recovery
    PlankyMinerReGear,
    PlankyAlignerReGear,
    PlankyAlignerReHearts,
    PlankyScramblerRecovery,
]
