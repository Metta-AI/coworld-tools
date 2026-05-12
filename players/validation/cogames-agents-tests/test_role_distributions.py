"""Tests for scripted role distribution and URI-based role assignment."""

from __future__ import annotations

import random

import pytest
from cogames_agents.policy.evolution.cogsguard.evolution import (
    BehaviorSource,
    RoleCatalog,
    RoleDef,
    RoleTier,
    pick_role_id_weighted,
)
from cogames_agents.policy.evolution.cogsguard.evolutionary_coordinator import (
    EvolutionaryRoleCoordinator,
)
from cogames_agents.policy.scripted_registry import resolve_scripted_agent_uri

ROLE_VARIANTS = ("role", "role_nim", "wombo", "teacher")
BASE_ROLE_VIBES = (
    ("BaseMiner", "miner"),
    ("BaseScout", "scout"),
    ("BaseAligner", "aligner"),
    ("BaseScrambler", "scrambler"),
)


@pytest.fixture
def coordinator() -> EvolutionaryRoleCoordinator:
    return EvolutionaryRoleCoordinator(num_agents=20, rng=random.Random(42))


def _catalog_with_dummy_behavior() -> RoleCatalog:
    catalog = RoleCatalog()
    catalog.add_behavior(
        "b0",
        BehaviorSource.COMMON,
        lambda _: True,
        lambda _: None,
        lambda _: False,  # type: ignore[arg-type]
    )
    return catalog


@pytest.mark.parametrize("name", ROLE_VARIANTS)
def test_role_variant_uri(name: str) -> None:
    uri = resolve_scripted_agent_uri(name)
    assert uri.startswith("metta://policy/")
    assert name in uri


def test_all_base_roles_assigned(coordinator: EvolutionaryRoleCoordinator) -> None:
    roles_assigned = {coordinator.assign_role(agent_id).name for agent_id in range(20)}
    expected = {"BaseMiner", "BaseScout", "BaseAligner", "BaseScrambler"}
    assert expected.issubset(roles_assigned)


def test_role_assignment_deterministic() -> None:
    def assign_all(seed: int) -> list[str]:
        policy = EvolutionaryRoleCoordinator(num_agents=10, rng=random.Random(seed))
        return [policy.assign_role(agent_id).name for agent_id in range(10)]

    assert assign_all(99) == assign_all(99)


def test_high_fitness_role_selected_more() -> None:
    catalog = _catalog_with_dummy_behavior()
    catalog.register_role(RoleDef(id=-1, name="HighFit", games=10, fitness=0.95, tiers=[RoleTier(behavior_ids=[0])]))
    catalog.register_role(RoleDef(id=-1, name="LowFit", games=10, fitness=0.05, tiers=[RoleTier(behavior_ids=[0])]))

    rng = random.Random(42)
    counts = {0: 0, 1: 0}
    for _ in range(200):
        counts[pick_role_id_weighted(catalog, [0, 1], rng)] += 1

    assert counts[0] > counts[1], "High-fitness role should be selected more often"


def test_zero_games_roles_still_selectable() -> None:
    catalog = _catalog_with_dummy_behavior()
    catalog.register_role(RoleDef(id=-1, name="NewRole", games=0, fitness=0.0, tiers=[RoleTier(behavior_ids=[0])]))

    assert pick_role_id_weighted(catalog, [0], random.Random(42)) == 0


@pytest.mark.parametrize(("role_name", "expected_vibe"), BASE_ROLE_VIBES)
def test_base_role_maps_to_expected_vibe(
    coordinator: EvolutionaryRoleCoordinator,
    role_name: str,
    expected_vibe: str,
) -> None:
    role = coordinator.catalog.roles[coordinator.catalog.find_role_id(role_name)]
    assert coordinator.map_role_to_vibe(role) == expected_vibe


def test_empty_role_maps_to_gear(coordinator: EvolutionaryRoleCoordinator) -> None:
    assert coordinator.map_role_to_vibe(RoleDef(id=-1, name="Empty", tiers=[])) == "gear"


def test_choose_vibe_returns_valid(coordinator: EvolutionaryRoleCoordinator) -> None:
    valid_vibes = {"miner", "scout", "aligner", "scrambler", "gear"}
    for agent_id in range(4):
        assert coordinator.choose_vibe(agent_id) in valid_vibes
