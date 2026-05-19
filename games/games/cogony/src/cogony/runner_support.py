"""Shared runtime helpers for Cogony CLI and episode runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mettagrid.sdk.agent.runtime.observation import ObservationEnvelope, decode_observation


def _make_policy(name: str, pei, *, enable_llm: bool = True):
    if name == "baseline":
        from cogony_policy import CogonyPolicy

        return CogonyPolicy(pei)
    if name in {"toolsy", "toolsy-autopilot"}:
        from toolsy_policy import ToolsyPolicy

        if name == "toolsy-autopilot":
            enable_llm = False
        return ToolsyPolicy(pei, enable_llm=enable_llm)
    if name == "random":
        from mettagrid.policy.random_agent import RandomMultiAgentPolicy

        return RandomMultiAgentPolicy(pei)
    return None


def _start_toolsy_coworld_processes(renderer, num_agents: int):
    from toolsy_policy.coworld import ToolsyCoworldProcessManager

    return ToolsyCoworldProcessManager([renderer.policy_ws_url(agent_id) for agent_id in range(num_agents)])


def _obs_grid_from_decoded(decoded) -> dict:
    obs_grid = {}
    for (row, col), cell in decoded.cells_by_location.items():
        dr, dc = row - decoded.center_row, col - decoded.center_col
        tags = list(cell.tags)
        feats = dict(cell.features)
        obs_grid[f"{dr},{dc}"] = {"tags": tags, "feats": feats}
    return obs_grid


def _obs_global_from_decoded(decoded) -> dict:
    return dict(decoded.global_features)


def _local_position_from_global_tokens(global_features: dict) -> tuple[int, int] | None:
    keys = ("lp:north", "lp:south", "lp:west", "lp:east")
    if not any(key in global_features for key in keys):
        return None
    row = int(global_features.get("lp:south", 0)) - int(global_features.get("lp:north", 0))
    col = int(global_features.get("lp:east", 0)) - int(global_features.get("lp:west", 0))
    return row, col


def _obs_center_from_decoded(decoded, state: dict | None = None) -> list[int]:
    state = state if state is not None else {}
    raw_center = [int(decoded.center_row), int(decoded.center_col)]
    local_position = _local_position_from_global_tokens(dict(decoded.global_features))
    if local_position is not None:
        state["uses_local_position"] = True
    elif state.get("uses_local_position"):
        local_position = (0, 0)
    if local_position is None:
        center = raw_center
    else:
        spawn = state.setdefault("spawn", raw_center)
        center = [int(spawn[0]) + local_position[0], int(spawn[1]) + local_position[1]]
    state["center"] = center
    return center


def _decode_observation_tokens(obs, pei, step: int) -> tuple[dict, dict, list[int]]:
    decoded = decode_observation(ObservationEnvelope(raw_observation=obs, policy_env_info=pei, step=step))
    return _obs_grid_from_decoded(decoded), _obs_global_from_decoded(decoded), _obs_center_from_decoded(decoded)


def _decode_observation_grid(obs, pei, step: int) -> dict:
    return _decode_observation_tokens(obs, pei, step)[0]


def _refresh_policy_obs_grids(
    policy_infos: dict,
    observations: list,
    pei,
    step: int,
    policy_name: str,
    decode_observation_tokens: Callable[[Any, Any, int], tuple[dict, dict, list[int] | None]] = (
        _decode_observation_tokens
    ),
) -> None:
    for agent_id, obs in enumerate(observations):
        infos = policy_infos.setdefault(agent_id, {"__policy_name__": policy_name})
        infos.setdefault("__policy_name__", policy_name)
        obs_grid, obs_global, obs_center = decode_observation_tokens(obs, pei, step)
        infos["obs_grid"] = obs_grid
        infos["obs_global"] = obs_global
        if obs_center is not None:
            infos["obs_center"] = obs_center


def _current_policy_infos(
    sim,
    pei,
    policy_name: str,
    decode_observation_tokens: Callable[[Any, Any, int], tuple[dict, dict, list[int] | None]] = (
        _decode_observation_tokens
    ),
) -> dict:
    policy_infos = {agent_id: {"__policy_name__": policy_name} for agent_id in range(sim.num_agents)}
    if sim.num_agents > 0 and hasattr(sim, "observations"):
        _refresh_policy_obs_grids(policy_infos, sim.observations(), pei, sim.current_step, policy_name, decode_observation_tokens)
    return policy_infos
