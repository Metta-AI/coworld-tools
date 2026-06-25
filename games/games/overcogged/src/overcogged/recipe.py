"""Metta recipe entrypoints for the standalone Overcogged package."""

from __future__ import annotations

from collections.abc import Sequence

from mettagrid.renderer.renderer import RenderMode

from overcogged.rendering import auto_render_mode

DEFAULT_PLAY_NUM_AGENTS = 4
DEFAULT_POLICY_URI = "metta://policy/overcogged.agent.overcogged_agent.policy.OvercookedPolicy"


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
    render: RenderMode | None = None,
):
    from cogames.cli.mission import resolve_mission
    from mettagrid.cogame.game import get_game
    from metta.sim.simulation_config import SimulationConfig
    from metta.tools.play import PlayTool

    resolved_num_agents = _resolve_num_agents(
        num_agents=num_agents,
        cogs=cogs,
        default=DEFAULT_PLAY_NUM_AGENTS,
    )
    variant_list = _parse_variants(variants)
    game = get_game("overcogged")
    _mission_name, env_cfg, _mission = resolve_mission(
        game,
        "basic",
        variants_arg=variant_list or None,
        cogs=resolved_num_agents,
    )
    if max_steps is not None:
        env_cfg.game.max_steps = max_steps

    return PlayTool(
        sim=SimulationConfig(suite="overcogged", name="basic", env=env_cfg),
        policy_uri=policy_uri or DEFAULT_POLICY_URI,
        max_steps=env_cfg.game.max_steps,
        autostart=autostart,
        render=render or auto_render_mode(),
    )
