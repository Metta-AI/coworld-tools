"""Tests for eval output metric keys.

Verifies that:
- The catalog summary captures expected metric keys
- Performance recording produces expected fitness/score fields
- Trace and metrics modules expose the expected interfaces
"""

from __future__ import annotations

import random

import pytest
from cogames_agents.policy.evolution.cogsguard.evolution import (
    BehaviorDef,
    BehaviorSource,
    RoleCatalog,
    RoleDef,
    RoleTier,
    behavior_selection_weight,
    record_behavior_score,
    record_role_score,
    role_selection_weight,
)
from cogames_agents.policy.evolution.cogsguard.evolutionary_coordinator import (
    EvolutionaryRoleCoordinator,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _noop_action(_):
    return None


def _always_true(_):
    return True


def _always_false(_):
    return False


@pytest.fixture
def coordinator() -> EvolutionaryRoleCoordinator:
    return EvolutionaryRoleCoordinator(
        num_agents=4,
        rng=random.Random(42),
    )


@pytest.fixture
def catalog_with_scored_roles() -> RoleCatalog:
    catalog = RoleCatalog()
    for name in ["behav_a", "behav_b", "behav_c"]:
        catalog.add_behavior(
            name=name,
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )

    for i, (name, fitness) in enumerate([("RoleA", 0.8), ("RoleB", 0.3)]):
        role = RoleDef(
            id=-1,
            name=name,
            tiers=[RoleTier(behavior_ids=[i])],
            games=10,
            fitness=fitness,
        )
        catalog.register_role(role)

    return catalog


# ---------------------------------------------------------------------------
# Catalog summary metric keys
# ---------------------------------------------------------------------------


class TestCatalogSummaryMetricKeys:
    """Verify that get_catalog_summary returns all expected metric keys."""

    _EXPECTED_TOP_KEYS = {"generation", "games_this_generation", "num_behaviors", "num_roles", "roles"}
    _EXPECTED_ROLE_KEYS = {"name", "origin", "fitness", "games", "wins", "locked"}

    def test_top_level_keys(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        summary = coordinator.get_catalog_summary()
        assert set(summary.keys()) == self._EXPECTED_TOP_KEYS

    def test_role_entry_keys(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        summary = coordinator.get_catalog_summary()
        for role_info in summary["roles"]:
            assert set(role_info.keys()) == self._EXPECTED_ROLE_KEYS

    def test_metric_types(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        summary = coordinator.get_catalog_summary()
        assert isinstance(summary["generation"], int)
        assert isinstance(summary["games_this_generation"], int)
        assert isinstance(summary["num_behaviors"], int)
        assert isinstance(summary["num_roles"], int)
        assert isinstance(summary["roles"], list)

    def test_role_metric_types(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        summary = coordinator.get_catalog_summary()
        for role_info in summary["roles"]:
            assert isinstance(role_info["name"], str)
            assert isinstance(role_info["origin"], str)
            assert isinstance(role_info["fitness"], (int, float))
            assert isinstance(role_info["games"], int)
            assert isinstance(role_info["wins"], int)
            assert isinstance(role_info["locked"], bool)


# ---------------------------------------------------------------------------
# Role fitness metric tracking
# ---------------------------------------------------------------------------


class TestRoleFitnessMetrics:
    """Verify fitness/score fields update correctly."""

    def test_initial_fitness_zero(self) -> None:
        role = RoleDef(id=0, name="test")
        assert role.fitness == 0.0
        assert role.games == 0
        assert role.wins == 0

    def test_fitness_after_single_score(self) -> None:
        role = RoleDef(id=0, name="test")
        record_role_score(role, score=0.75, won=True)

        assert role.fitness == pytest.approx(0.75)
        assert role.games == 1
        assert role.wins == 1

    def test_fitness_after_multiple_scores(self) -> None:
        role = RoleDef(id=0, name="test")
        scores = [0.9, 0.1, 0.5, 0.7]
        for s in scores:
            record_role_score(role, score=s, won=s > 0.5, alpha=0.2)

        assert role.games == 4
        assert 0.0 < role.fitness < 1.0

    def test_wins_only_increment_on_won(self) -> None:
        role = RoleDef(id=0, name="test")
        record_role_score(role, score=0.5, won=False)
        record_role_score(role, score=0.8, won=True)
        record_role_score(role, score=0.3, won=False)

        assert role.wins == 1
        assert role.games == 3


# ---------------------------------------------------------------------------
# Behavior fitness metric tracking
# ---------------------------------------------------------------------------


class TestBehaviorFitnessMetrics:
    """Verify behavior-level fitness tracking."""

    def test_initial_behavior_fitness(self) -> None:
        b = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )
        assert b.fitness == 0.0
        assert b.games == 0

    def test_behavior_score_recording(self) -> None:
        b = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )
        record_behavior_score(b, 0.6)
        assert b.fitness == pytest.approx(0.6)
        assert b.games == 1

    def test_behavior_ema_convergence(self) -> None:
        """Repeated high scores should converge fitness toward 1.0."""
        b = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )
        for _ in range(50):
            record_behavior_score(b, 1.0, alpha=0.2)

        assert b.fitness > 0.99

    def test_behavior_selection_weight_keys(self) -> None:
        """Selection weight should be a float in valid range."""
        b = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
            games=5,
            fitness=0.5,
        )
        w = behavior_selection_weight(b)
        assert isinstance(w, float)
        assert w >= 0.1

    def test_role_selection_weight_keys(self) -> None:
        """Role selection weight should be a float in valid range."""
        role = RoleDef(id=0, name="test", games=5, fitness=0.6)
        w = role_selection_weight(role)
        assert isinstance(w, float)
        assert w >= 0.1


# ---------------------------------------------------------------------------
# Coordinator performance metrics after games
# ---------------------------------------------------------------------------


class TestCoordinatorPerformanceMetrics:
    """Test metric fields after running games through the coordinator."""

    def test_metrics_after_game_cycle(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        rng = random.Random(42)
        for agent_id in range(4):
            coordinator.assign_role(agent_id)
            coordinator.record_agent_performance(agent_id, score=rng.random(), won=True)

        coordinator.end_game(won=True)

        summary = coordinator.get_catalog_summary()
        assert summary["games_this_generation"] == 1
        # At least some roles should have been scored
        scored_roles = [r for r in summary["roles"] if r["games"] > 0]
        assert len(scored_roles) > 0

    def test_fitness_bounds(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        """All fitness values should be in [0, 1]."""
        for agent_id in range(4):
            coordinator.assign_role(agent_id)
            coordinator.record_agent_performance(agent_id, score=0.5)

        for role in coordinator.catalog.roles:
            assert 0.0 <= role.fitness <= 1.0

    def test_games_monotonically_increase(self, coordinator: EvolutionaryRoleCoordinator) -> None:
        coordinator.assign_role(0)
        role_id = coordinator.agent_assignments[0].role_id

        prev_games = coordinator.catalog.roles[role_id].games
        for _ in range(5):
            coordinator.record_agent_performance(0, score=0.5)
            curr_games = coordinator.catalog.roles[role_id].games
            assert curr_games > prev_games
            prev_games = curr_games


# ---------------------------------------------------------------------------
# Parity metrics module interface
# ---------------------------------------------------------------------------


class TestParityMetricsInterface:
    """Test that parity_metrics module functions exist and work."""

    def test_update_action_counts(self) -> None:
        from collections import Counter  # noqa: PLC0415

        from cogames_agents.policy.scripted_agent.cogsguard.parity_metrics import (  # noqa: PLC0415
            update_action_counts,
        )

        counts = Counter()
        update_action_counts(counts, "move")
        update_action_counts(counts, "move")
        update_action_counts(counts, "attack")

        assert counts["move"] == 2
        assert counts["attack"] == 1

    def test_update_move_stats(self) -> None:
        from cogames_agents.policy.scripted_agent.cogsguard.parity_metrics import (  # noqa: PLC0415
            update_move_stats,
        )

        stats = {"attempts": 0, "success": 0, "fail": 0}
        update_move_stats(stats, "move_north", success=True)
        update_move_stats(stats, "move_south", success=False)
        update_move_stats(stats, "attack", success=True)  # ignored (not move*)

        assert stats["attempts"] == 2
        assert stats["success"] == 1
        assert stats["fail"] == 1

    def test_diff_action_counts(self) -> None:
        from collections import Counter  # noqa: PLC0415

        from cogames_agents.policy.scripted_agent.cogsguard.parity_metrics import (  # noqa: PLC0415
            diff_action_counts,
        )

        a = Counter({"move": 10, "attack": 5})
        b = Counter({"move": 8, "attack": 5, "defend": 2})

        diff = diff_action_counts(a, b, top_n=5)
        diff_dict = dict(diff)
        assert "move" in diff_dict
        assert diff_dict["move"] == 2
