#!/usr/bin/env -S uv run
"""Launch local BitWorld AmongThem with cyborg LLM policies and observer mode."""

from __future__ import annotations

import argparse
import os
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

from mettagrid import MettaGridConfig
from mettagrid.bitworld import (
    BITWORLD_AMONG_THEM_IMPOSTER_COOLDOWN_TICKS,
    BITWORLD_AMONG_THEM_IMPOSTER_COUNT,
    BITWORLD_AMONG_THEM_PLAYER_COUNT,
    BITWORLD_AMONG_THEM_TASKS_PER_PLAYER,
    BITWORLD_AMONG_THEM_VOTE_TIMER_TICKS,
)
from mettagrid.runner import bitworld_runner
from mettagrid.runner.types import PureSingleEpisodeJob


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local AmongThem cyborg policies and open the BitWorld global observer."
    )
    parser.add_argument("--port", type=int, default=2000, help="Local BitWorld server port.")
    parser.add_argument("--host", default="0.0.0.0", help="Server bind host.")
    parser.add_argument("--browser-host", default="localhost", help="Host name used in the observer URL.")
    parser.add_argument(
        "--tailscale",
        action="store_true",
        help="Bind to the first `tailscale ip -4` address and use it in the observer URL.",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=BITWORLD_AMONG_THEM_PLAYER_COUNT,
        help="Number of cyborg players to connect.",
    )
    parser.add_argument(
        "--imposters",
        type=int,
        default=BITWORLD_AMONG_THEM_IMPOSTER_COUNT,
        help="Number of imposters.",
    )
    parser.add_argument(
        "--tasks-per-player",
        type=int,
        default=BITWORLD_AMONG_THEM_TASKS_PER_PLAYER,
        help="AmongThem tasksPerPlayer value.",
    )
    parser.add_argument(
        "--imposter-cooldown-ticks",
        type=int,
        default=BITWORLD_AMONG_THEM_IMPOSTER_COOLDOWN_TICKS,
        help="AmongThem imposterCooldownTicks value.",
    )
    parser.add_argument(
        "--vote-timer-ticks",
        type=int,
        default=BITWORLD_AMONG_THEM_VOTE_TIMER_TICKS,
        help="AmongThem voteTimerTicks value.",
    )
    parser.add_argument(
        "--task-complete-ticks",
        type=int,
        default=None,
        help="Optional ticks required to hold A for one task.",
    )
    parser.add_argument("--max-steps", type=int, default=12000, help="Maximum BitWorld ticks to run.")
    parser.add_argument("--seed", type=int, default=17, help="Game seed.")
    parser.add_argument(
        "--bitworld-root",
        type=Path,
        default=Path.home() / "Code/bitworld",
        help="BitWorld checkout root. Used for BITWORLD_REPO_PATH and default binary lookup.",
    )
    parser.add_argument(
        "--binary",
        type=Path,
        default=None,
        help="AmongThem server binary. Defaults to <bitworld-root>/among_them/among_them.",
    )
    parser.add_argument(
        "--no-rebuild",
        action="store_false",
        dest="rebuild",
        help="Skip rebuilding <bitworld-root>/among_them/among_them.nim before launch.",
    )
    parser.add_argument(
        "--provider",
        choices=("auto", "anthropic", "openai"),
        default="auto",
        help="LLM provider for meeting talk. auto prefers OPENAI_API_KEY, then Anthropic/Bedrock.",
    )
    parser.add_argument("--model", default=None, help="Optional provider model override.")
    parser.add_argument(
        "--llm-talk",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use LLMs for queued meeting evidence. Disable for pure NotTooDumb baseline/debug runs.",
    )
    parser.add_argument("--no-browser", action="store_true", help="Print observer URL without opening a browser.")
    parser.add_argument("--no-nim-core", action="store_true", help="Disable the local nottoodumb Nim core.")
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="Optional replay output URI path. Must satisfy the shared episode validator suffix if provided.",
    )
    parser.add_argument(
        "--observer-delay",
        type=float,
        default=8.0,
        help="Seconds to keep the observer open before connecting policy players.",
    )
    parser.add_argument(
        "--startup-delay",
        type=float,
        default=1.0,
        help="Seconds to wait after starting the BitWorld server before opening the observer.",
    )
    parser.add_argument(
        "--observer-reconnect-seconds",
        type=float,
        default=1.0,
        help="Seconds between global observer reconnect attempts. Use 0 to disable reconnect.",
    )
    parser.add_argument(
        "--debug-stats",
        action="store_true",
        help="Collect per-agent NotTooDumb debug stats. Useful for audits but slower.",
    )
    return parser.parse_args()


def _apply_tailscale_address(args: argparse.Namespace) -> None:
    if not args.tailscale:
        return
    tailscale_ips = subprocess.check_output(["tailscale", "ip", "-4"], text=True).strip().splitlines()
    if not tailscale_ips:
        raise RuntimeError("No Tailscale IPv4 address found")
    tailscale_ip = tailscale_ips[0]
    args.host = tailscale_ip
    args.browser_host = tailscale_ip


def _rebuild_binary(args: argparse.Namespace, bitworld_root: Path) -> None:
    if args.rebuild:
        subprocess.run(
            ["nim", "c", "-d:release", "--opt:speed", "among_them/among_them.nim"], cwd=bitworld_root, check=True
        )
        if not args.no_nim_core:
            subprocess.run(["python", "among_them/players/build_nottoodumb.py"], cwd=bitworld_root, check=True)


def _policy_uri(args: argparse.Namespace) -> str:
    query: dict[str, str] = {
        "llm_talk": "true" if args.llm_talk else "false",
        "llm_provider": args.provider,
        "use_nim_core": "false" if args.no_nim_core else "true",
    }
    if args.model:
        query["llm_model"] = args.model
    return f"metta://policy/amongthem_cyborg?{urlencode(query)}"


def _crewmate_count(args: argparse.Namespace) -> int:
    return args.players - min(args.imposters, max(0, args.players - 1))


def _install_fixed_port_server(args: argparse.Namespace) -> None:
    def start_server_on_requested_port(
        binary_path: Path,
        config: bitworld_runner.BitWorldConfig,
        replay_path: Path | None = None,
    ):
        config.host = args.host
        config.port = args.port
        server_proc = bitworld_runner._start_server(binary_path, config, replay_path)
        time.sleep(args.startup_delay)
        if server_proc.poll() is not None:
            stderr = server_proc.stderr.read().decode(errors="replace") if server_proc.stderr is not None else ""
            raise RuntimeError(stderr)

        observer_query = ""
        if args.observer_reconnect_seconds > 0:
            observer_query = f"?{urlencode({'reconnect': args.observer_reconnect_seconds})}"
        observer_url = f"http://{args.browser_host}:{args.port}/client/global.html{observer_query}"
        print(f"Observer: {observer_url}", flush=True)
        if not args.no_browser:
            webbrowser.open(observer_url)
        time.sleep(args.observer_delay)
        return server_proc

    bitworld_runner._start_server_on_free_port = start_server_on_requested_port


def main() -> None:
    args = _parse_args()
    _apply_tailscale_address(args)
    bitworld_root = args.bitworld_root.expanduser().resolve()
    binary = (args.binary or bitworld_root / "among_them" / "among_them").expanduser().resolve()
    _rebuild_binary(args, bitworld_root)
    os.environ.setdefault("BITWORLD_REPO_PATH", str(bitworld_root))
    if args.debug_stats:
        os.environ["BITWORLD_DEBUG_STATS"] = "1"

    _install_fixed_port_server(args)
    bitworld_runner._find_bitworld_binary = lambda _config: binary

    policy_uri = _policy_uri(args)
    job = PureSingleEpisodeJob(
        policy_uris=[policy_uri],
        assignments=[0 for _ in range(args.players)],
        env=MettaGridConfig.model_validate(
            {
                "game": {
                    "num_agents": args.players,
                    "max_steps": args.max_steps,
                    "bitworld": {
                        "imposterCount": args.imposters,
                        "tasksPerPlayer": args.tasks_per_player,
                        "taskCompleteTicks": args.task_complete_ticks,
                        "imposterCooldownTicks": args.imposter_cooldown_ticks,
                        "voteTimerTicks": args.vote_timer_ticks,
                    },
                }
            },
        ),
        game_engine="bitworld",
        results_uri=None,
        replay_uri=args.replay.expanduser().resolve().as_uri() if args.replay else None,
        seed=args.seed,
    )

    print(f"Policy: {policy_uri}", flush=True)
    task_complete_ticks = args.task_complete_ticks if args.task_complete_ticks is not None else "BitWorld default"
    print(
        "Game: "
        f"players={args.players} "
        f"imposters={args.imposters} "
        f"tasks_per_player={args.tasks_per_player} "
        f"total_crewmate_tasks={_crewmate_count(args) * args.tasks_per_player} "
        f"imposter_cooldown_ticks={args.imposter_cooldown_ticks} "
        f"vote_timer_ticks={args.vote_timer_ticks} "
        f"task_complete_ticks={task_complete_ticks}",
        flush=True,
    )
    if args.replay:
        print(f"Replay: {args.replay.expanduser().resolve()}", flush=True)
    result = bitworld_runner.run_bitworld_episode(job)
    print(f"rewards {result.rewards}", flush=True)
    print(f"steps {result.steps}", flush=True)
    print(f"chat_sent {[stats.get('chat.sent', 0.0) for stats in result.stats['agent']]}", flush=True)


if __name__ == "__main__":
    main()
