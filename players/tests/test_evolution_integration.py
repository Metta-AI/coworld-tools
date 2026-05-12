"""Integration tests for the evolution coordinator lifecycle.

Tests the full lifecycle:
- Seeding default behaviors and roles
- Assigning roles to agents
- Recording performance
- Running through a generation cycle
- Verifying evolution produces valid offspring
"""

from __future__ import annotations

import random

import pytest
from cogames_agents.policy.evolution.cogsguard.evolution import (
    BehaviorDef,
    BehaviorSource,
)
from cogames_agents.policy.evolution.cogsguard.evolutionary_coordinator import (
    EvolutionaryRoleCoordinator,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def coordinator() -> EvolutionaryRoleCoordinator:
    """Coordinator with fixed seed for reproducibility."""
    return EvolutionaryRoleCoordinator(
        num_agents=8,
        rng=random.Random(42),
        games_per_generation=5,
    )


@pytest.fixture
def fast_evolve_coordinator() -> EvolutionaryRoleCoordinator:
    """Coordinator that evolves after just 2 games."""
    return EvolutionaryRoleCoordinator(
        num_agents=4,
        rng=random.Random(7),
        games_per_generation=2,
    )


# ---------------------------------------------------------------------------
# Seeding tests
# ---------------------------------------------------------------------------


class TestSeedingBehaviors:
    """Test that the coordinator seeds correct default behaviors."""

    def test_default_behavior_count(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        # Common(2) + Miner(3) + Scout(3) + Aligner(3) + Scrambler(2) = 13
        assert len(coordinator.catalog.behaviors) == 13

    def test_default_behavior_sources(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        sources = {b.source for b in coordinator.catalog.behaviors}
        expected = {
            BehaviorSource.COMMON,
            BehaviorSource.MINER,
            BehaviorSource.SCOUT,
            BehaviorSource.ALIGNER,
            BehaviorSource.SCRAMBLER,
        }
        assert sources == expected

    def test_default_behavior_names(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        names = {b.name for b in coordinator.catalog.behaviors}
        assert "explore" in names
        assert "recharge" in names
        assert "mine_resource" in names
        assert "deposit_resource" in names
        assert "find_extractor" in names
        assert "discover_stations" in names
        assert "get_hearts" in names
        assert "align_junction" in names
        assert "scramble_junction" in names
        assert "find_enemy_junction" in names

    def test_default_role_count(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        assert len(coordinator.catalog.roles) == 4

    def test_default_roles_are_manual_origin(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        for role in coordinator.catalog.roles:
            assert role.origin == "manual"


# ---------------------------------------------------------------------------
# Role assignment integration
# ---------------------------------------------------------------------------


class TestRoleAssignmentIntegration:
    """Test assigning roles and retrieving them."""

    def test_assign_all_agents(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        for agent_id in range(8):
            role = coordinator.assign_role(agent_id, step=agent_id * 10)
            assert role is not None
            assert role.name != ""
            assert len(role.tiers) > 0

        assert len(coordinator.agent_assignments) == 8

    def test_get_role_after_assignment(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        assigned = coordinator.assign_role(0)
        retrieved = coordinator.get_agent_role(0)
        assert retrieved is not None
        assert retrieved.name == assigned.name

    def test_get_behaviors_after_assignment(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        coordinator.assign_role(0)
        behaviors = coordinator.get_role_behaviors(0)
        assert len(behaviors) > 0
        assert all(isinstance(b, BehaviorDef) for b in behaviors)


# ---------------------------------------------------------------------------
# Performance tracking integration
# ---------------------------------------------------------------------------


class TestPerformanceTrackingIntegration:
    """Test recording performance through the coordinator."""

    def test_record_updates_role_fitness(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        coordinator.assign_role(0)
        role_id = coordinator.agent_assignments[0].role_id

        coordinator.record_agent_performance(0, score=0.9, won=True)
        assert coordinator.catalog.roles[role_id].games == 1
        assert coordinator.catalog.roles[role_id].fitness == pytest.approx(0.9)
        assert coordinator.catalog.roles[role_id].wins == 1

    def test_multiple_scores_ema(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        coordinator.assign_role(0)
        role_id = coordinator.agent_assignments[0].role_id

        coordinator.record_agent_performance(0, score=1.0, won=True)
        coordinator.record_agent_performance(0, score=0.0, won=False)

        role = coordinator.catalog.roles[role_id]
        assert role.games == 2
        # EMA: first=1.0, then 1.0*(1-0.2) + 0.0*0.2 = 0.8
        assert role.fitness == pytest.approx(0.8)

    def test_score_contributions_tracked(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        coordinator.assign_role(0)
        coordinator.record_agent_performance(0, score=0.3)
        coordinator.record_agent_performance(0, score=0.7)

        assert coordinator.agent_assignments[0].score_contributions == [0.3, 0.7]


# ---------------------------------------------------------------------------
# Full generation cycle
# ---------------------------------------------------------------------------


class TestGenerationCycle:
    """Test running through complete evolutionary generation cycles."""

    def test_single_generation(self, fast_evolve_coordinator: EvolutionaryRoleCoordinator) -> None:
        c = fast_evolve_coordinator
        initial_gen = c.generation

        # Assign and score
        for agent_id in range(4):
            c.assign_role(agent_id)
            c.record_agent_performance(agent_id, score=random.random())

        # Two games trigger evolution
        c.end_game(won=True)
        c.end_game(won=False)

        assert c.generation == initial_gen + 1
        assert c.games_this_generation == 0

    def test_evolution_produces_offspring(self, fast_evolve_coordinator: EvolutionaryRoleCoordinator) -> None:
        c = fast_evolve_coordinator

        # Give roles different fitness levels
        for i, role in enumerate(c.catalog.roles):
            role.games = 10
            role.fitness = 0.2 * (i + 1)

        for agent_id in range(4):
            c.assign_role(agent_id)

        c.end_game()
        c.end_game()

        # After evolution, should have recombined/mutated roles
        origins = {r.origin for r in c.catalog.roles}
        assert origins != {"manual"}, "Evolution should create non-manual roles"

    def test_multi_generation_no_crash(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        """Run through 5 generations without errors."""
        c = coordinator
        rng = random.Random(42)

        for _gen in range(5):
            for agent_id in range(c.num_agents):
                c.assign_role(agent_id)
                c.record_agent_performance(agent_id, score=rng.random(), won=rng.random() > 0.5)
            for _ in range(c.games_per_generation):
                c.end_game(won=rng.random() > 0.5)

        assert c.generation >= 5

    def test_evolution_clears_assignments(self, fast_evolve_coordinator: EvolutionaryRoleCoordinator) -> None:
        c = fast_evolve_coordinator
        for agent_id in range(4):
            c.assign_role(agent_id)
        assert len(c.agent_assignments) == 4

        c.end_game()
        c.end_game()

        # After evolution, assignments should be cleared
        assert len(c.agent_assignments) == 0

    def test_evolved_roles_have_valid_tiers(self, fast_evolve_coordinator: EvolutionaryRoleCoordinator) -> None:
        c = fast_evolve_coordinator
        for i, role in enumerate(c.catalog.roles):
            role.games = 5
            role.fitness = 0.5 + (i * 0.1)

        c.end_game()
        c.end_game()

        for role in c.catalog.roles:
            assert len(role.tiers) > 0, f"Role {role.name} has no tiers after evolution"
            for tier in role.tiers:
                for bid in tier.behavior_ids:
                    assert 0 <= bid < len(c.catalog.behaviors), f"Invalid behavior id {bid} in role {role.name}"


# ---------------------------------------------------------------------------
# Catalog summary integration
# ---------------------------------------------------------------------------


class TestCatalogSummaryIntegration:
    """Test catalog summary across lifecycle stages."""

    def test_summary_before_evolution(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        summary = coordinator.get_catalog_summary()
        assert summary["generation"] == 0
        assert summary["num_behaviors"] == 13
        assert summary["num_roles"] == 4
        assert len(summary["roles"]) == 4

    def test_summary_after_evolution(self, fast_evolve_coordinator: EvolutionaryRoleCoordinator) -> None:
        c = fast_evolve_coordinator
        for i, role in enumerate(c.catalog.roles):
            role.games = 5
            role.fitness = 0.3 * (i + 1)

        c.end_game()
        c.end_game()

        summary = c.get_catalog_summary()
        assert summary["generation"] == 1
        assert summary["num_roles"] > 0

    def test_summary_role_fields(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        summary = coordinator.get_catalog_summary()
        for role_info in summary["roles"]:
            assert "name" in role_info
            assert "origin" in role_info
            assert "fitness" in role_info
            assert "games" in role_info
            assert "wins" in role_info
            assert "locked" in role_info


# ---------------------------------------------------------------------------
# Reproducibility integration
# ---------------------------------------------------------------------------


class TestReproducibilityIntegration:
    """Test that full lifecycle is reproducible with fixed seed."""

    def _run_lifecycle(self, seed: int) -> dict:
        c = EvolutionaryRoleCoordinator(
            num_agents=4,
            rng=random.Random(seed),
            games_per_generation=3,
        )
        rng = random.Random(seed + 1)

        for _gen in range(3):
            for agent_id in range(4):
                c.assign_role(agent_id)
                c.record_agent_performance(agent_id, score=rng.random())
            for _ in range(c.games_per_generation):
                c.end_game()

        return c.get_catalog_summary()

    def test_same_seed_same_result(self) -> None:
        s1 = self._run_lifecycle(42)
        s2 = self._run_lifecycle(42)
        assert s1 == s2

    def test_different_seed_different_result(self) -> None:
        s1 = self._run_lifecycle(42)
        s2 = self._run_lifecycle(99)
        # Role names/fitness should differ
        names1 = [r["name"] for r in s1["roles"]]
        names2 = [r["name"] for r in s2["roles"]]
        assert names1 != names2 or s1["num_roles"] != s2["num_roles"]
