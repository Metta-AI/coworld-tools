from rich.console import Console

from cogames.cli.policy import parse_policy_spec
from cogames.cli.mission import resolve_mission
from mettagrid.cogame.game import get_game
from cogames.play import play

import overcogged  # noqa: F401
from overcogged.classic.game import RESOURCE_NAMES


def test_classic_mission_preserves_original_objects() -> None:
    game = get_game("overcogged")
    resolved_name, env, _ = resolve_mission(game, "classic")

    assert resolved_name == "classic"
    for resource in RESOURCE_NAMES:
        assert resource in env.game.resource_names
    for object_name in ["carbon_extractor", "hub", "miner_station", "scrambler_station", "chest", "junction"]:
        assert object_name in env.game.objects


def test_classic_full_variant_uses_classic_graph() -> None:
    game = get_game("overcogged")
    _, env, _ = resolve_mission(game, "classic", variants_arg=["full"])

    assert "decoder" in env.game.resource_names
    assert "burn_complete" in env.game.events


def test_classic_mission_headless_scripted_rollout_completes() -> None:
    game = get_game("overcogged")
    resolved_name, env, _ = resolve_mission(game, "classic")

    play(
        console=Console(record=True),
        env_cfg=env,
        policy_specs=[
            parse_policy_spec(
                "class=overcogged.agent.overcogged_agent.policy.OvercookedPolicy",
                device="cpu",
            )
        ],
        game_name=resolved_name,
        seed=7,
        device="cpu",
        render_mode="none",
        autostart=True,
    )
