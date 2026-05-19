"""Bombercog command-line smoke tool.

Launches a bombercog episode with every agent taking the ``noop`` action. In
``gui`` render mode (the default) the episode is streamed through MettaScope so
you can watch it; pass ``--render none`` for a headless run that prints
``done: ticks=N agents_alive=M`` when the episode finishes.
"""

from __future__ import annotations

import typer

from mettagrid.renderer.renderer import create_renderer
from mettagrid.simulator.simulator import Simulator

from bombercog import BombercogMission

# Side-effect import: registers every variant by name on the framework registry.
import bombercog.variants  # noqa: F401


def main(
    variant: list[str] = typer.Option(
        None,
        "--variant",
        "-v",
        help="Variant name(s) to apply. Repeat to stack, e.g. -v powerups -v kickable_bombs.",
    ),
    num_agents: int = typer.Option(2, "--num-agents", "-n", min=1, help="Number of agents."),
    max_steps: int = typer.Option(500, "--max-steps", "-s", min=1, help="Episode step cap."),
    seed: int = typer.Option(42, "--seed", help="Simulator seed."),
    render: str = typer.Option(
        "gui",
        "--render",
        "-r",
        help="Render mode: 'gui' (MettaScope), 'unicode' (terminal miniscope), 'log', or 'none'.",
    ),
    autostart: bool = typer.Option(
        False,
        "--autostart/--no-autostart",
        help="Auto-start the episode on launch (gui only; default: wait for play button).",
    ),
) -> None:
    """Run a bombercog episode, optionally with MettaScope rendering."""
    mission = BombercogMission.create(num_agents, max_steps)
    if variant:
        mission = mission.with_variants(list(variant))
    env = mission.make_env()

    simulator = Simulator()
    renderer = create_renderer(render, autostart=autostart)  # type: ignore[arg-type]
    simulator.add_event_handler(renderer)
    sim = simulator.new_simulation(env, seed=seed)

    renderer.render()  # initial frame so the user sees t=0 before pressing play
    while not sim.is_done():
        for i in range(sim.num_agents):
            sim.agent(i).set_action("noop")
        # Apply user keypresses queued by the renderer on the previous frame.
        # These override the noop we just set so WASD actually moves agents.
        renderer.apply_deferred_user_actions()
        sim.step()
        renderer.render()

    agents_alive = sum(
        1 for o in sim.grid_objects().values() if o.get("type_name") == "agent"
    )
    typer.echo(f"done: ticks={sim.current_step} agents_alive={agents_alive}")


def cli() -> None:
    """Console-script entry point."""
    typer.run(main)


if __name__ == "__main__":
    cli()
