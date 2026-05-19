"""Metta recipe entrypoints for the standalone Diplomacog package."""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_NUM_AGENTS = 24
DEFAULT_MAX_STEPS = 400
DEFAULT_POLICY_URI = "metta://policy/diplomacog.agent.diplomacy_agent.policy.DiplomacyPolicy"


def _parse_variants(variants: Sequence[str] | str | None) -> list[str]:
    if isinstance(variants, str):
        return [value.strip() for value in variants.split(",") if value.strip()]
    return list(variants) if variants else []


def _resolve_num_agents(*, num_agents: int | None, cogs: int | None, default: int) -> int:
    if cogs is not None:
        return cogs
    if num_agents is not None:
        return num_agents
    return default


def _make_play_env(
    *,
    num_agents: int | None,
    cogs: int | None,
    max_steps: int | None,
    variants: Sequence[str] | str | None,
):
    from diplomacog import make_diplomacog_env

    effective_num_agents = _resolve_num_agents(num_agents=num_agents, cogs=cogs, default=DEFAULT_NUM_AGENTS)
    effective_max_steps = max_steps if max_steps is not None else DEFAULT_MAX_STEPS
    variant_list = _parse_variants(variants)
    env_cfg = make_diplomacog_env(
        num_agents=effective_num_agents,
        max_steps=effective_max_steps,
        variants=variant_list,
    )
    for name in variant_list:
        env_cfg.label += f".{name}"
    return env_cfg, effective_max_steps


def play(
    policy_uri: str | None = None,
    num_agents: int | None = None,
    cogs: int | None = None,
    max_steps: int | None = None,
    variants: Sequence[str] | str | None = None,
    autostart: bool = True,
):
    from metta.sim.simulation_config import SimulationConfig
    from metta.tools.play import PlayTool

    env_cfg, effective_max_steps = _make_play_env(
        num_agents=num_agents,
        cogs=cogs,
        max_steps=max_steps,
        variants=variants,
    )

    return PlayTool(
        sim=SimulationConfig(suite="diplomacog", name="diplomacog.basic", env=env_cfg),
        policy_uri=policy_uri or DEFAULT_POLICY_URI,
        max_steps=effective_max_steps,
        autostart=autostart,
    )
