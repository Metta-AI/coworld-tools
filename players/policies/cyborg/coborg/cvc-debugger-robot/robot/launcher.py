"""Standalone launcher for the robot debugger.

Starts the observability server immediately, then waits for the user to
launch a game from the debugger UI (POST /api/launch). The game runs in
the same process so RobotPolicy picks up the existing hub seamlessly.

Usage:
  python robot/launcher.py
  python robot/launcher.py --port 8777
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback

from robot.observability import ObservabilityHub, start_server


def _run_game(hub: ObservabilityHub, params: dict) -> None:
  """Resolve mission + policy and run one episode."""
  # Ensure cogames registers its games and policies
  import cogames  # noqa: F401
  from cogames.cli.mission import resolve_mission
  from cogames.cli.policy import parse_policy_spec
  from cogames.game import get_game
  from cogames.play import play as play_game
  from cogames.seed import seed_rollout_rng
  from mettagrid.policy.loader import discover_and_register_policies
  from rich.console import Console

  discover_and_register_policies()

  map_name = params.get("map", "arena")
  steps = int(params.get("steps", 1000))
  seed = int(params.get("seed", 42))
  render = params.get("render", "none")
  autostart = bool(params.get("autostart", True))

  game = get_game("cogs_vs_clips")
  mission_name, env_cfg, _ = resolve_mission(game, map_name)

  env_cfg.game.max_steps = steps

  policy_spec = parse_policy_spec("class=robot.RobotPolicy,kw.debug=true", device="cpu")
  seed_rollout_rng(seed)

  console = Console(stderr=True)
  hub.set_game_config({
    "map": map_name,
    "max_steps": steps,
    "seed": seed,
    "render": render,
    "num_agents": env_cfg.game.num_agents,
  })

  print(f"\n  Starting game: {mission_name} ({steps} steps, seed={seed})\n")

  play_game(
    console,
    env_cfg=env_cfg,
    policy_specs=[policy_spec],
    seed=seed,
    device="cpu",
    render_mode=render,
    action_timeout_ms=10000,
    game_name=mission_name,
    autostart=autostart,
  )


def main() -> None:
  parser = argparse.ArgumentParser(description="Robot Debugger Launcher")
  parser.add_argument("--port", type=int, default=8777, help="Server port")
  args = parser.parse_args()

  os.environ["ROBOT_DEBUG"] = "1"

  hub = ObservabilityHub()
  hub._launcher_mode = True
  hub.set_game_status("waiting")
  start_server(hub, port=args.port, open_browser=True)

  print("  Waiting for game launch from debugger UI...")
  print("  (or press Ctrl+C to exit)\n")

  try:
    while True:
      params = hub.wait_for_launch(timeout=1.0)
      if params is None:
        continue

      hub.set_game_status("starting")
      hub.reset_for_new_game()
      hub.set_game_status("starting")

      try:
        _run_game(hub, params)
        hub.set_game_status("finished")
      except Exception:
        traceback.print_exc()
        hub.set_game_status("finished")
        hub.set_game_results({"error": traceback.format_exc()})

      print("\n  Game finished. Waiting for next launch...\n")
      hub.set_game_status("waiting")

  except KeyboardInterrupt:
    print("\n  Launcher stopped.")
    sys.exit(0)


if __name__ == "__main__":
  main()
