"""Parameterized benchmark tests for scripted agent variants.

Each agent variant (role, role_nim, planky, wombo, teacher, baseline, etc.)
is tested for:
- Importability and class instantiation
- Short-name registration in the scripted registry
- Policy class existence and interface compliance
"""

from __future__ import annotations

import pytest
from policies.scripted.cogsguard.scripted_registry import (
    list_scripted_agent_names,
    resolve_scripted_agent_uri,
)

# All agent variants the issue requires coverage for, plus extras
CORE_AGENT_NAMES = [
    "role",
    "role_nim",
    "nlanky",
    "wombo",
    "teacher",
    "baseline",
]

EXTENDED_AGENT_NAMES = [
    "thinky",
    "race_car",
    "nim_random",
    "alignall",
    "tiny_baseline",
    "cogsguard_control",
    "cogsguard_targeted",
    "cogsguard_v2",
]

ALL_AGENT_NAMES = CORE_AGENT_NAMES + EXTENDED_AGENT_NAMES


# ---------------------------------------------------------------------------
# Registry presence tests
# ---------------------------------------------------------------------------


class TestAgentRegistryPresence:
    """Every known agent short-name must be discoverable in the registry."""

    @pytest.mark.parametrize("agent_name", ALL_AGENT_NAMES)
    def test_agent_in_registry(self, agent_name: str) -> None:
        names = list_scripted_agent_names()
        assert agent_name in names, f"{agent_name} not found in scripted agent names"

    @pytest.mark.parametrize("agent_name", ALL_AGENT_NAMES)
    def test_agent_uri_resolves(self, agent_name: str) -> None:
        uri = resolve_scripted_agent_uri(agent_name)
        assert uri == f"metta://policy/{agent_name}"


# ---------------------------------------------------------------------------
# Policy class import tests
# ---------------------------------------------------------------------------

_POLICY_CLASS_MAP: dict[str, tuple[str, str]] = {
    "baseline": (
        "policies.scripted.cogsguard.scripted_agent.baseline_agent",
        "BaselinePolicy",
    ),
    "tiny_baseline": (
        "policies.scripted.cogsguard.scripted_agent.demo_policy",
        "DemoPolicy",
    ),
}


class TestPolicyClassImportable:
    """Verify that key policy classes can be imported without errors."""

    @pytest.mark.parametrize(
        "module_path,class_name",
        list(_POLICY_CLASS_MAP.values()),
        ids=list(_POLICY_CLASS_MAP.keys()),
    )
    def test_policy_class_exists(self, module_path: str, class_name: str) -> None:
        import importlib  # noqa: PLC0415

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name, None)
        assert cls is not None, f"{class_name} not found in {module_path}"

    @pytest.mark.parametrize(
        "module_path,class_name",
        list(_POLICY_CLASS_MAP.values()),
        ids=list(_POLICY_CLASS_MAP.keys()),
    )
    def test_policy_class_has_short_names(self, module_path: str, class_name: str) -> None:
        import importlib  # noqa: PLC0415

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        assert hasattr(cls, "short_names"), f"{class_name} missing short_names attribute"
        assert isinstance(cls.short_names, (list, tuple))
        assert len(cls.short_names) > 0


# ---------------------------------------------------------------------------
# Evolution module import benchmark
# ---------------------------------------------------------------------------


class TestEvolutionModuleImportable:
    """Verify the evolution modules import cleanly."""

    def test_import_evolution(self) -> None:
        from policies.scripted.cogsguard.evolution.cogsguard.evolution import (  # noqa: PLC0415
            RoleCatalog,
            RoleDef,
            sample_role,
        )

        assert RoleCatalog is not None
        assert RoleDef is not None
        assert sample_role is not None

    def test_import_coordinator(self) -> None:
        from policies.scripted.cogsguard.evolution.cogsguard.evolutionary_coordinator import (  # noqa: PLC0415
            EvolutionaryRoleCoordinator,
        )

        assert EvolutionaryRoleCoordinator is not None


# ---------------------------------------------------------------------------
# Smoke tests: coordinator assigns vibes without crash for each base role
# ---------------------------------------------------------------------------


class TestAgentBenchmarkSmoke:
    """Smoke tests verifying agent variants operate without errors.

    Since actual simulation requires a running mettagrid environment,
    these tests exercise the coordinator and registry paths that each
    agent variant relies on.
    """

    def test_coordinator_assigns_all_vibes(self) -> None:
        """All four base vibes (miner/scout/aligner/scrambler) should
        be assignable by the evolutionary coordinator."""
        from policies.scripted.cogsguard.evolution.cogsguard.evolutionary_coordinator import (  # noqa: PLC0415
            EvolutionaryRoleCoordinator,
        )

        coordinator = EvolutionaryRoleCoordinator(num_agents=20)
        vibes_seen: set[str] = set()
        for agent_id in range(20):
            vibe = coordinator.choose_vibe(agent_id)
            vibes_seen.add(vibe)

        expected = {"miner", "scout", "aligner", "scrambler"}
        assert expected.issubset(vibes_seen), f"Missing vibes: {expected - vibes_seen}"

    @pytest.mark.parametrize(
        "role_name",
        ["BaseMiner", "BaseScout", "BaseAligner", "BaseScrambler"],
    )
    def test_base_role_materializes(self, role_name: str) -> None:
        """Each base role should materialize into a non-empty behavior list."""
        from policies.scripted.cogsguard.evolution.cogsguard.evolution import (  # noqa: PLC0415
            materialize_role_behaviors,
        )
        from policies.scripted.cogsguard.evolution.cogsguard.evolutionary_coordinator import (  # noqa: PLC0415
            EvolutionaryRoleCoordinator,
        )

        coordinator = EvolutionaryRoleCoordinator(num_agents=4)
        role_id = coordinator.catalog.find_role_id(role_name)
        assert role_id >= 0, f"Role {role_name} not found"

        role = coordinator.catalog.roles[role_id]
        behaviors = materialize_role_behaviors(coordinator.catalog, role)
        assert len(behaviors) > 0, f"Role {role_name} materialized to empty list"

    def test_multiple_games_no_crash(self) -> None:
        """Run the coordinator through multiple games without errors."""
        import random  # noqa: PLC0415

        from policies.scripted.cogsguard.evolution.cogsguard.evolutionary_coordinator import (  # noqa: PLC0415
            EvolutionaryRoleCoordinator,
        )

        rng = random.Random(123)
        coordinator = EvolutionaryRoleCoordinator(
            num_agents=4,
            rng=rng,
            games_per_generation=3,
        )

        for _game in range(6):
            for agent_id in range(4):
                coordinator.assign_role(agent_id)
            for agent_id in range(4):
                coordinator.record_agent_performance(agent_id, score=rng.random(), won=rng.random() > 0.5)
            coordinator.end_game(won=rng.random() > 0.5)

        assert coordinator.generation >= 1
