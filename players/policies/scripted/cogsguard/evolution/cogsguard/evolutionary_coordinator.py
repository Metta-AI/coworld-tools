"""
Evolutionary role coordinator for CogsGuard agents.

This module extends the smart-role coordination with evolutionary capabilities,
allowing roles to evolve based on game performance.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from policies.scripted.cogsguard.evolution.cogsguard.evolution import (
    BehaviorDef,
    BehaviorSource,
    EvolutionConfig,
    RoleCatalog,
    RoleDef,
    RoleTier,
    TierSelection,
    lock_role_name_if_fit,
    materialize_role_behaviors,
    mutate_role,
    pick_role_id_weighted,
    recombine_roles,
    record_role_score,
    sample_role,
)
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from policies.scripted.cogsguard.scripted_agent.cogsguard.types import CogsguardAgentState


# Default behaviors for each role that will be registered in the catalog
def _always_true(_: CogsguardAgentState) -> bool:
    return True


def _always_false(_: CogsguardAgentState) -> bool:
    return False


def _noop_action(_: CogsguardAgentState) -> Action:
    return Action(name="noop")


if TYPE_CHECKING:
    BehaviorHook = Callable[[CogsguardAgentState], Action]
else:
    BehaviorHook = Callable[[Any], Action]


@dataclass
class AgentRoleAssignment:
    """Tracks a role assignment for an agent."""

    agent_id: int
    role_id: int
    role_name: str
    assigned_step: int = 0
    score_contributions: list[float] = field(default_factory=list)


@dataclass
class EvolutionaryRoleCoordinator:
    """Coordinates evolutionary role selection across agents.

    This coordinator maintains a catalog of behaviors and roles, assigns
    roles to agents, tracks performance, and evolves new roles based on
    fitness.

    Attributes:
        num_agents: Total number of agents to coordinate
        catalog: Registry of behaviors and roles
        config: Evolution configuration
        agent_assignments: Current role assignments per agent
        generation: Current evolutionary generation
        games_per_generation: Games to play before evolving new roles
        games_this_generation: Games played in current generation
        rng: Random number generator for reproducibility
    """

    num_agents: int
    catalog: RoleCatalog = field(default_factory=RoleCatalog)
    config: EvolutionConfig = field(default_factory=EvolutionConfig)
    agent_assignments: dict[int, AgentRoleAssignment] = field(default_factory=dict)
    generation: int = 0
    games_per_generation: int = 10
    games_this_generation: int = 0
    rng: Optional[random.Random] = None
    behavior_hooks: dict[str, BehaviorHook] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize the behavior catalog with default behaviors."""
        if not self.catalog.behaviors:
            self._seed_default_behaviors()
        if not self.catalog.roles:
            self._seed_initial_roles()

    def _seed_default_behaviors(self) -> None:
        """Register default behaviors for each role."""
        # These are placeholder behaviors that will be connected to actual
        # role implementations via the behavior functions

        # Common behaviors
        self.catalog.add_behavior(
            name="explore",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=self._behavior_act("explore"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="recharge",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=self._behavior_act("recharge"),
            should_terminate=_always_false,
            interruptible=True,
        )

        # Miner behaviors
        self.catalog.add_behavior(
            name="mine_resource",
            source=BehaviorSource.MINER,
            can_start=_always_true,
            act=self._behavior_act("mine_resource"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="deposit_resource",
            source=BehaviorSource.MINER,
            can_start=_always_true,
            act=self._behavior_act("deposit_resource"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="find_extractor",
            source=BehaviorSource.MINER,
            can_start=_always_true,
            act=self._behavior_act("find_extractor"),
            should_terminate=_always_false,
            interruptible=True,
        )

        # Scout behaviors
        self.catalog.add_behavior(
            name="discover_stations",
            source=BehaviorSource.SCOUT,
            can_start=_always_true,
            act=self._behavior_act("discover_stations"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="discover_extractors",
            source=BehaviorSource.SCOUT,
            can_start=_always_true,
            act=self._behavior_act("discover_extractors"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="discover_junctions",
            source=BehaviorSource.SCOUT,
            can_start=_always_true,
            act=self._behavior_act("discover_junctions"),
            should_terminate=_always_false,
            interruptible=True,
        )

        # Aligner behaviors
        self.catalog.add_behavior(
            name="get_hearts",
            source=BehaviorSource.ALIGNER,
            can_start=_always_true,
            act=self._behavior_act("get_hearts"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="get_influence",
            source=BehaviorSource.ALIGNER,
            can_start=_always_true,
            act=self._behavior_act("get_influence"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="align_junction",
            source=BehaviorSource.ALIGNER,
            can_start=_always_true,
            act=self._behavior_act("align_junction"),
            should_terminate=_always_false,
            interruptible=True,
        )

        # Scrambler behaviors
        self.catalog.add_behavior(
            name="scramble_junction",
            source=BehaviorSource.SCRAMBLER,
            can_start=_always_true,
            act=self._behavior_act("scramble_junction"),
            should_terminate=_always_false,
            interruptible=True,
        )
        self.catalog.add_behavior(
            name="find_enemy_junction",
            source=BehaviorSource.SCRAMBLER,
            can_start=_always_true,
            act=self._behavior_act("find_enemy_junction"),
            should_terminate=_always_false,
            interruptible=True,
        )

    def _behavior_act(self, name: str) -> BehaviorHook:
        def _act(s: CogsguardAgentState) -> Action:
            hook = self.behavior_hooks.get(name)
            if hook is None:
                return _noop_action(s)
            return hook(s)

        return _act

    def _seed_initial_roles(self) -> None:
        """Create initial role definitions for each base role type."""
        # Miner role: deposit -> mine -> find_extractor -> explore
        miner_tiers = [
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("deposit_resource")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("mine_resource")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("find_extractor")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("explore")],
                selection=TierSelection.FIXED,
            ),
        ]
        miner_role = RoleDef(
            id=-1,
            name="BaseMiner",
            tiers=miner_tiers,
            origin="manual",
        )
        self.catalog.register_role(miner_role)

        # Scout role: discover_stations -> discover_extractors -> discover_junctions -> explore
        scout_tiers = [
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("discover_stations")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("discover_extractors")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("discover_junctions")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("explore")],
                selection=TierSelection.FIXED,
            ),
        ]
        scout_role = RoleDef(
            id=-1,
            name="BaseScout",
            tiers=scout_tiers,
            origin="manual",
        )
        self.catalog.register_role(scout_role)

        # Aligner role: get_hearts -> get_influence -> align_junction -> explore
        aligner_tiers = [
            RoleTier(
                behavior_ids=[
                    self.catalog.find_behavior_id("get_hearts"),
                    self.catalog.find_behavior_id("get_influence"),
                ],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("align_junction")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("explore")],
                selection=TierSelection.FIXED,
            ),
        ]
        aligner_role = RoleDef(
            id=-1,
            name="BaseAligner",
            tiers=aligner_tiers,
            origin="manual",
        )
        self.catalog.register_role(aligner_role)

        # Scrambler role: get_hearts -> find_enemy_junction -> scramble_junction -> explore
        scrambler_tiers = [
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("get_hearts")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("find_enemy_junction")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("scramble_junction")],
                selection=TierSelection.FIXED,
            ),
            RoleTier(
                behavior_ids=[self.catalog.find_behavior_id("explore")],
                selection=TierSelection.FIXED,
            ),
        ]
        scrambler_role = RoleDef(
            id=-1,
            name="BaseScrambler",
            tiers=scrambler_tiers,
            origin="manual",
        )
        self.catalog.register_role(scrambler_role)

    def _reset_roles(self, roles: list[RoleDef]) -> None:
        """Replace the catalog roles with a new set and reassign role IDs."""
        self.catalog.roles = []
        self.catalog.next_role_id = 0
        for role in roles:
            self.catalog.register_role(role)

    def assign_role(self, agent_id: int, step: int = 0) -> RoleDef:
        """Assign a role to an agent using fitness-weighted selection.

        Args:
            agent_id: The agent to assign a role to
            step: Current simulation step

        Returns:
            The assigned RoleDef
        """
        if not self.catalog.roles:
            # Fallback: sample a new role
            new_role = sample_role(self.catalog, self.config, self.rng)
            self.catalog.register_role(new_role)

        # If we have no fitness signal yet, avoid flakiness by assigning the seeded base
        # roles in a round-robin pattern across agent ids.
        if all(role.games <= 0 for role in self.catalog.roles):
            selected_id = agent_id % len(self.catalog.roles)
        else:
            role_ids = list(range(len(self.catalog.roles)))
            selected_id = pick_role_id_weighted(self.catalog, role_ids, self.rng)

        if selected_id < 0:
            selected_id = 0

        role = self.catalog.roles[selected_id]

        self.agent_assignments[agent_id] = AgentRoleAssignment(
            agent_id=agent_id,
            role_id=selected_id,
            role_name=role.name,
            assigned_step=step,
        )

        return role

    def get_agent_role(self, agent_id: int) -> Optional[RoleDef]:
        """Get the currently assigned role for an agent."""
        assignment = self.agent_assignments.get(agent_id)
        if assignment is None:
            return None
        if 0 <= assignment.role_id < len(self.catalog.roles):
            return self.catalog.roles[assignment.role_id]
        return None

    def get_role_behaviors(self, agent_id: int) -> list[BehaviorDef]:
        """Get the materialized behaviors for an agent's current role."""
        role = self.get_agent_role(agent_id)
        if role is None:
            return []
        return materialize_role_behaviors(self.catalog, role, self.rng)

    def record_agent_performance(self, agent_id: int, score: float, won: bool = False) -> None:
        """Record performance for an agent's current role.

        Args:
            agent_id: The agent whose performance to record
            score: Performance score (0.0 to 1.0)
            won: Whether the game was won
        """
        assignment = self.agent_assignments.get(agent_id)
        if assignment is None:
            return

        assignment.score_contributions.append(score)

        if 0 <= assignment.role_id < len(self.catalog.roles):
            role = self.catalog.roles[assignment.role_id]
            record_role_score(role, score, won, self.config.fitness_alpha)
            lock_role_name_if_fit(role, self.config.lock_fitness_threshold)

    def end_game(self, won: bool = False) -> None:
        """Signal end of a game for evolutionary bookkeeping.

        Args:
            won: Whether the game was won
        """
        self.games_this_generation += 1

        # Check if we should evolve new roles
        if self.games_this_generation >= self.games_per_generation:
            self._evolve_generation()

    def _evolve_generation(self) -> None:
        """Evolve new roles based on fitness of current generation."""
        self.generation += 1
        self.games_this_generation = 0

        target_population = len(self.catalog.roles)
        if target_population < 2:
            # Not enough roles to recombine, just sample new ones
            for _ in range(2):
                new_role = sample_role(self.catalog, self.config, self.rng)
                self.catalog.register_role(new_role)
            return

        # Select top performers for reproduction
        sorted_roles = sorted(
            self.catalog.roles,
            key=lambda r: r.fitness,
            reverse=True,
        )

        # Keep top 50% of roles
        survivors = sorted_roles[: max(2, len(sorted_roles) // 2)]
        self._reset_roles(survivors)

        # Create offspring through recombination
        num_offspring = max(0, target_population - len(survivors))
        for _ in range(num_offspring):
            # Select parents weighted by fitness
            parent_ids = list(range(len(self.catalog.roles)))
            parent1_id = pick_role_id_weighted(self.catalog, parent_ids, self.rng)
            parent2_id = pick_role_id_weighted(self.catalog, parent_ids, self.rng)

            parent1 = self.catalog.roles[parent1_id] if 0 <= parent1_id < len(self.catalog.roles) else survivors[0]
            parent2 = self.catalog.roles[parent2_id] if 0 <= parent2_id < len(self.catalog.roles) else survivors[-1]

            # Recombine and mutate
            child = recombine_roles(self.catalog, parent1, parent2, self.rng)
            child = mutate_role(self.catalog, child, self.config.mutation_rate, self.rng)
            self.catalog.register_role(child)

        # Occasionally sample a completely new role for diversity
        if self.rng:
            if self.rng.random() < 0.1 and len(self.catalog.roles) < target_population:
                new_role = sample_role(self.catalog, self.config, self.rng)
                self.catalog.register_role(new_role)
        elif random.random() < 0.1 and len(self.catalog.roles) < target_population:
            new_role = sample_role(self.catalog, self.config, self.rng)
            self.catalog.register_role(new_role)

        self.agent_assignments.clear()

    def map_role_to_vibe(self, role: RoleDef) -> str:
        """Map a role definition to a vibe name for the existing system.

        This bridges the evolutionary roles to the existing vibe-based system.
        """
        # Check which behaviors dominate the role
        behavior_sources: dict[BehaviorSource, int] = {}
        for tier in role.tiers:
            for behavior_id in tier.behavior_ids:
                if 0 <= behavior_id < len(self.catalog.behaviors):
                    source = self.catalog.behaviors[behavior_id].source
                    behavior_sources[source] = behavior_sources.get(source, 0) + 1

        # Find dominant source
        if not behavior_sources:
            return "gear"  # Fallback to smart role selection

        dominant = max(behavior_sources.items(), key=lambda x: x[1])[0]

        source_to_vibe = {
            BehaviorSource.MINER: "miner",
            BehaviorSource.SCOUT: "scout",
            BehaviorSource.ALIGNER: "aligner",
            BehaviorSource.SCRAMBLER: "scrambler",
            BehaviorSource.COMMON: "gear",
        }

        return source_to_vibe.get(dominant, "gear")

    def choose_vibe(self, agent_id: int, current_step: int = 0) -> str:
        """Choose a vibe for an agent using evolutionary selection.

        This method is the main interface for the existing policy system.
        It assigns a role and returns the corresponding vibe name.

        Args:
            agent_id: The agent to choose a vibe for
            current_step: Current simulation step

        Returns:
            Vibe name (miner, scout, aligner, scrambler, or gear)
        """
        role = self.assign_role(agent_id, current_step)
        return self.map_role_to_vibe(role)

    def get_catalog_summary(self) -> dict:
        """Get a summary of the current catalog state for debugging."""
        return {
            "generation": self.generation,
            "games_this_generation": self.games_this_generation,
            "num_behaviors": len(self.catalog.behaviors),
            "num_roles": len(self.catalog.roles),
            "roles": [
                {
                    "name": r.name,
                    "origin": r.origin,
                    "fitness": r.fitness,
                    "games": r.games,
                    "wins": r.wins,
                    "locked": r.locked_name,
                }
                for r in self.catalog.roles
            ],
        }
