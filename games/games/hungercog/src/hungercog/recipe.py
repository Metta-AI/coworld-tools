"""Metta recipe entrypoints for the standalone HungerCog package."""

from __future__ import annotations

from collections.abc import Sequence

from hungercog.game import DEFAULT_MAX_STEPS, DEFAULT_NUM_AGENTS, DEFAULT_POLICY_URI, register_with_metta
from mettagrid.renderer.renderer import RenderMode


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
    render: RenderMode = "none",
    autostart: bool = True,
):
    from cogames.cli.mission import resolve_mission
    from mettagrid.cogame.game import get_game
    from metta.sim.simulation_config import SimulationConfig
    from metta.tools.play import PlayTool

    resolved_num_agents = _resolve_num_agents(
        num_agents=num_agents,
        cogs=cogs,
        default=DEFAULT_NUM_AGENTS,
    )
    variant_list = _parse_variants(variants)
    game = get_game("hungercog")
    mission_name, env_cfg, _mission = resolve_mission(
        game,
        "hungercog",
        variants_arg=variant_list or None,
        cogs=resolved_num_agents,
    )
    if max_steps is not None:
        env_cfg.game.max_steps = max_steps

    return PlayTool(
        sim=SimulationConfig(suite="hungercog", name=mission_name, env=env_cfg),
        policy_uri=policy_uri or DEFAULT_POLICY_URI,
        max_steps=env_cfg.game.max_steps,
        render=render,
        autostart=autostart,
    )


def train(
    num_agents: int | None = None,
    cogs: int | None = None,
    max_steps: int | None = None,
    variants: Sequence[str] | str | None = None,
):
    from hungercog.tree_curriculum import HUNGER_MECHANICS, HungerTreeTaskGenerator
    from metta.games.games import make_game
    from metta.rl.curriculum.tree_curriculum import make_tree_curriculum
    from metta.rl.training import EvaluatorConfig, TrainingEnvironmentConfig
    from metta.sim.simulation_config import SimulationConfig
    from metta.tools.train import TrainTool

    register_with_metta()

    resolved_num_agents = _resolve_num_agents(
        num_agents=num_agents,
        cogs=cogs,
        default=DEFAULT_NUM_AGENTS,
    )
    variant_list = _parse_variants(variants)
    steps = max_steps if max_steps is not None else DEFAULT_MAX_STEPS
    mechanics = variant_list if variant_list else HUNGER_MECHANICS

    curriculum = make_tree_curriculum(
        game="hungercog",
        mechanics=mechanics,
        num_agents=resolved_num_agents,
        max_steps=steps,
        interface_variants=HUNGER_MECHANICS,
        task_generator_config_cls=HungerTreeTaskGenerator.Config,
    )
    eval_env = make_game(
        "hungercog",
        num_agents=resolved_num_agents,
        max_steps=steps,
        variants=HUNGER_MECHANICS,
    )

    return TrainTool(
        training_env=TrainingEnvironmentConfig(curriculum=curriculum),
        evaluator=EvaluatorConfig(
            simulations=[SimulationConfig(suite="hungercog", name="full_mechanics", env=eval_env)]
        ),
    )
