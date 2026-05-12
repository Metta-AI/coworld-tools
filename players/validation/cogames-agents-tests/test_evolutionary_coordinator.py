"""Tests for the evolutionary role coordinator."""

import random

import pytest
from cogames_agents.policy.evolution.cogsguard.evolution import EvolutionConfig
from cogames_agents.policy.evolution.cogsguard.evolutionary_coordinator import (
    EvolutionaryRoleCoordinator,
)


@pytest.fixture
def coordinator():
    """Create a coordinator with default settings."""
    return EvolutionaryRoleCoordinator(num_agents=5)


@pytest.fixture
def seeded_coordinator():
    """Create a coordinator with fixed random seed for reproducibility."""
    return EvolutionaryRoleCoordinator(
        num_agents=5,
        rng=random.Random(42),
    )


class TestEvolutionaryCoordinatorInit:
    """Tests for coordinator initialization."""

    def test_creates_default_behaviors(self, coordinator):
        """Test that default behaviors are created."""
        assert len(coordinator.catalog.behaviors) > 0

        # Check for expected behavior names
        behavior_names = [b.name for b in coordinator.catalog.behaviors]
        assert "explore" in behavior_names
        assert "mine_resource" in behavior_names
        assert "align_junction" in behavior_names
        assert "scramble_junction" in behavior_names

    def test_creates_default_roles(self, coordinator):
        """Test that default roles are created."""
        assert len(coordinator.catalog.roles) >= 4  # Miner, Scout, Aligner, Scrambler

        role_names = [r.name for r in coordinator.catalog.roles]
        assert "BaseMiner" in role_names
        assert "BaseScout" in role_names
        assert "BaseAligner" in role_names
        assert "BaseScrambler" in role_names

    def test_custom_config(self):
        """Test coordinator with custom config."""
        config = EvolutionConfig(
            min_tiers=1,
            max_tiers=2,
            mutation_rate=0.3,
        )
        coordinator = EvolutionaryRoleCoordinator(
            num_agents=5,
            config=config,
        )

        assert coordinator.config.min_tiers == 1
        assert coordinator.config.max_tiers == 2
        assert coordinator.config.mutation_rate == 0.3


class TestRoleAssignment:
    """Tests for role assignment functionality."""

    def test_assign_role_returns_role(self, coordinator):
        """Test that assign_role returns a valid role."""
        role = coordinator.assign_role(0)

        assert role is not None
        assert role.name is not None
        assert len(role.tiers) > 0

    def test_assign_role_tracks_assignment(self, coordinator):
        """Test that assignments are tracked."""
        coordinator.assign_role(0, step=100)

        assignment = coordinator.agent_assignments.get(0)
        assert assignment is not None
        assert assignment.agent_id == 0
        assert assignment.assigned_step == 100

    def test_get_agent_role(self, coordinator):
        """Test getting assigned role."""
        assigned_role = coordinator.assign_role(0)
        retrieved_role = coordinator.get_agent_role(0)

        assert retrieved_role is not None
        assert retrieved_role.name == assigned_role.name

    def test_get_agent_role_unassigned(self, coordinator):
        """Test getting role for unassigned agent."""
        role = coordinator.get_agent_role(99)
        assert role is None

    def test_get_role_behaviors(self, coordinator):
        """Test getting behaviors for assigned role."""
        coordinator.assign_role(0)
        behaviors = coordinator.get_role_behaviors(0)

        assert len(behaviors) > 0

    def test_get_role_behaviors_unassigned(self, coordinator):
        """Test getting behaviors for unassigned agent."""
        behaviors = coordinator.get_role_behaviors(99)
        assert behaviors == []


class TestPerformanceTracking:
    """Tests for performance tracking."""

    def test_record_performance_updates_fitness(self, coordinator):
        """Test that recording performance updates role fitness."""
        coordinator.assign_role(0)
        assignment = coordinator.agent_assignments[0]
        role_id = assignment.role_id
        initial_games = coordinator.catalog.roles[role_id].games

        coordinator.record_agent_performance(0, score=0.8, won=True)

        assert coordinator.catalog.roles[role_id].games > initial_games

    def test_record_performance_unassigned(self, coordinator):
        """Test recording performance for unassigned agent (no-op)."""
        # Should not raise
        coordinator.record_agent_performance(99, score=0.8)

    def test_score_contributions_tracked(self, coordinator):
        """Test that individual score contributions are tracked."""
        coordinator.assign_role(0)
        coordinator.record_agent_performance(0, score=0.5)
        coordinator.record_agent_performance(0, score=0.8)

        assignment = coordinator.agent_assignments[0]
        assert len(assignment.score_contributions) == 2
        assert 0.5 in assignment.score_contributions
        assert 0.8 in assignment.score_contributions


class TestEvolutionGeneration:
    """Tests for evolutionary generation advancement."""

    def test_end_game_increments_counter(self, coordinator):
        """Test that end_game increments games counter."""
        initial = coordinator.games_this_generation

        coordinator.end_game(won=True)

        assert coordinator.games_this_generation == initial + 1

    def test_generation_evolves_after_threshold(self, coordinator):
        """Test that new generation starts after games_per_generation."""
        coordinator.games_per_generation = 3
        initial_generation = coordinator.generation
        initial_roles = len(coordinator.catalog.roles)

        for _ in range(3):
            coordinator.end_game()

        assert coordinator.generation == initial_generation + 1
        assert coordinator.games_this_generation == 0
        # Should have created new roles
        assert len(coordinator.catalog.roles) >= initial_roles

    def test_evolution_creates_offspring(self, seeded_coordinator):
        """Test that evolution creates offspring roles."""
        seeded_coordinator.games_per_generation = 2
        initial_roles = len(seeded_coordinator.catalog.roles)

        # Add some fitness differentiation
        for i, role in enumerate(seeded_coordinator.catalog.roles):
            role.games = 10
            role.fitness = 0.5 + (i * 0.1)

        for _ in range(2):
            seeded_coordinator.end_game()

        # Should have recombined roles without unbounded growth
        assert len(seeded_coordinator.catalog.roles) <= initial_roles
        assert any(role.origin in {"mutated", "recombined"} for role in seeded_coordinator.catalog.roles)


class TestVibeMapping:
    """Tests for role-to-vibe mapping."""

    def test_map_miner_role(self, coordinator):
        """Test mapping miner role to vibe."""
        miner_role = coordinator.catalog.roles[0]  # BaseMiner
        vibe = coordinator.map_role_to_vibe(miner_role)

        assert vibe == "miner"

    def test_map_scout_role(self, coordinator):
        """Test mapping scout role to vibe."""
        scout_role = coordinator.catalog.roles[1]  # BaseScout
        vibe = coordinator.map_role_to_vibe(scout_role)

        assert vibe == "scout"

    def test_map_aligner_role(self, coordinator):
        """Test mapping aligner role to vibe."""
        aligner_role = coordinator.catalog.roles[2]  # BaseAligner
        vibe = coordinator.map_role_to_vibe(aligner_role)

        assert vibe == "aligner"

    def test_map_scrambler_role(self, coordinator):
        """Test mapping scrambler role to vibe."""
        scrambler_role = coordinator.catalog.roles[3]  # BaseScrambler
        vibe = coordinator.map_role_to_vibe(scrambler_role)

        assert vibe == "scrambler"

    def test_choose_vibe_returns_valid_vibe(self, coordinator):
        """Test that choose_vibe returns a valid vibe name."""
        vibe = coordinator.choose_vibe(0)

        assert vibe in ["miner", "scout", "aligner", "scrambler", "gear"]


class TestCatalogSummary:
    """Tests for catalog summary."""

    def test_summary_structure(self, coordinator):
        """Test that summary has expected structure."""
        summary = coordinator.get_catalog_summary()

        assert "generation" in summary
        assert "games_this_generation" in summary
        assert "num_behaviors" in summary
        assert "num_roles" in summary
        assert "roles" in summary

    def test_summary_role_details(self, coordinator):
        """Test that role details are included in summary."""
        summary = coordinator.get_catalog_summary()

        assert len(summary["roles"]) > 0
        role_info = summary["roles"][0]

        assert "name" in role_info
        assert "origin" in role_info
        assert "fitness" in role_info
        assert "games" in role_info
        assert "wins" in role_info
        assert "locked" in role_info


class TestReproducibility:
    """Tests for reproducible behavior with fixed seed."""

    def test_consistent_role_assignment(self):
        """Test that fixed seed produces consistent assignments."""
        coordinator1 = EvolutionaryRoleCoordinator(
            num_agents=5,
            rng=random.Random(42),
        )
        coordinator2 = EvolutionaryRoleCoordinator(
            num_agents=5,
            rng=random.Random(42),
        )

        vibe1 = coordinator1.choose_vibe(0)
        vibe2 = coordinator2.choose_vibe(0)

        assert vibe1 == vibe2

    def test_consistent_evolution(self):
        """Test that evolution with fixed seed is reproducible."""

        def run_evolution(seed):
            coordinator = EvolutionaryRoleCoordinator(
                num_agents=5,
                rng=random.Random(seed),
            )
            coordinator.games_per_generation = 2

            # Run through a generation
            for i in range(5):
                coordinator.assign_role(i)
                coordinator.record_agent_performance(i, score=0.5 + (i * 0.1))

            for _ in range(2):
                coordinator.end_game()

            return [r.name for r in coordinator.catalog.roles]

        roles1 = run_evolution(42)
        roles2 = run_evolution(42)

        assert roles1 == roles2
