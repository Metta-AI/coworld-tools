"""Fill many seats on a live among_them server with assorted personas.

Each persona key from ``personas.py`` is instantiated as an :class:`Agent`
and driven by its own :class:`LiveGame` worker thread. One process, N
WebSocket clients — handy when the server is waiting for ``minPlayers:8``
and you don't want to open eight terminals.

Run::

    # Server already running on :2000 with minPlayers=8
    cd among_them/sdk
    uv sync
    uv run python examples/personas_fanout.py --count 8 --host localhost --port 2000

Mix and match with the Nim ``quick_player`` to fill 6 SDK + 2 raw
``evidencebot_v2`` (or any combination)::

    uv run python examples/personas_fanout.py --count 6
    nim r tools/quick_player evidencebot_v2 --players:2 \\
        --address:127.0.0.1 --port:2000 --name-prefix:evidencebot_v2
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Make sibling ``personas.py`` importable regardless of cwd.
_THIS_FILE = Path(__file__).resolve()
sys.path.insert(0, str(_THIS_FILE.parent))

from among_them_sdk import LiveGame  # noqa: E402

from personas import PERSONAS, _build  # noqa: E402  (sibling module)


def _short (persona_key: str) -> str:
  """Compact a persona key into a name-safe prefix.

  Server names go into chat / replays — keep them short and ASCII.
  ``aggressive_imposter`` -> ``aggimp``, ``paranoid_crewmate`` -> ``parcre``.
  """
  parts = [p for p in persona_key.split("_") if p]
  if len(parts) >= 2:
    return (parts[0][:3] + parts[1][:3]).lower()
  return parts[0][:6].lower() if parts else "sdk"


def run_one (
  persona_key: str,
  name: str,
  host: str,
  port: int,
  seed: int,
  *,
  max_ticks: int | None,
  connect_timeout: float,
  results: dict[str, Any],
  results_lock: threading.Lock,
) -> None:
  try:
    agent = _build(PERSONAS[persona_key], seed=seed)
    live = LiveGame(
      host=host,
      port=port,
      name=name,
      max_ticks=max_ticks,
      connect_timeout=connect_timeout,
    )
    print(f"[sdk] {name:<14} ({persona_key}) -> {live.url}")
    result, transcript = live.run_agent(agent)
    with results_lock:
      results[name] = {
        "persona": persona_key,
        "frames": transcript.frames_received,
        "masks": transcript.masks_sent,
        "summary": result.summary,
        "error": transcript.error,
      }
    print(f"[sdk] {name:<14} done (frames={transcript.frames_received})")
  except Exception as exc:
    with results_lock:
      results[name] = {
        "persona": persona_key,
        "error": repr(exc),
      }
    print(f"[sdk] {name:<14} errored: {exc!r}")


def parse_args () -> argparse.Namespace:
  p = argparse.ArgumentParser(
    description="Fan out many persona Agents at one live among_them server.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
  )
  p.add_argument("--host", default="localhost", help="Server hostname / IP.")
  p.add_argument("--port", type=int, default=2000, help="Server TCP port.")
  p.add_argument("--count", type=int, default=8, help="How many SDK seats to fill.")
  p.add_argument(
    "--mix",
    default=",".join(sorted(PERSONAS.keys())),
    help="Comma-separated persona keys (round-robined across --count).",
  )
  p.add_argument(
    "--name-prefix",
    default=None,
    help="Override the name-prefix scheme. Default: per-persona short prefix.",
  )
  p.add_argument(
    "--seed-base",
    type=int,
    default=100,
    help="First persona uses this seed; each later one adds +1.",
  )
  p.add_argument(
    "--max-ticks",
    type=int,
    default=None,
    help="Disconnect each persona after N FFI ticks. Default: ride the game out.",
  )
  p.add_argument(
    "--connect-timeout",
    type=float,
    default=30.0,
    help="Seconds to retry the initial WebSocket connect (per persona).",
  )
  p.add_argument(
    "--stagger-ms",
    type=int,
    default=150,
    help="Delay between successive persona connects (avoid thundering-herd kicks).",
  )
  return p.parse_args()


def main () -> int:
  args = parse_args()

  mix = [m.strip() for m in args.mix.split(",") if m.strip()]
  unknown = [m for m in mix if m not in PERSONAS]
  if unknown:
    raise SystemExit(
      f"--mix has unknown persona keys: {unknown}. "
      f"Known: {sorted(PERSONAS.keys())}"
    )
  if not mix:
    raise SystemExit("--mix is empty after parsing")
  if args.count < 1:
    raise SystemExit("--count must be >= 1")

  results: dict[str, Any] = {}
  results_lock = threading.Lock()
  threads: list[threading.Thread] = []
  shutdown = threading.Event()

  def _signal_handler (sig: int, _frame: Any) -> None:
    if shutdown.is_set():
      return
    print(f"\n[signal] caught {sig}; threads will exit when their sockets close.")
    shutdown.set()

  signal.signal(signal.SIGINT, _signal_handler)
  signal.signal(signal.SIGTERM, _signal_handler)

  for i in range(args.count):
    persona = mix[i % len(mix)]
    if args.name_prefix:
      name = f"{args.name_prefix}{i + 1}"
    else:
      name = f"{_short(persona)}{i + 1}"
    t = threading.Thread(
      target=run_one,
      kwargs={
        "persona_key": persona,
        "name": name,
        "host": args.host,
        "port": args.port,
        "seed": args.seed_base + i,
        "max_ticks": args.max_ticks,
        "connect_timeout": args.connect_timeout,
        "results": results,
        "results_lock": results_lock,
      },
      name=f"persona-{name}",
      daemon=True,
    )
    t.start()
    threads.append(t)
    if args.stagger_ms > 0:
      time.sleep(args.stagger_ms / 1000.0)

  for t in threads:
    while t.is_alive():
      t.join(timeout=1.0)
      if shutdown.is_set():
        break

  print("")
  print("=" * 60)
  print(f"Persona fanout summary ({len(results)}/{args.count} reported)")
  print("=" * 60)
  errors = 0
  for name in sorted(results):
    info = results[name]
    if info.get("error"):
      errors += 1
      print(f"  {name:<14} {info['persona']:<22} ERROR {info['error']}")
    else:
      print(
        f"  {name:<14} {info['persona']:<22} "
        f"frames={info['frames']:>5} masks={info['masks']:>4}"
      )
  return 1 if errors else 0


if __name__ == "__main__":
  raise SystemExit(main())
