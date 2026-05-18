"""Connect one *or many* copies of one persona to a live among_them server.

Where ``personas.py`` runs personas in :class:`LocalSim` (synthetic frames),
this script wires the *same* :class:`Agent` into a real game via
:class:`LiveGame`. Use it when you've already started a server (e.g.
``nim r among_them.nim --address:0.0.0.0 --port:2000 --config:'{...}'`` or
``python3 among_them/host_game.py``) and want to fill one or more seats
with an SDK persona.

By default the persona is the *scripted* version from ``personas.py``
(``ScriptedChatter``/``SilentChatter``, no LLM in the loop). Pass
``--llm`` to rebuild the same persona with LLM-backed modules — chat,
voting, *and* the natural-language instructions parser all run through
the SDK's default LLM (``claude-sonnet`` on AWS Bedrock — set
``AWS_PROFILE`` and ``AWS_REGION``).

For multi-seat fanout, pass ``--players N``. Each copy gets its own
:class:`Agent`, its own :class:`LiveGame` thread, a unique seed, and
a unique server-side name (``<base>-1``, ``<base>-2``, ...). For mixing
*different* personas in one process, use ``personas_fanout.py`` instead.

Examples::

    # Scripted persona, single seat
    cd among_them/sdk
    uv run python examples/personas_live.py \\
        --persona paranoid_crewmate --host localhost --port 2000

    # LLM-driven, single seat (Bedrock default)
    uv run python examples/personas_live.py \\
        --persona paranoid_crewmate --host localhost --port 2000 --llm

    # Two LLM copies of the same persona under one shared name root
    uv run python examples/personas_live.py \\
        --persona paranoid_crewmate --host localhost --port 2000 \\
        --llm --name claude-paranoid --players 2

    # Cheaper model, only LLM for chat:
    uv run python examples/personas_live.py \\
        --persona aggressive_imposter --host localhost --port 2000 \\
        --llm-chat --model claude-haiku
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Make sibling ``personas.py`` importable regardless of cwd.
_THIS_FILE = Path(__file__).resolve()
sys.path.insert(0, str(_THIS_FILE.parent))

from among_them_sdk import (  # noqa: E402
  Agent,
  LiveGame,
  LLMChatter,
  LLMVoter,
)
from among_them_sdk.live_game import LiveGameTranscript  # noqa: E402

from personas import PERSONAS  # noqa: E402  (sibling module)


def parse_args () -> argparse.Namespace:
  p = argparse.ArgumentParser(
    description="Connect one persona Agent to a live among_them server.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
  )
  p.add_argument(
    "--persona",
    default="paranoid_crewmate",
    choices=sorted(PERSONAS.keys()),
    help="Which persona block from personas.py to instantiate.",
  )
  p.add_argument("--host", default="localhost", help="Server hostname / IP.")
  p.add_argument("--port", type=int, default=2000, help="Server TCP port.")
  p.add_argument(
    "--name",
    default=None,
    help=(
      "Player name. With --players=1 (default) this is the literal name. "
      "With --players>1 it's a base; each seat appends '-<i>'. "
      "If omitted, defaults to '<persona>-<pid>' so back-to-back runs don't "
      "collide with a stale identity still tracked server-side."
    ),
  )
  p.add_argument(
    "--players",
    type=int,
    default=1,
    help=(
      "How many copies of this persona to fan out as separate seats. "
      "Each gets its own Agent + LiveGame thread, a unique name, and "
      "seed=<--seed> + i. For mixing different personas, use "
      "personas_fanout.py."
    ),
  )
  p.add_argument(
    "--stagger-ms",
    type=int,
    default=150,
    help=(
      "Delay between successive connects when --players>1 (avoid "
      "thundering-herd duplicate-name races server-side)."
    ),
  )
  p.add_argument("--seed", type=int, default=42, help="Base RNG seed; copy i uses --seed + i.")
  p.add_argument(
    "--max-ticks",
    type=int,
    default=None,
    help="Disconnect after N FFI ticks. Default: ride the whole game out.",
  )
  p.add_argument(
    "--connect-timeout",
    type=float,
    default=20.0,
    help="Seconds to retry the initial WebSocket connect.",
  )

  # ----- LLM controls -----
  llm = p.add_argument_group("LLM (default: scripted modules from personas.py)")
  llm.add_argument(
    "--llm",
    action="store_true",
    help="Shorthand for --llm-chat --llm-vote --llm-instructions.",
  )
  llm.add_argument(
    "--llm-chat",
    action="store_true",
    help="Use LLMChatter (override personas.py's scripted chatter).",
  )
  llm.add_argument(
    "--llm-vote",
    action="store_true",
    help="Use LLMVoter for meeting-time votes.",
  )
  llm.add_argument(
    "--llm-instructions",
    action="store_true",
    help="Parse the persona's free-text instructions through the LLM.",
  )
  llm.add_argument(
    "--model",
    default=None,
    help=(
      "Model string for any LLM module. "
      "Default: claude-sonnet (Bedrock). Other examples: claude-haiku, "
      "openai/gpt-5.5, anthropic/claude-3-5-sonnet, gateway/openai/gpt-5.5."
    ),
  )
  return p.parse_args()


def _resolve_llm_flags (args: argparse.Namespace) -> tuple[bool, bool, bool]:
  if args.llm:
    return (True, True, True)
  return (args.llm_chat, args.llm_vote, args.llm_instructions)


def _build_agent (args: argparse.Namespace, seed: int) -> Agent:
  """Same shape as ``personas._build`` but with optional LLM module overrides."""
  spec = PERSONAS[args.persona]
  use_chat, use_vote, use_inst = _resolve_llm_flags(args)

  modules: dict[str, Any] = dict(spec.get("modules", {}))
  if use_chat:
    tone = spec.get("cognitive", {}).get("chat_tone", "neutral")
    modules["chatter"] = LLMChatter(model=args.model, tone=tone)
  if use_vote:
    modules["voter"] = LLMVoter(model=args.model)

  agent = Agent.create(
    instructions=spec["instructions"],
    cognitive=spec["cognitive"],
    seed=seed,
    use_llm_for_instructions=use_inst,
    instructions_model=args.model,
    **modules,
  )
  return agent


def _resolve_player_names (args: argparse.Namespace) -> list[str]:
  """Compute the unique server-side name for each requested seat.

  - ``--players=1`` (default): one name. ``--name`` (if given) used verbatim,
    else ``<persona>-<pid>`` to avoid colliding with stale identities.
  - ``--players>1``: ``<base>-<i>`` for ``i=1..N`` where ``base`` is
    ``--name`` if given, else ``<persona>-<pid>``.
  """
  base = args.name or f"{args.persona}-{os.getpid() % 10000:04d}"
  if args.players <= 1:
    return [base]
  return [f"{base}-{i + 1}" for i in range(args.players)]


@dataclass
class _SeatResult:
  """One seat's outcome from a fanout run, captured for the summary table."""

  index: int
  name: str
  seed: int
  summary: str = ""
  transcript: LiveGameTranscript | None = None
  error: str | None = None
  modules_summary: str = ""


def _llm_modules_summary (agent: Agent) -> str:
  parts = []
  for label, mod in (("chatter", agent.chatter), ("voter", agent.voter)):
    backend = type(mod).__name__
    if hasattr(mod, "llm") and mod.llm is not None:
      backend += f"({mod.llm.provider_kind}/{mod.llm._backend.model})"
    elif hasattr(mod, "llm") and mod.llm is None:
      backend += "(scripted-fallback: no LLM creds)"
    parts.append(f"{label}={backend}")
  return ", ".join(parts)


def _print_seat_summary (seat: _SeatResult) -> None:
  """Print the post-run line(s) for one seat, including the zero-frames hint."""
  t = seat.transcript
  if t is None:
    print(f"[{seat.name}] errored before transcript: {seat.error}")
    return
  print(f"[{seat.name}] {seat.summary}")
  print(
    f"[{seat.name}] frames={t.frames_received} "
    f"masks={t.masks_sent} "
    f"meetings={t.meetings_seen} "
    f"chats_sent={len(t.chat_messages_sent)} "
    f"votes={len(t.vote_advisories)} "
    f"err={t.error!r} "
    f"close={t.close_code!r}/{t.close_reason!r}"
  )
  for i, msg in enumerate(t.chat_messages_sent, start=1):
    print(f"[{seat.name}] chat#{i}: {msg!r}")
  for v in t.vote_advisories:
    print(
      f"[{seat.name}] vote@meeting{v['meeting']}: "
      f"target={v['target']!r} reason={v['reason']!r}"
    )
  if t.frames_received == 0 and t.error is None:
    print(
      f"[{seat.name}] WARNING: connected but received zero frames. Common causes:\n"
      f"  * Player name '{seat.name}' is already in use server-side "
      "(prior socket not yet GC'd, or another bot has it).\n"
      "    -> Pass --name <unique> or just rerun (default name embeds pid).\n"
      "  * Server is mid-match and you were demoted to spectator.\n"
      "    -> Wait for the current match to end, or restart the server.\n"
      "  * minPlayers not met yet — the lobby is collecting players.\n"
      "    -> Spawn more bots until minPlayers is reached, or lower it.\n"
    )


def _run_seat (args: argparse.Namespace, seat: _SeatResult) -> None:
  """Build the Agent + LiveGame for one seat and ride it to completion.

  Mutates ``seat`` in place so the caller can read results after the
  thread exits.
  """
  try:
    agent = _build_agent(args, seed=seat.seed)
    seat.modules_summary = _llm_modules_summary(agent)
    live = LiveGame(
      host=args.host,
      port=args.port,
      name=seat.name,
      max_ticks=args.max_ticks,
      connect_timeout=args.connect_timeout,
    )
    print(
      f"[{seat.name}] persona={args.persona} seed={seat.seed} -> {live.url}"
    )
    print(f"[{seat.name}] modules: {seat.modules_summary}")
    print(
      f"[{seat.name}] directives: "
      f"susp={agent.directives.suspicion_threshold:.2f}, "
      f"report={agent.directives.report_eagerness}, "
      f"chat={agent.directives.chat_tone}, "
      f"vote={agent.directives.voting_style}"
    )
    result, transcript = live.run_agent(agent)
    seat.summary = result.summary
    seat.transcript = transcript
    if transcript.error is not None:
      seat.error = transcript.error
  except Exception as exc:
    seat.error = repr(exc)
    print(f"[{seat.name}] errored: {exc!r}")


def main () -> int:
  args = parse_args()
  if args.players < 1:
    raise SystemExit("--players must be >= 1")

  use_chat, use_vote, use_inst = _resolve_llm_flags(args)
  any_llm = use_chat or use_vote or use_inst
  names = _resolve_player_names(args)

  print(
    f"[sdk] persona={args.persona} players={args.players} "
    f"target=ws://{args.host}:{args.port}/player"
  )
  print(
    "[sdk] llm: "
    f"{'on' if any_llm else 'off'} "
    f"(chat={use_chat}, vote={use_vote}, instructions={use_inst}, "
    f"model={args.model or '<default: claude-sonnet/bedrock>'})"
  )
  print(f"[sdk] seats: {names}")
  print()

  seats = [
    _SeatResult(index=i, name=name, seed=args.seed + i)
    for i, name in enumerate(names)
  ]

  # Single-player path: run inline so Ctrl+C is immediate.
  if len(seats) == 1:
    _run_seat(args, seats[0])
    print()
    _print_seat_summary(seats[0])
    return 0 if seats[0].error is None else 1

  # Multi-player path: thread per seat, staggered to avoid name-collision races.
  shutdown = threading.Event()

  def _signal_handler (sig: int, _frame: Any) -> None:
    if shutdown.is_set():
      return
    print(f"\n[signal] caught {sig}; threads will exit when their sockets close.")
    shutdown.set()

  signal.signal(signal.SIGINT, _signal_handler)
  signal.signal(signal.SIGTERM, _signal_handler)

  threads: list[threading.Thread] = []
  for seat in seats:
    t = threading.Thread(
      target=_run_seat,
      args=(args, seat),
      name=f"seat-{seat.name}",
      daemon=True,
    )
    t.start()
    threads.append(t)
    if args.stagger_ms > 0 and seat is not seats[-1]:
      time.sleep(args.stagger_ms / 1000.0)

  for t in threads:
    while t.is_alive():
      t.join(timeout=1.0)
      if shutdown.is_set():
        break

  print()
  print("=" * 60)
  print(
    f"personas_live fanout: {args.persona} x {args.players} "
    f"({sum(1 for s in seats if s.error is None)}/{len(seats)} ok)"
  )
  print("=" * 60)
  for seat in seats:
    _print_seat_summary(seat)
    print()

  return 0 if all(s.error is None for s in seats) else 1


if __name__ == "__main__":
  raise SystemExit(main())
