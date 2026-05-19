"""CLI for running the standalone Overcogged package."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from mettagrid.renderer.renderer import RenderMode
from rich.console import Console

from overcogged.rendering import auto_render_mode

DEFAULT_MISSION = "basic"
DEFAULT_POLICY = "class=overcogged.agent.overcogged_agent.policy.OvercookedPolicy"
POLICY_OPTION_HELP = "Policy per team (repeatable, for example class=module.Class:1.0)."

app = typer.Typer(
    help="Play Overcogged as a standalone package.",
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode="rich",
    add_completion=False,
)
console = Console()


def _render_mode(render: Literal["auto", "gui", "unicode", "log", "none"]) -> RenderMode:
    if render == "auto":
        return auto_render_mode()
    return cast(RenderMode, render)


def _list_variants(names: tuple[str, ...]) -> str:
    return ", ".join(names) if names else "(none)"


@app.command("play")
def play_cmd(
    mission: Annotated[
        str,
        typer.Option("--mission", "-m", help="Mission to play."),
    ] = DEFAULT_MISSION,
    variant: Annotated[
        list[str] | None,
        typer.Option("--variant", "-v", help="Apply variant modifier (repeatable)."),
    ] = None,
    cogs: Annotated[
        int | None,
        typer.Option("--cogs", "-c", help="Override number of cogs."),
    ] = None,
    policy: Annotated[
        list[str] | None,
        typer.Option(
            "--policy",
            "-p",
            help=POLICY_OPTION_HELP,
        ),
    ] = None,
    device: Annotated[
        str,
        typer.Option("--device", help="Policy device (auto, cpu, cuda, cuda:0, etc.)."),
    ] = "auto",
    steps: Annotated[
        int | None,
        typer.Option("--steps", "-s", help="Override episode max steps.", min=1),
    ] = None,
    action_timeout_ms: Annotated[
        int,
        typer.Option("--action-timeout-ms", help="Max ms per action before noop.", min=1),
    ] = 10_000,
    render: Annotated[
        Literal["auto", "gui", "unicode", "log", "none"],
        typer.Option("--render", "-r", help="Render mode."),
    ] = "auto",
    seed: Annotated[
        int,
        typer.Option("--seed", help="RNG seed for reproducibility."),
    ] = 42,
    autostart: Annotated[
        bool,
        typer.Option("--autostart", help="Start simulation immediately."),
    ] = False,
    save_replay_dir: Annotated[
        Path | None,
        typer.Option("--save-replay-dir", help="Directory to write replay files into."),
    ] = None,
    save_replay_file: Annotated[
        Path | None,
        typer.Option("--save-replay-file", help="Exact replay file to write."),
    ] = None,
) -> None:
    from cogames.cli.mission import resolve_mission
    from cogames.cli.policy import parse_policy_spec
    from cogames.device import resolve_training_device
    from cogames.game import get_game
    from cogames.play import play

    game = get_game("overcogged")
    resolved_name, env_cfg, _ = resolve_mission(game, mission, variants_arg=variant, cogs=cogs)
    if steps is not None:
        env_cfg.game.max_steps = steps

    requested_policies = policy or [DEFAULT_POLICY]
    resolved_device = str(resolve_training_device(console, device))
    policy_specs = [parse_policy_spec(spec, device=resolved_device) for spec in requested_policies]

    play(
        console=console,
        env_cfg=env_cfg,
        policy_specs=policy_specs,
        game_name=resolved_name,
        seed=seed,
        device=resolved_device,
        render_mode=_render_mode(render),
        action_timeout_ms=action_timeout_ms,
        save_replay=save_replay_dir,
        save_replay_file=save_replay_file,
        autostart=autostart,
    )


@app.command("missions")
def missions_cmd() -> None:
    from cogames.game import get_game

    game = get_game("overcogged")
    for mission in game.missions:
        console.print(mission.full_name())


@app.command("variants")
def variants_cmd() -> None:
    from cogames.game import get_game

    game = get_game("overcogged")
    public = tuple(variant.name for variant in game.variant_registry.all() if not variant.name.startswith("reset_"))
    console.print(_list_variants(public))


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        ctx.invoke(play_cmd)


if __name__ == "__main__":
    app()
