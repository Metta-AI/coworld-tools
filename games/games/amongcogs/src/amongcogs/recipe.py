"""Metta recipe entrypoints for the standalone AmongCogs package."""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_PLAY_NUM_AGENTS = 12
DEFAULT_POLICY_URI = "metta://policy/amongcogs_agent"
POLICY_PACKAGES = (
    "amongcogs.agent.amongcogs_agent",
    "amongcogs.agent.amongcogs_cyborg",
)


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
) -> object:
    from cogames.cli.mission import resolve_mission
    from cogames.game import get_game
    from metta.sim.simulation_config import SimulationConfig
    from metta.tools.play import PlayTool
    from mettagrid.policy.loader import discover_and_register_policies

    for package_name in POLICY_PACKAGES:
        discover_and_register_policies(package_name)

    game = get_game("amongcogs")
    variant_list = _parse_variants(variants)
    _mission_name, env_cfg, _mission = resolve_mission(
        game,
        "basic",
        variants_arg=variant_list or None,
        cogs=_resolve_num_agents(num_agents=num_agents, cogs=cogs, default=DEFAULT_PLAY_NUM_AGENTS),
    )
    if max_steps is not None:
        env_cfg.game.max_steps = max_steps

    return PlayTool(
        sim=SimulationConfig(suite="amongcogs", name="basic", env=env_cfg),
        policy_uri=policy_uri or DEFAULT_POLICY_URI,
        max_steps=env_cfg.game.max_steps,
        render="none",
        autostart=autostart,
    )
