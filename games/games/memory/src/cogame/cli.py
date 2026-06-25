"""Standalone ``memory-play`` CLI.

Runs the default mission through a package-local console script. Importing
:mod:`cogame` triggers ``register_game(MyCoGame())`` so the game is available
through :func:`cogames.game.get_game` after import.

TODO(cogame): rename the script in ``pyproject.toml`` (``memory-play``) to
match your package name.
"""

from __future__ import annotations

import typer
from mettagrid.renderer.renderer import create_renderer
from mettagrid.simulator.simulator import Simulator

# Side-effect import: registers the game + its variants.
import cogame  # noqa: F401
from cogame.game import MyMission


def main(
    variant: list[str] = typer.Option(
        None,
        "--variant",
        "-v",
        help="Variant name(s) to apply. Repeat to stack, e.g. -v easy -v big_map.",
    ),
    num_agents: int = typer.Option(2, "--num-agents", "-n", min=1, help="Number of agents."),
    max_steps: int = typer.Option(200, "--max-steps", "-s", min=1, help="Episode step cap."),
    seed: int = typer.Option(42, "--seed", help="Simulator seed."),
    render: str = typer.Option(
        "gui",
        "--render",
        "-r",
        help="Render mode: 'gui' (MettaScope), 'unicode' (terminal), 'log', or 'none'.",
    ),
    autostart: bool = typer.Option(
        False,
        "--autostart/--no-autostart",
        help="Auto-start the episode on launch (gui only).",
    ),
) -> None:
    """Run a memory episode, optionally with MettaScope rendering."""
    mission = MyMission.create(num_agents=num_agents, max_steps=max_steps)
    if variant:
        # with_variants + make_env runs the full cogames variant lifecycle
        # (dependency resolution, topological configure order, apply).
        mission = mission.with_variants(list(variant))
    env = mission.make_env()

    simulator = Simulator()
    renderer = create_renderer(render, autostart=autostart)  # type: ignore[arg-type]
    simulator.add_event_handler(renderer)
    sim = simulator.new_simulation(env, seed=seed)

    renderer.render()
    while not sim.is_done():
        for i in range(sim.num_agents):
            sim.agent(i).set_action("noop")
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
