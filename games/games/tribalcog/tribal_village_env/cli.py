from __future__ import annotations

import os
import subprocess
from typing import Annotated

import typer
from rich.console import Console

from tribal_village_env.build import (
    ensure_nim_binary_current,
    ensure_nim_library_current,
    get_runtime_project_root,
)
from tribal_village_env.config import DEFAULT_ANSI_STEPS, DEFAULT_PROFILE_STEPS

# Optional CoGames training integration
try:
    from tribal_village_env.cogames.cli import attach_train_command
except ImportError:  # CoGames not installed; CLI should still work for play mode
    attach_train_command = None  # type: ignore[assignment]

app = typer.Typer(
    help="CLI for playing Tribal Village",
    invoke_without_command=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode="rich",
    add_completion=False,
)
console = Console()

# Attempt to register the PufferLib trainer if CoGames is installed locally.
if attach_train_command is not None:
    attach_train_command(
        app, command_name="train", require_cogames=False, console_fallback=console
    )
# ---------------------------------------------------------------------------
# Shared option type aliases (defined once, used by both play and root)
# ---------------------------------------------------------------------------
Render = Annotated[str, typer.Option("--render", "-r", help="Render mode: gui (default) or ansi (text-only)")]
Steps = Annotated[int, typer.Option("--steps", "-s", help="Steps to run when using ANSI render", min=1)]
MaxSteps = Annotated[int | None, typer.Option("--max-steps", help="Override max steps in ANSI mode", min=1)]
RandomActions = Annotated[bool, typer.Option("--random-actions/--no-random-actions", help="Use random actions in ANSI mode (otherwise no-op)")]
Profile = Annotated[bool, typer.Option("--profile", help="Enable Nim profiler (GUI mode only; runs headless steps then exits)")]
ProfileSteps = Annotated[int, typer.Option("--profile-steps", help="Steps to run when profiling", min=1)]
StepTiming = Annotated[bool, typer.Option("--step-timing", help="Enable per-step timing logs (GUI mode only)")]
StepTimingTarget = Annotated[int, typer.Option("--step-timing-target", help="Step index at which to start timing logs", min=0)]
StepTimingWindow = Annotated[int, typer.Option("--step-timing-window", help="Number of steps to log starting at target", min=0)]
RenderTiming = Annotated[bool, typer.Option("--render-timing", help="Enable per-frame render timing logs (GUI mode only)")]
RenderTimingTarget = Annotated[int, typer.Option("--render-timing-target", help="Frame index at which to start render timing logs", min=0)]
RenderTimingWindow = Annotated[int, typer.Option("--render-timing-window", help="Number of frames to log starting at target", min=0)]
RenderTimingEvery = Annotated[int, typer.Option("--render-timing-every", help="Log every N frames within the timing window", min=1)]
RenderTimingExit = Annotated[int | None, typer.Option("--render-timing-exit", help="Exit after this frame index (GUI mode only)", min=1)]


def _run_gui(
    profile: bool,
    profile_steps: int,
    step_timing: bool,
    step_timing_target: int,
    step_timing_window: int,
    render_timing: bool,
    render_timing_target: int,
    render_timing_window: int,
    render_timing_every: int,
    render_timing_exit: int | None,
) -> None:
    project_root = get_runtime_project_root()
    env = os.environ.copy()
    if profile:
        env["TV_PROFILE_STEPS"] = str(profile_steps)
    if step_timing:
        env["TV_STEP_TIMING"] = str(step_timing_target)
        env["TV_STEP_TIMING_WINDOW"] = str(step_timing_window)
    if render_timing:
        env["TV_RENDER_TIMING"] = str(render_timing_target)
        env["TV_RENDER_TIMING_WINDOW"] = str(render_timing_window)
        env["TV_RENDER_TIMING_EVERY"] = str(render_timing_every)
        if render_timing_exit is not None:
            env["TV_RENDER_TIMING_EXIT"] = str(render_timing_exit)

    if profile or step_timing or render_timing:
        cmd = ["nim", "r", "-d:release"]
        if profile:
            cmd.extend(["--profiler:on", "--stackTrace:on", "--lineTrace:on"])
        if step_timing:
            cmd.append("-d:stepTiming")
        if render_timing:
            cmd.append("-d:renderTiming")
        cmd.extend(["--path:src", "tribal_village.nim"])
        console.print("[cyan]Launching Tribal Village GUI via Nim...[/cyan]")
    else:
        cmd = [str(ensure_nim_binary_current())]
        console.print("[cyan]Launching Tribal Village GUI...[/cyan]")

    subprocess.run(cmd, cwd=project_root, check=True, env=env)


def _run_ansi(steps: int, max_steps: int | None, random_actions: bool) -> None:
    from tribal_village_env.environment import TribalVillageEnv

    config: dict[str, object] = {"render_mode": "ansi"}
    if max_steps is not None:
        config["max_steps"] = max_steps

    env = TribalVillageEnv(config=config)

    try:
        env.reset()
        console.print(env.render())

        for step in range(steps):
            actions = {
                f"agent_{agent_id}": (
                    int(env.single_action_space.sample()) if random_actions else 0
                )
                for agent_id in range(env.num_agents)
            }
            _, _, terminated, truncated, _ = env.step(actions)
            console.print(env.render())

            if all(terminated.values()) or all(truncated.values()):
                console.print(f"[yellow]Episode ended at step {step + 1}[/yellow]")
                break
    finally:
        env.close()


@app.command("play", help="Play Tribal Village using the Nim GUI or ANSI renderer")
def play(
    render: Render = "gui",
    steps: Steps = DEFAULT_ANSI_STEPS,
    max_steps: MaxSteps = None,
    random_actions: RandomActions = True,
    profile: Profile = False,
    profile_steps: ProfileSteps = DEFAULT_PROFILE_STEPS,
    step_timing: StepTiming = False,
    step_timing_target: StepTimingTarget = 0,
    step_timing_window: StepTimingWindow = 0,
    render_timing: RenderTiming = False,
    render_timing_target: RenderTimingTarget = 0,
    render_timing_window: RenderTimingWindow = 0,
    render_timing_every: RenderTimingEvery = 1,
    render_timing_exit: RenderTimingExit = None,
) -> None:
    render_mode = render.lower()
    if render_mode not in {"gui", "ansi"}:
        console.print("[red]Invalid render mode. Use 'gui' or 'ansi'.[/red]")
        raise typer.Exit(1)

    if render_mode == "gui":
        _run_gui(
            profile=profile,
            profile_steps=profile_steps,
            step_timing=step_timing,
            step_timing_target=step_timing_target,
            step_timing_window=step_timing_window,
            render_timing=render_timing,
            render_timing_target=render_timing_target,
            render_timing_window=render_timing_window,
            render_timing_every=render_timing_every,
            render_timing_exit=render_timing_exit,
        )
    else:
        ensure_nim_library_current()
        _run_ansi(steps=steps, max_steps=max_steps, random_actions=random_actions)


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    render: Render = "gui",
    steps: Steps = DEFAULT_ANSI_STEPS,
    max_steps: MaxSteps = None,
    random_actions: RandomActions = True,
    profile: Profile = False,
    profile_steps: ProfileSteps = DEFAULT_PROFILE_STEPS,
    step_timing: StepTiming = False,
    step_timing_target: StepTimingTarget = 0,
    step_timing_window: StepTimingWindow = 0,
    render_timing: RenderTiming = False,
    render_timing_target: RenderTimingTarget = 0,
    render_timing_window: RenderTimingWindow = 0,
    render_timing_every: RenderTimingEvery = 1,
    render_timing_exit: RenderTimingExit = None,
) -> None:
    """Default to play when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        ctx.forward(play)


if __name__ == "__main__":
    app()
