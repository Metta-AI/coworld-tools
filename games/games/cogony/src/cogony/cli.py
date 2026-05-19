"""cogony CLI: `cogony play` runs the default cogony mission."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from mettagrid.simulator.simulator import Simulator

import cogony  # noqa: F401  (side effect: register_game)
from cogony import runner_support as _runner_support
from cogony.episode_runner import EpisodeRunner, EpisodeRunnerConfig
from cogony.mission import CogonyMission

app = typer.Typer(help="cogony: a MettaGrid game.")

_make_policy = _runner_support._make_policy
_start_toolsy_coworld_processes = _runner_support._start_toolsy_coworld_processes
_obs_grid_from_decoded = _runner_support._obs_grid_from_decoded
_obs_global_from_decoded = _runner_support._obs_global_from_decoded
_obs_center_from_decoded = _runner_support._obs_center_from_decoded
_decode_observation_tokens = _runner_support._decode_observation_tokens
_decode_observation_grid = _runner_support._decode_observation_grid
_refresh_policy_obs_grids = _runner_support._refresh_policy_obs_grids
_current_policy_infos = _runner_support._current_policy_infos


def _load_dotenv() -> None:
    """Load project-root .env values that are not already set."""
    env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _mettascope_wasm_dir() -> Path | None:
    """Return the repo-local MettaScope WASM dist directory."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    for candidate in [
        repo_root / "mettagrid" / "nim" / "mettascope" / "dist",
        repo_root / ".mettagrid" / "nim" / "mettascope" / "dist",
    ]:
        if (candidate / "mettascope.html").exists():
            return candidate
    return None


def _policy_env_info_from_config(config):
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface

    return PolicyEnvInterface.from_mg_cfg(config)


def _web_renderer_factory(**kwargs):
    from cogony.web.server import WebRenderer

    return WebRenderer(**kwargs)


def _renderer_factory(render_mode: str, should_autoplay: bool):
    from mettagrid.renderer.renderer import create_renderer

    return create_renderer(render_mode, autostart=should_autoplay)  # type: ignore[arg-type]


def _print_client_urls(status: dict) -> None:
    artifacts = status.get("artifacts", {})
    client_urls = status.get("client_urls", {})
    players = client_urls.get("players")
    if isinstance(players, list) and artifacts.get("workspace"):
        typer.echo(f"Artifacts: {artifacts['workspace']}")
        typer.echo("Player clients:")
        for slot, link in enumerate(players):
            typer.echo(f"  {slot}: {link}")
        if client_urls.get("global"):
            typer.echo(f"Global client: {client_urls['global']}")
        if client_urls.get("admin"):
            typer.echo(f"Admin client: {client_urls['admin']}")
        typer.echo("Waiting for the game to exit...")
        return
    for name in ("admin", "global-client", "policy-debugger?agent=0"):
        url = client_urls.get(name)
        if url:
            typer.echo(f"{name}: {url}")


def _print_artifact_results(status: dict) -> None:
    artifacts = status.get("artifacts", {})
    if artifacts.get("results"):
        typer.echo(f"Results: {artifacts['results']}")
    if artifacts.get("replay"):
        typer.echo(f"Replay: {artifacts['replay']}")
    if artifacts.get("logs"):
        typer.echo(f"Logs: {artifacts['logs']}")


def _launch_path_from_client_flags(*, agent: bool, global_client: bool, admin: bool) -> str:
    selected = [name for name, enabled in (("agent", agent), ("global", global_client), ("admin", admin)) if enabled]
    if len(selected) > 1:
        raise typer.BadParameter("Choose only one of --agent, --global, or --admin.")
    if selected == ["agent"]:
        return "/policy-debugger?agent=0"
    if selected == ["global"]:
        return "/global"
    if selected == ["admin"]:
        return "/admin"
    return "/"


@app.callback()
def _root() -> None:
    """cogony entry point."""


@app.command()
def play(
    variant: list[str] = typer.Option(
        None, "--variant", "-v", help="Variant name(s) to apply. Repeat to stack."
    ),
    max_steps: int = typer.Option(10000, "--max-steps", "-s", min=1, help="Episode step cap."),
    seed: int = typer.Option(42, "--seed", help="Simulator seed."),
    policy: str = typer.Option(
        "noop",
        "--policy",
        "-p",
        help="Policy: 'noop', 'random', 'baseline', 'toolsy', or 'toolsy-autopilot'.",
    ),
    cogs: int = typer.Option(
        0, "--cogs", "-c", min=0, help="Number of agents (0 = default, min 4).",
    ),
    render: str = typer.Option(
        "gui",
        "--render",
        "-r",
        help="Render mode: 'gui'/'web' for the browser client, or 'none', 'unicode', 'log'.",
    ),
    tps: float = typer.Option(5.0, "--tps", min=0.1, help="Ticks per second."),
    port: int = typer.Option(0, "--port", help="Web server port (0 = random available port)."),
    autoplay: bool = typer.Option(
        False,
        "--autoplay",
        help="Start the simulator running immediately instead of waiting for MettaScope controls.",
    ),
    autostart: bool = typer.Option(
        False,
        "--autostart",
        help="Alias for --autoplay, kept for existing smoke commands.",
    ),
    codex: bool = typer.Option(
        False,
        "--codex",
        help="Open the viewer in the Codex browser instead of a dedicated external browser window.",
    ),
    agent: bool = typer.Option(
        False,
        "--agent",
        help="Launch the selected agent policy debugger.",
    ),
    global_client: bool = typer.Option(
        False,
        "--global",
        help="Launch the global viewer client.",
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Launch the admin controls page.",
    ),
    god_mode: bool = typer.Option(
        False,
        "--god-mode",
        help="Enable testing-only resource transfer vibes.",
    ),
) -> None:
    """Run a cogony episode with web-based MettaScope viewer."""
    _load_dotenv()
    variant = None if hasattr(variant, "default") else variant
    port = int(getattr(port, "default", port))
    codex = bool(getattr(codex, "default", codex))
    agent = bool(getattr(agent, "default", agent))
    global_client = bool(getattr(global_client, "default", global_client))
    admin = bool(getattr(admin, "default", admin))
    god_mode = bool(getattr(god_mode, "default", god_mode))
    launch_path = _launch_path_from_client_flags(agent=agent, global_client=global_client, admin=admin)
    runner = EpisodeRunner(
        EpisodeRunnerConfig(
            variant=list(variant) if variant else None,
            max_steps=max_steps,
            seed=seed,
            policy=policy,
            cogs=cogs,
            render=render,
            tps=tps,
            port=port,
            autoplay=autoplay,
            autostart=autostart,
            codex=codex,
            wasm_dir=_mettascope_wasm_dir(),
            god_mode=god_mode,
            launch_path=launch_path,
        ),
        mission_factory=CogonyMission,
        simulator_factory=Simulator,
        web_renderer_factory=_web_renderer_factory,
        renderer_factory=_renderer_factory,
        policy_env_info_factory=_policy_env_info_from_config,
        make_policy=_make_policy,
        start_coworld_processes=_start_toolsy_coworld_processes,
        decode_observation_tokens=_decode_observation_tokens,
        on_ready=_print_client_urls,
    )
    runner.run()
    _print_artifact_results(runner.status())


@app.command()
def docs(
    port: int = typer.Option(8801, "--port", "-p", help="Port for the docs server."),
) -> None:
    """Serve the rules docs with auto-reload and open in browser."""
    import subprocess
    import webbrowser

    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "serve_rules.py")
    script = os.path.normpath(script)
    typer.echo(f"Starting docs server on http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")
    subprocess.run(["python3", script, str(port)])


def cli() -> None:
    app()


if __name__ == "__main__":
    cli()
