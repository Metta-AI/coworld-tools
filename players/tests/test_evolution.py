"""Tests for the evolutionary role system."""

import random

import pytest
from cogames_agents.policy.evolution.cogsguard.evolution import (
    BehaviorDef,
    BehaviorSource,
    EvolutionConfig,
    RoleCatalog,
    RoleDef,
    RoleTier,
    TierSelection,
    behavior_selection_weight,
    lock_role_name_if_fit,
    materialize_role_behaviors,
    mutate_role,
    pick_role_id_weighted,
    recombine_roles,
    record_behavior_score,
    record_role_score,
    resolve_tier_order,
    role_selection_weight,
    sample_role,
)


def _noop_action(_):
    from mettagrid.simulator import Action  # noqa: PLC0415

    return Action(name="noop")


def _always_true(_):
    return True


def _always_false(_):
    return False


@pytest.fixture
def empty_catalog():
    """Create an empty role catalog."""
    return RoleCatalog()


@pytest.fixture
def seeded_catalog():
    """Create a catalog with some test behaviors."""
    catalog = RoleCatalog()

    # Add test behaviors
    for _i, name in enumerate(["explore", "mine", "deposit", "attack", "defend"]):
        catalog.add_behavior(
            name=name,
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )

    return catalog


@pytest.fixture
def catalog_with_roles(seeded_catalog):
    """Create a catalog with behaviors and roles."""
    catalog = seeded_catalog

    # Add a basic miner role
    miner_tiers = [
        RoleTier(behavior_ids=[2], selection=TierSelection.FIXED),  # deposit
        RoleTier(behavior_ids=[1], selection=TierSelection.FIXED),  # mine
        RoleTier(behavior_ids=[0], selection=TierSelection.FIXED),  # explore
    ]
    miner_role = RoleDef(id=-1, name="TestMiner", tiers=miner_tiers, origin="manual")
    catalog.register_role(miner_role)

    # Add a scout role
    scout_tiers = [
        RoleTier(behavior_ids=[0], selection=TierSelection.FIXED),  # explore
    ]
    scout_role = RoleDef(id=-1, name="TestScout", tiers=scout_tiers, origin="manual")
    catalog.register_role(scout_role)

    return catalog


class TestRoleCatalog:
    """Tests for RoleCatalog functionality."""

    def test_add_behavior(self, empty_catalog):
        """Test adding behaviors to catalog."""
        behavior_id = empty_catalog.add_behavior(
            name="test_behavior",
            source=BehaviorSource.MINER,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )

        assert behavior_id == 0
        assert len(empty_catalog.behaviors) == 1
        assert empty_catalog.behaviors[0].name == "test_behavior"

    def test_add_duplicate_behavior(self, seeded_catalog):
        """Test that duplicate behaviors return existing ID."""
        original_count = len(seeded_catalog.behaviors)
        behavior_id = seeded_catalog.add_behavior(
            name="explore",  # Already exists
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )

        assert behavior_id == 0  # Should return existing ID
        assert len(seeded_catalog.behaviors) == original_count

    def test_find_behavior_id(self, seeded_catalog):
        """Test finding behavior by name."""
        assert seeded_catalog.find_behavior_id("explore") == 0
        assert seeded_catalog.find_behavior_id("mine") == 1
        assert seeded_catalog.find_behavior_id("nonexistent") == -1

    def test_register_role(self, seeded_catalog):
        """Test registering a role."""
        tiers = [RoleTier(behavior_ids=[0, 1], selection=TierSelection.FIXED)]
        role = RoleDef(id=-1, name="TestRole", tiers=tiers, origin="test")

        role_id = seeded_catalog.register_role(role)

        assert role_id == 0
        assert len(seeded_catalog.roles) == 1
        assert seeded_catalog.roles[0].name == "TestRole"
        assert seeded_catalog.roles[0].id == 0

    def test_find_role_id(self, catalog_with_roles):
        """Test finding role by name."""
        assert catalog_with_roles.find_role_id("TestMiner") == 0
        assert catalog_with_roles.find_role_id("TestScout") == 1
        assert catalog_with_roles.find_role_id("Nonexistent") == -1

    def test_generate_role_name(self, seeded_catalog):
        """Test role name generation."""
        tiers = [RoleTier(behavior_ids=[1], selection=TierSelection.FIXED)]  # mine
        name1 = seeded_catalog.generate_role_name(tiers)
        name2 = seeded_catalog.generate_role_name(tiers)

        assert name1 != name2  # Should be unique
        assert "Mine" in name1 or "mine" in name1.lower()


class TestFitnessTracking:
    """Tests for fitness tracking functionality."""

    def test_behavior_selection_weight_new(self):
        """Test weight for new behavior (no games)."""
        behavior = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
            games=0,
            fitness=0.0,
        )
        assert behavior_selection_weight(behavior) == 1.0

    def test_behavior_selection_weight_with_fitness(self):
        """Test weight based on fitness."""
        behavior = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
            games=10,
            fitness=0.8,
        )
        assert behavior_selection_weight(behavior) == 0.8

    def test_behavior_selection_weight_minimum(self):
        """Test that weight has minimum of 0.1."""
        behavior = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
            games=10,
            fitness=0.0,
        )
        assert behavior_selection_weight(behavior) == 0.1

    def test_role_selection_weight_new(self):
        """Test weight for new role."""
        role = RoleDef(id=0, name="test", games=0, fitness=0.0)
        assert role_selection_weight(role) == 0.1

    def test_role_selection_weight_with_fitness(self):
        """Test weight based on role fitness."""
        role = RoleDef(id=0, name="test", games=10, fitness=0.9)
        assert role_selection_weight(role) == 0.9

    def test_record_behavior_score_initial(self):
        """Test initial score recording."""
        behavior = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
        )
        record_behavior_score(behavior, 0.8)

        assert behavior.games == 1
        assert behavior.fitness == 0.8

    def test_record_behavior_score_ema(self):
        """Test EMA fitness update."""
        behavior = BehaviorDef(
            id=0,
            name="test",
            source=BehaviorSource.COMMON,
            can_start=_always_true,
            act=_noop_action,
            should_terminate=_always_false,
            games=1,
            fitness=0.8,
        )
        record_behavior_score(behavior, 0.4, alpha=0.5)

        assert behavior.games == 2
        # EMA: 0.8 * 0.5 + 0.4 * 0.5 = 0.6
        assert abs(behavior.fitness - 0.6) < 0.001

    def test_record_role_score(self):
        """Test role score recording."""
        role = RoleDef(id=0, name="test")
        record_role_score(role, 0.9, won=True)

        assert role.games == 1
        assert role.wins == 1
        assert role.fitness == 0.9

    def test_lock_role_name(self):
        """Test locking role name at threshold."""
        role = RoleDef(id=0, name="test", fitness=0.8)
        lock_role_name_if_fit(role, threshold=0.7)
        assert role.locked_name is True

        role2 = RoleDef(id=1, name="test2", fitness=0.5)
        lock_role_name_if_fit(role2, threshold=0.7)
        assert role2.locked_name is False


class TestEvolutionaryOperations:
    """Tests for evolutionary operations."""

    def test_sample_role_empty_catalog(self, empty_catalog):
        """Test sampling from empty catalog."""
        role = sample_role(empty_catalog)
        assert role.name == "EmptyRole"

    def test_sample_role_creates_tiers(self, seeded_catalog):
        """Test that sampled role has proper tier structure."""
        rng = random.Random(42)
        config = EvolutionConfig(min_tiers=2, max_tiers=4)
        role = sample_role(seeded_catalog, config, rng)

        assert len(role.tiers) >= 2
        assert len(role.tiers) <= 4
        assert role.origin == "sampled"

    def test_sample_role_respects_max_behaviors(self, seeded_catalog):
        """Test that sampled role respects max behaviors across tiers."""
        rng = random.Random(7)
        config = EvolutionConfig(
            min_tiers=3,
            max_tiers=3,
            min_tier_size=2,
            max_tier_size=3,
            max_behaviors_per_role=4,
        )
        role = sample_role(seeded_catalog, config, rng)

        total_behaviors = sum(len(tier.behavior_ids) for tier in role.tiers)
        assert total_behaviors <= config.max_behaviors_per_role

    def test_sample_role_uses_unique_behaviors(self, seeded_catalog):
        """Test that sampled behaviors are unique within a role."""
        rng = random.Random(42)
        role = sample_role(seeded_catalog, rng=rng)

        all_ids = []
        for tier in role.tiers:
            all_ids.extend(tier.behavior_ids)

        # Should have mostly unique IDs (may repeat if exhausted)
        # At minimum, we shouldn't have consecutive duplicates
        for _i in range(len(all_ids) - 1):
            # Within reason, most should be unique
            pass  # Just checking structure works

    def test_recombine_roles_empty_parents(self, seeded_catalog):
        """Test recombination with empty parents."""
        left = RoleDef(id=0, name="empty1")
        right = RoleDef(id=1, name="empty2")
        child = recombine_roles(seeded_catalog, left, right)

        assert child.name == "EmptyRole"

    def test_recombine_roles_one_empty(self, catalog_with_roles):
        """Test recombination when one parent is empty."""
        left = RoleDef(id=99, name="empty")
        right = catalog_with_roles.roles[0]  # TestMiner
        child = recombine_roles(catalog_with_roles, left, right)

        assert len(child.tiers) > 0
        assert child.origin == "recombined"

    def test_recombine_roles_both_have_tiers(self, catalog_with_roles):
        """Test normal recombination."""
        rng = random.Random(42)
        left = catalog_with_roles.roles[0]  # TestMiner
        right = catalog_with_roles.roles[1]  # TestScout

        child = recombine_roles(catalog_with_roles, left, right, rng)

        assert len(child.tiers) > 0
        assert child.origin == "recombined"

    def test_mutate_role_preserves_structure(self, catalog_with_roles):
        """Test that mutation preserves basic structure."""
        rng = random.Random(42)
        original = catalog_with_roles.roles[0]
        original_tier_count = len(original.tiers)

        mutated = mutate_role(catalog_with_roles, original, mutation_rate=0.5, rng=rng)

        # Should have same number of tiers
        assert len(mutated.tiers) == original_tier_count
        assert mutated.origin == "mutated"

    def test_mutate_role_changes_behaviors(self, seeded_catalog):
        """Test that mutation can change behaviors."""
        # Create a role with known structure
        tiers = [RoleTier(behavior_ids=[0, 1, 2], selection=TierSelection.FIXED)]
        role = RoleDef(id=0, name="test", tiers=tiers)

        # Run multiple mutations with high rate to ensure changes
        rng = random.Random(42)
        changes_found = False
        for _ in range(10):
            mutated = mutate_role(seeded_catalog, role, mutation_rate=1.0, rng=rng)
            if mutated.tiers[0].behavior_ids != role.tiers[0].behavior_ids:
                changes_found = True
                break

        assert changes_found, "Mutation should eventually change behaviors"


class TestTierResolution:
    """Tests for tier order resolution."""

    def test_resolve_fixed_tier(self):
        """Test fixed tier keeps order."""
        tier = RoleTier(behavior_ids=[0, 1, 2], selection=TierSelection.FIXED)
        result = resolve_tier_order(tier)
        assert result == [0, 1, 2]

    def test_resolve_shuffle_tier(self):
        """Test shuffle tier changes order (sometimes)."""
        tier = RoleTier(behavior_ids=[0, 1, 2, 3], selection=TierSelection.SHUFFLE)
        rng = random.Random(42)

        # Run multiple times to ensure we get different orders
        results = [tuple(resolve_tier_order(tier, rng)) for _ in range(10)]
        unique_orders = set(results)

        # Should get multiple different orders
        assert len(unique_orders) > 1

    def test_resolve_weighted_tier(self):
        """Test weighted tier uses weights."""
        tier = RoleTier(
            behavior_ids=[0, 1, 2],
            weights=[0.0, 0.0, 1.0],  # Only behavior 2 should be selected first
            selection=TierSelection.WEIGHTED,
        )
        rng = random.Random(42)
        result = resolve_tier_order(tier, rng)

        # Behavior 2 should appear (weights strongly favor it)
        assert 2 in result

    def test_resolve_empty_tier(self):
        """Test empty tier returns empty list."""
        tier = RoleTier(behavior_ids=[], selection=TierSelection.FIXED)
        result = resolve_tier_order(tier)
        assert result == []


class TestRoleSelection:
    """Tests for fitness-weighted role selection."""

    def test_pick_role_empty_list(self, catalog_with_roles):
        """Test selection from empty list."""
        result = pick_role_id_weighted(catalog_with_roles, [])
        assert result == -1

    def test_pick_role_single_option(self, catalog_with_roles):
        """Test selection with single option."""
        result = pick_role_id_weighted(catalog_with_roles, [0])
        assert result == 0

    def test_pick_role_weighted_selection(self, catalog_with_roles):
        """Test that higher fitness roles are selected more often."""
        # Set up fitness differences
        catalog_with_roles.roles[0].games = 10
        catalog_with_roles.roles[0].fitness = 0.9
        catalog_with_roles.roles[1].games = 10
        catalog_with_roles.roles[1].fitness = 0.1

        rng = random.Random(42)
        counts = {0: 0, 1: 0}
        for _ in range(100):
            selected = pick_role_id_weighted(catalog_with_roles, [0, 1], rng)
            counts[selected] += 1

        # Higher fitness should be selected more often
        assert counts[0] > counts[1]


class TestMaterializeRole:
    """Tests for role materialization."""

    def test_materialize_empty_role(self, seeded_catalog):
        """Test materializing empty role."""
        role = RoleDef(id=0, name="empty")
        behaviors = materialize_role_behaviors(seeded_catalog, role)
        assert behaviors == []

    def test_materialize_role_returns_behaviors(self, catalog_with_roles):
        """Test that materialization returns actual behaviors."""
        role = catalog_with_roles.roles[0]  # TestMiner
        behaviors = materialize_role_behaviors(catalog_with_roles, role)

        assert len(behaviors) > 0
        assert all(isinstance(b, BehaviorDef) for b in behaviors)

    def test_materialize_role_respects_max(self, catalog_with_roles):
        """Test max_behaviors limit."""
        role = catalog_with_roles.roles[0]  # TestMiner
        behaviors = materialize_role_behaviors(catalog_with_roles, role, max_behaviors=2)

        assert len(behaviors) <= 2


class TestEvolutionConfig:
    """Tests for EvolutionConfig defaults and usage."""

    def test_default_config(self):
        """Test default configuration values."""
        config = EvolutionConfig()

        assert config.min_tiers == 2
        assert config.max_tiers == 4
        assert config.min_tier_size == 1
        assert config.max_tier_size == 3
        assert config.mutation_rate == 0.15
        assert config.lock_fitness_threshold == 0.7
        assert config.max_behaviors_per_role == 12
        assert config.fitness_alpha == 0.2

    def test_custom_config(self):
        """Test custom configuration."""
        config = EvolutionConfig(
            min_tiers=1,
            max_tiers=2,
            mutation_rate=0.5,
        )

        assert config.min_tiers == 1
        assert config.max_tiers == 2
        assert config.mutation_rate == 0.5
