"""
Behavior smoke tests for the nlanky scripted policy.

These are intentionally minimal: they validate that the nlanky Nim policy can run
in deterministic eval arenas and achieve at least basic capability.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent_policies.tools.eval.cogsguard.evals.planky_evals import (
    PLANKY_BEHAVIOR_EVALS,
    PlankyAlignerGear,
    PlankyAlignerHearts,
    PlankyAlignerReGear,
    PlankyAlignerReHearts,
    PlankyCommanderAlign,
    PlankyCommanderScramble,
    PlankyExplorationDistant,
    PlankyMaze,
    PlankyMinerBestResource,
    PlankyMinerExtract,
    PlankyMinerFullCycle,
    PlankyMinerGear,
    PlankyMinerReGear,
    PlankyResourceChain,
    PlankyScoutExplore,
    PlankyScoutGear,
    PlankyScramblerGear,
    PlankyScramblerRecovery,
    PlankyScramblerTarget,
    PlankyStuckCorridor,
)

from mettagrid.policy.loader import discover_and_register_policies
from mettagrid.policy.policy import PolicySpec
from mettagrid.runner.rollout import run_episode_local

discover_and_register_policies("agent_policies.policies.scripted.cogsguard")


def run_nlanky_episode(
    mission_class: type,
    *,
    max_steps: int | None = None,
    roles: dict[str, int] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    mission = mission_class()
    env_cfg = mission.make_env()
    if max_steps is not None:
        env_cfg.game.max_steps = max_steps

    init_kwargs = {"miner": 0, "scout": 0, "aligner": 0, "scrambler": 0}
    if roles:
        init_kwargs.update(roles)
    else:
        init_kwargs["miner"] = 1

    policy_spec = PolicySpec(class_path="nlanky", data_path=None, init_kwargs=init_kwargs)
    results, _replay = run_episode_local(
        policy_specs=[policy_spec],
        assignments=[0] * env_cfg.game.num_agents,
        env=env_cfg,
        seed=seed,
        device="cpu",
        render_mode="none",
    )
    return {"steps": results.steps, "stats": results.stats, "rewards": results.rewards}


@pytest.mark.parametrize(
    ("mission_cls", "role"),
    [
        (PlankyMinerGear, "miner"),
        (PlankyScoutGear, "scout"),
        (PlankyAlignerGear, "aligner"),
        (PlankyScramblerGear, "scrambler"),
    ],
)
def test_nlanky_role_gets_gear(mission_cls: type, role: str) -> None:
    stats = run_nlanky_episode(mission_cls, max_steps=100, roles={role: 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get(f"{role}.gained", 0) > 0, f"Expected {role} gear gain, got stats={agent_stats[0]}"


def test_nlanky_miner_extracts_carbon() -> None:
    stats = run_nlanky_episode(PlankyMinerExtract, max_steps=200, roles={"miner": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    carbon_gained = agent_stats[0].get("carbon.gained", 0)
    assert carbon_gained > 0, f"Expected some carbon mined, got stats={agent_stats[0]}"


def test_nlanky_miner_picks_best_resource() -> None:
    stats = run_nlanky_episode(PlankyMinerBestResource, max_steps=300, roles={"miner": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    carbon_gained = agent_stats[0].get("carbon.gained", 0)
    assert carbon_gained > 0, f"Expected miner to mine carbon in best-resource arena, got stats={agent_stats[0]}"


def test_nlanky_miner_full_cycle() -> None:
    stats = run_nlanky_episode(PlankyMinerFullCycle, max_steps=400, roles={"miner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("carbon.gained", 0) > 0, f"Expected some carbon mined, got stats={agent_stats[0]}"


def test_nlanky_aligner_gets_hearts() -> None:
    stats = run_nlanky_episode(PlankyAlignerHearts, max_steps=200, roles={"aligner": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("heart.gained", 0) > 0, f"Expected some hearts gained, got stats={agent_stats[0]}"


def test_nlanky_scrambler_scrambles_junction() -> None:
    stats = run_nlanky_episode(PlankyScramblerTarget, max_steps=300, roles={"scrambler": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("junction.scrambled_by_agent", 0) > 0, (
        f"Expected scrambler to scramble a junction, got stats={agent_stats[0]}"
    )


def test_nlanky_scout_explores() -> None:
    stats = run_nlanky_episode(PlankyScoutExplore, max_steps=200, roles={"scout": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("action.move.success", 0) > 50, (
        f"Expected scout to move around, got stats={agent_stats[0]}"
    )


def test_nlanky_maze_navigation_mines_carbon() -> None:
    stats = run_nlanky_episode(PlankyMaze, max_steps=400, roles={"miner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("carbon.gained", 0) > 0, f"Expected some carbon mined, got stats={agent_stats[0]}"


def test_nlanky_distant_exploration_mines_carbon() -> None:
    stats = run_nlanky_episode(PlankyExplorationDistant, max_steps=400, roles={"miner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("carbon.gained", 0) > 0, f"Expected some carbon mined, got stats={agent_stats[0]}"


def test_nlanky_stuck_corridor_mines_carbon() -> None:
    stats = run_nlanky_episode(PlankyStuckCorridor, max_steps=400, roles={"miner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("carbon.gained", 0) > 0, f"Expected some carbon mined, got stats={agent_stats[0]}"


def test_nlanky_resource_chain_mines_resources() -> None:
    stats = run_nlanky_episode(PlankyResourceChain, max_steps=500, roles={"miner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    resources_gained = sum(agent_stats[0].get(f"{r}.gained", 0) for r in ("carbon", "oxygen", "germanium", "silicon"))
    assert resources_gained > 0, f"Expected some resources mined, got stats={agent_stats[0]}"


def test_nlanky_miner_re_gears() -> None:
    stats = run_nlanky_episode(PlankyMinerReGear, max_steps=300, roles={"miner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("miner.gained", 0) > 0, f"Expected miner to re-gear, got stats={agent_stats[0]}"
    assert agent_stats[0].get("carbon.gained", 0) > 0, (
        f"Expected miner to mine after re-gearing, got stats={agent_stats[0]}"
    )


def test_nlanky_aligner_re_gears() -> None:
    stats = run_nlanky_episode(PlankyAlignerReGear, max_steps=400, roles={"aligner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("aligner.gained", 0) > 0, f"Expected aligner to re-gear, got stats={agent_stats[0]}"


def test_nlanky_aligner_re_hearts() -> None:
    stats = run_nlanky_episode(PlankyAlignerReHearts, max_steps=400, roles={"aligner": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("heart.gained", 0) > 0, (
        f"Expected aligner to re-acquire hearts, got stats={agent_stats[0]}"
    )


def test_nlanky_scrambler_recovers() -> None:
    stats = run_nlanky_episode(PlankyScramblerRecovery, max_steps=400, roles={"scrambler": 1})
    assert stats["steps"] > 0
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("scrambler.gained", 0) > 0, (
        f"Expected scrambler to recover gear, got stats={agent_stats[0]}"
    )


@pytest.mark.parametrize("mission_cls", [PlankyMaze, PlankyStuckCorridor])
def test_nlanky_does_not_get_stuck_in_nav_arenas(mission_cls: type) -> None:
    stats = run_nlanky_episode(mission_cls, max_steps=200, roles={"miner": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    # Regression guard for nav cache/stuck handling. If the agent is thrashing, this spikes.
    assert agent_stats[0].get("status.max_steps_without_motion", 999) < 25, (
        f"Expected agent to avoid long stuck periods, got stats={agent_stats[0]}"
    )


def test_nlanky_commander_align_directive() -> None:
    """Miner sees a heart-vibed junction and aligns it (commander directive)."""
    stats = run_nlanky_episode(PlankyCommanderAlign, max_steps=400, roles={"miner": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("junction.aligned_by_agent", 0) > 0, (
        f"Expected miner to align commander-tagged junction, got stats={agent_stats[0]}"
    )


def test_nlanky_commander_scramble_directive() -> None:
    """Miner sees a scrambler-vibed enemy junction and scrambles it."""
    stats = run_nlanky_episode(PlankyCommanderScramble, max_steps=400, roles={"miner": 1})
    agent_stats = stats["stats"].get("agent", [])
    assert agent_stats, "Expected agent stats to be present"
    assert agent_stats[0].get("junction.scrambled_by_agent", 0) > 0, (
        f"Expected miner to scramble commander-tagged junction, got stats={agent_stats[0]}"
    )


# ==============================================================================
# Smoke Tests — All Missions
# ==============================================================================


@pytest.mark.parametrize(
    "mission_class",
    PLANKY_BEHAVIOR_EVALS,
    ids=[m.model_fields["name"].default for m in PLANKY_BEHAVIOR_EVALS],
)
def test_nlanky_behavior_mission_runs(mission_class: type) -> None:
    """Smoke test: All eval missions should run under nlanky without error."""
    name = mission_class.model_fields["name"].default
    if "aligner" in name:
        roles = {"aligner": 1}
    elif "scrambler" in name:
        roles = {"scrambler": 1}
    elif "scout" in name:
        roles = {"scout": 1}
    elif "multi_role" in name:
        roles = {"miner": 1, "scout": 1, "aligner": 1, "scrambler": 1}
    else:
        roles = {"miner": 1}

    stats = run_nlanky_episode(mission_class, max_steps=50, roles=roles)
    assert stats["steps"] > 0, f"Mission {mission_class} should run for at least one step"
