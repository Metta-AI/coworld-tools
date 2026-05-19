"""Fixtures for rule-level integration tests.

Each test in this directory drives a small ascii-map simulation and asserts
the post-conditions described in `RULES.md`. Fixtures here assemble a
``CogonyMission`` config, swap in a small ascii map, trim agents to match,
and expose a fresh ``Simulation``.
"""

from __future__ import annotations

from typing import Iterable

import pytest

import cogony  # noqa: F401  (import side-effects: mettascope asset overlay)
from cogony.mission import CogonyMission
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.simulator.simulator import Simulator


CHAR_TO_MAP_NAME = {
    "#": "wall",
    "@": "agent.agent",
    "j": "junction",
    "c": "carbon_extractor",
    "o": "oxygen_extractor",
    "g": "germanium_extractor",
    "s": "silicon_extractor",
    "h": "red:hub",
    "D": "red:core_a_st",
    "M": "red:market_st",
    "H": "heart_altar",
    "+": "red:stake_buy_st",
    "-": "red:stake_sell_st",
    "T": "trap",
    ".": "empty",
}


def _build_config(
    map_data: list[list[str]],
    agent_tags: list[list[str]] | None,
    agent_inventory: list[dict[str, int]] | None,
    agent_team_ids: list[int] | None,
    max_steps: int,
    god_mode: bool,
) -> MettaGridConfig:
    n_agents = sum(row.count("@") for row in map_data)
    assert n_agents >= 1, "rule maps must place at least one '@' agent"

    mission = CogonyMission(god_mode=god_mode)
    mission.max_steps = max_steps
    cfg = mission.make_env()
    cfg = cfg.with_ascii_map(map_data, char_to_map_name=CHAR_TO_MAP_NAME)
    cfg.game.num_agents = n_agents
    cfg.game.agents = cfg.game.agents[:n_agents]

    if agent_team_ids is not None:
        assert len(agent_team_ids) == n_agents
        for agent, tid in zip(cfg.game.agents, agent_team_ids):
            agent.team_id = tid
    if agent_tags is not None:
        assert len(agent_tags) == n_agents
        for agent, tags in zip(cfg.game.agents, agent_tags):
            agent.tags = list(tags)
    if agent_inventory is not None:
        assert len(agent_inventory) == n_agents
        for agent, extra in zip(cfg.game.agents, agent_inventory):
            agent.inventory.initial = {**agent.inventory.initial, **extra}

    return cfg


@pytest.fixture
def build_rule_config():
    """Factory: builds a MettaGridConfig from a small ascii map."""
    def _factory(
        map_data: list[list[str]],
        *,
        agent_tags: list[list[str]] | None = None,
        agent_inventory: list[dict[str, int]] | None = None,
        agent_team_ids: list[int] | None = None,
        max_steps: int = 200,
        god_mode: bool = False,
    ) -> MettaGridConfig:
        return _build_config(map_data, agent_tags, agent_inventory, agent_team_ids, max_steps, god_mode)
    return _factory


@pytest.fixture
def new_simulation():
    """Factory: build a fresh Simulation from a config."""
    def _factory(cfg: MettaGridConfig, *, seed: int = 0):
        return Simulator().new_simulation(cfg, seed=seed)
    return _factory


@pytest.fixture
def step_with_actions():
    """Apply one action per agent (positional) and step once."""
    def _step(sim, actions: Iterable[str]) -> None:
        for i, name in enumerate(actions):
            sim.agent(i).set_action(name)
        sim.step()
    return _step


@pytest.fixture
def junction_at():
    """Look up the junction grid object at (row, col)."""
    def _lookup(sim, row: int, col: int) -> dict:
        for o in sim.grid_objects().values():
            if o.get("type_name") == "junction" and o.get("r") == row and o.get("c") == col:
                return o
        raise AssertionError(f"no junction at ({row}, {col})")
    return _lookup


@pytest.fixture
def extractor_at():
    """Look up an extractor grid object at (row, col)."""
    def _lookup(sim, row: int, col: int):
        for o in sim.grid_objects().values():
            tn = o.get("type_name", "")
            if "extractor" in tn and o.get("r") == row and o.get("c") == col:
                return o
        raise AssertionError(f"no extractor at ({row}, {col})")
    return _lookup


@pytest.fixture
def object_at():
    """Look up any grid object at (row, col) by type_name substring."""
    def _lookup(sim, row: int, col: int, type_contains: str = ""):
        for o in sim.grid_objects().values():
            tn = o.get("type_name", "")
            if type_contains in tn and o.get("r") == row and o.get("c") == col:
                return o
        raise AssertionError(f"no object matching '{type_contains}' at ({row}, {col})")
    return _lookup


@pytest.fixture
def tag_id():
    """Resolve a tag name to its runtime int id (uses the canonical id_map)."""
    def _resolve(cfg: MettaGridConfig, name: str) -> int:
        id_map = cfg.game.id_map()
        names = list(id_map.tag_names())
        return names.index(name)
    return _resolve
