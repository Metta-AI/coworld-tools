"""Metta recipe entrypoints for the standalone Werecog package."""

from __future__ import annotations

from collections.abc import Sequence

from werecog.cogame import make_game
from werecog.defaults import DEFAULT_MAX_STEPS

DEFAULT_PLAY_NUM_AGENTS = 16
DEFAULT_POLICY_URI = "metta://policy/werecog"


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
    from mettagrid.policy.loader import discover_and_register_policies

    discover_and_register_policies("werecog")

    resolved_num_agents = _resolve_num_agents(
        num_agents=num_agents,
        cogs=cogs,
        default=DEFAULT_PLAY_NUM_AGENTS,
    )
    variant_list = _parse_variants(variants)
    env = make_game(
        "werecog",
        num_agents=resolved_num_agents,
        max_steps=max_steps if max_steps is not None else DEFAULT_MAX_STEPS,
        variants=variant_list if variant_list else None,
    )

    return PlayTool(
        sim=SimulationConfig(suite="werecog", name="basic", env=env),
        policy_uri=policy_uri or DEFAULT_POLICY_URI,
        max_steps=env.game.max_steps,
        render="none",
        autostart=autostart,
    )
