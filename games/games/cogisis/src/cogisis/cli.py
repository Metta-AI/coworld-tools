"""Command line interface for Cogisis."""

from __future__ import annotations

import argparse
import json
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from cogisis.client import build_client_frames, render_client_html
from cogisis.engine import CogisisSimulator
from cogisis.mission import CogisisMission
from cogisis.policies import make_policy
from cogisis.tunnel import CloudflareQuickTunnel
from cogisis.web.server import CogisisWebServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cogisis", description="Run Cogisis.")
    _add_run_options(parser)
    subparsers = parser.add_subparsers(dest="command")

    play = subparsers.add_parser("play", help="Run a Cogisis episode.")
    _add_run_options(play)

    client = subparsers.add_parser("client", help="Write a graphical Cogisis global client HTML file.")
    _add_episode_options(client)
    client.add_argument(
        "--output",
        "-o",
        default="cogisis-client.html",
        help="HTML output path.",
    )
    client.add_argument("--open", action="store_true", help="Open the generated client in the default browser.")
    return parser


def _add_episode_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-steps", "-s", type=int, default=15, help="Episode step cap.")
    parser.add_argument("--seed", type=int, default=42, help="Simulator seed.")
    parser.add_argument("--cogs", "-c", type=int, default=4, help="Number of cogs, 1-5.")
    parser.add_argument(
        "--policy",
        "-p",
        default="survivor",
        choices=["noop", "random", "survivor", "baseline", "signal"],
        help="Built-in policy.",
    )


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    _add_episode_options(parser)
    parser.add_argument(
        "--render",
        "-r",
        default="gui",
        choices=["gui", "web", "none", "unicode", "json"],
        help="Render mode. gui/web starts the local admin/global/player interfaces.",
    )
    parser.add_argument("--render-every", type=int, default=1, help="Unicode render cadence.")
    parser.add_argument("--port", type=int, default=0, help="Web server port (0 = random available port).")
    parser.add_argument("--tps", type=float, default=5.0, help="Ticks per second when autorun is enabled.")
    parser.add_argument(
        "--tunnel",
        action="store_true",
        help="Create a Cloudflare quick tunnel and print public client URLs.",
    )
    parser.add_argument(
        "--autorun",
        "--autoplay",
        "--autostart",
        action="store_true",
        help="Start the simulator immediately instead of waiting for admin/player controls.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {None, "play"}:
        return play(args)
    if args.command == "client":
        return client(args)
    parser.error(f"Unknown command {args.command!r}")
    return 2


def _build_simulator(args: argparse.Namespace) -> CogisisSimulator:
    if args.max_steps < 1:
        raise SystemExit("--max-steps must be at least 1")
    if args.cogs < 1 or args.cogs > 5:
        raise SystemExit("--cogs must be between 1 and 5")

    mission = CogisisMission(num_cogs=args.cogs, max_steps=args.max_steps, seed=args.seed)
    return CogisisSimulator(mission.build_world())


def play(args: argparse.Namespace) -> int:
    sim = _build_simulator(args)
    policy = make_policy(args.policy, seed=args.seed)
    render_mode = "gui" if args.render == "web" else args.render

    if render_mode == "gui":
        server = CogisisWebServer(
            sim,
            policy,
            policy_name=args.policy,
            seed=args.seed,
            max_steps=args.max_steps,
            port=args.port,
            tick_rate=args.tps,
            autorun=args.autorun,
        )
        server.start()
        tunnel = None
        try:
            if args.tunnel:
                tunnel = CloudflareQuickTunnel(server.local_base_url())
                server.set_public_base_url(tunnel.start())
            _print_client_urls(server.status())
            server.wait()
        finally:
            if tunnel is not None:
                tunnel.stop()
            server.stop()
        return 0

    if args.tunnel:
        raise SystemExit("--tunnel requires --render gui or --render web")

    if not args.autorun:
        return 0

    _run_headless(sim, policy, render_mode, render_every=args.render_every)
    return 0


def _run_headless(sim: CogisisSimulator, policy, render_mode: str, *, render_every: int) -> None:
    if render_mode == "unicode":
        print(sim.render_unicode())
    while not sim.done:
        result = sim.step_with_policy(policy)
        if render_mode == "unicode" and (result.done or result.step % max(1, render_every) == 0):
            print()
            print(sim.render_unicode())
    if render_mode == "json":
        print(json.dumps({"stats": sim.stats(), **sim.world.snapshot()}, sort_keys=True))


def _print_client_urls(status: dict) -> None:
    artifacts = status.get("artifacts", {})
    client_urls = status.get("client_urls", {})
    if artifacts.get("workspace"):
        print(f"Artifacts: {artifacts['workspace']}")
    players = client_urls.get("players")
    if isinstance(players, list):
        print("Player clients:")
        for slot, link in enumerate(players):
            print(f"  {slot}: {link}")
    if client_urls.get("global"):
        print(f"Global client: {client_urls['global']}")
    if client_urls.get("admin"):
        print(f"Admin client: {client_urls['admin']}")
    print("Waiting for the game to exit...")


def client(args: argparse.Namespace) -> int:
    sim = _build_simulator(args)
    frames = build_client_frames(sim, args.policy, seed=args.seed)

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_client_html(frames), encoding="utf-8")

    final_frame = frames[-1]
    print(f"Wrote Cogisis global client to {output_path}")
    print(f"frames={len(frames)} steps={final_frame['step']} phase={final_frame['phase']}")
    if args.open:
        webbrowser.open(output_path.as_uri())
    return 0


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
