"""Shared utilities for Among Them play/connect/capture scripts.

Extracted from play_local.py, play_live.py, play_watch.py,
capture_frames.py, and the shell harness scripts to eliminate
duplication and provide uniform interfaces.

All play/connect scripts import from this module rather than
reimplementing server management, WebSocket loops, policy loading,
metrics collection, and frame capture independently.

Responsibilities:
    - ``button_mask_for_action``: canonical action→mask conversion
    - ``resolve_policy``: generic ``-p class=...`` policy loader
    - ``agent_loop``: threaded recv/step/send loop
    - ``capture_loop``: passive (noop) frame capture loop
    - ``start_server`` / ``spawn_fillers``: Nim process management
    - ``find_server_binary`` / ``find_filler_binary``: binary discovery
    - ``connect_agents``: multi-WebSocket connection setup
    - ``report_results`` / ``write_metrics`` / ``write_captured_frames``:
      session output
    - ``add_*_args``: standardised argparse flag groups
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import websocket

from mettagrid.bitworld import (
    BITWORLD_ACTION_MASKS,
    BITWORLD_ACTION_NAMES,
    BITWORLD_DEFAULT_FRAME_STACK,
    PACKED_FRAME_BYTES,
    pack_input_packet,
)
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.config.bitworld_config import BitWorldEnvConfig
from mettagrid.runner.bitworld_runner import (
    BitWorldRuntime,
    PlayerConnection,
    _build_bitworld_env_interface,
    _connect_websocket,
    _start_server,
    _start_server_on_free_port,
    _stack_observation,
    _unpack_frame,
)

log = logging.getLogger("among_them.scripts")


# ---------------------------------------------------------------------------
# sys.path setup
# ---------------------------------------------------------------------------


def setup_pythonpath() -> None:
    """Ensure the ``among_them/`` package root is on ``sys.path``.

    Call once at script startup so local game-level packages work
    regardless of how the script was invoked — from repo root, from
    ``scripts/``, with or without an explicit ``PYTHONPATH=among_them``.
    """
    among_them_dir = str(Path(__file__).resolve().parent.parent)
    if among_them_dir not in sys.path:
        sys.path.insert(0, among_them_dir)


# ---------------------------------------------------------------------------
# Action mask conversion
# ---------------------------------------------------------------------------


def button_mask_for_action(action: int) -> int:
    """Convert a BitWorld action index to a 7-bit button mask.

    Uses the precomputed ``BITWORLD_ACTION_MASKS`` lookup table — the
    same one ``bitworld_runner`` uses internally.  No string splitting
    or name round-trip involved.
    """
    return int(BITWORLD_ACTION_MASKS[action])


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def find_binary(
    name: str,
    *,
    cli_override: str | Path | None = None,
    env_var: str | None = None,
    extra_candidates: list[Path] | None = None,
) -> Path:
    """Locate a Nim binary (server or filler bot) on disk.

    Resolution order:

    1. Explicit CLI path (``--server-binary`` / ``--filler-binary``).
    2. Environment variable (``AMONG_THEM_BINARY``, etc.).
    3. Well-known candidate paths under ``~/coding/bitworld/out/``.
    4. Extra candidates supplied by the caller.

    Raises :class:`FileNotFoundError` if nothing is found.
    """
    if cli_override is not None:
        p = Path(cli_override)
        if p.exists():
            return p
        raise FileNotFoundError(f"Specified binary not found: {p}")

    if env_var:
        env_path = os.environ.get(env_var)
        if env_path:
            p = Path(env_path)
            if p.exists():
                return p

    candidates = [
        # In-tree build output (nimble / direct compile).
        Path.home() / "coding" / "bitworld" / "among_them" / name,
        Path.home() / "coding" / "bitworld" / "out" / name,
        Path.home() / "bitworld" / "out" / name,
        Path("/opt/bitworld/among_them") / name,
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)

    for c in candidates:
        if c.exists():
            return c

    searched = "\n  ".join(str(c) for c in candidates)
    env_hint = env_var or (name.upper() + "_BINARY")
    raise FileNotFoundError(
        f"{name} binary not found.  Set {env_hint} or place it at one of:\n  {searched}"
    )


def find_server_binary(cli_override: str | Path | None = None) -> Path:
    """Find the Among Them server binary."""
    return find_binary(
        "among_them", cli_override=cli_override, env_var="AMONG_THEM_BINARY"
    )


def find_filler_binary(cli_override: str | Path | None = None) -> Path:
    """Find the nottoodumb filler bot binary."""
    return find_binary(
        "nottoodumb", cli_override=cli_override, env_var="FILLER_BOT_BINARY"
    )


# ---------------------------------------------------------------------------
# Server + filler process management
# ---------------------------------------------------------------------------


def start_server(
    binary: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    num_players: int = 8,
    max_ticks: int = 14400,
    seed: int = 0,
    imposter_count: int = 2,
    tasks_per_player: int = 8,
    imposter_cooldown_ticks: int = 1200,
    vote_timer_ticks: int = 600,
    force_role: str | None = None,
) -> tuple[subprocess.Popen, BitWorldRuntime]:
    """Start a Nim Among Them server.

    Returns ``(process, runtime)`` where ``runtime.port`` is the actual
    port the server bound to (relevant when *port* is 0 for auto-pick).

    When *force_role* is ``"crewmate"`` or ``"imposter"``, the server's
    ``slots`` config pins slot 0 (the first connecting player) to that
    role.  This uses the server's native slot-pinning feature
    (``sim.nim:1016-1051``) — no server-side changes required.
    """
    runtime = BitWorldRuntime(binary_path=str(binary), host=host, port=port)
    server_config: dict[str, Any] = {
        "imposterCount": imposter_count,
        "tasksPerPlayer": tasks_per_player,
        "imposterCooldownTicks": imposter_cooldown_ticks,
        "voteTimerTicks": vote_timer_ticks,
    }
    if force_role is not None:
        server_config["slots"] = [{"role": force_role}]
        log.info("Forcing slot 0 role: %s", force_role)
    env = BitWorldEnvConfig(
        num_players=num_players,
        max_ticks=max_ticks,
        seed=seed,
        server_config=server_config,
    )
    if port != 0:
        # Use the specified port directly instead of auto-picking.
        runtime.port = port
        server = _start_server(binary, runtime, env)
    else:
        server = _start_server_on_free_port(binary, runtime, env)
    log.info(
        "Server running on %s:%d (pid %d)", runtime.host, runtime.port, server.pid
    )
    return server, runtime


def spawn_fillers(
    binary: Path,
    host: str,
    port: int,
    count: int,
    *,
    stagger: float = 0.1,
) -> list[subprocess.Popen]:
    """Spawn *count* nottoodumb filler bots connecting to the server.

    Each bot is staggered by *stagger* seconds so the server can
    process join handshakes sequentially.  Returns the process handles.
    """
    procs: list[subprocess.Popen] = []
    for i in range(count):
        p = subprocess.Popen(
            [
                str(binary),
                f"--address:{host}",
                f"--port:{port}",
                f"--name:f{i + 1}",
            ],
            cwd=str(binary.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(p)
        if i < count - 1:
            time.sleep(stagger)
    log.info("Spawned %d filler bot(s)", count)
    return procs


# ---------------------------------------------------------------------------
# Process cleanup
# ---------------------------------------------------------------------------


def terminate_processes(
    procs: list[subprocess.Popen],
    *,
    timeout: float = 2.0,
    label: str = "process",
) -> None:
    """TERM then KILL a list of subprocesses, with a grace period."""
    for p in procs:
        try:
            p.terminate()
        except OSError:
            pass
    deadline = time.monotonic() + timeout
    for p in procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                p.kill()
                p.wait(timeout=1)
            except Exception:
                log.warning("Failed to kill %s pid %d", label, p.pid)


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def resolve_policy(
    class_path: str,
    env_info: PolicyEnvInterface,
    *,
    policy_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Import and instantiate a policy from a dotted class path.

    Args:
        class_path: ``module.ClassName``, e.g.
            ``guided_bot.cogames.amongthem_policy.AmongThemPolicy``.
        env_info: The :class:`PolicyEnvInterface` passed to the
            constructor as the first positional argument.
        policy_kwargs: Extra keyword arguments.  String values from
            the CLI are coerced via :func:`json.loads` so ``42``
            becomes ``int``, ``true`` becomes ``bool``, and bare words
            like ``decisions`` stay as ``str``.

    Returns:
        An instantiated policy object.

    Raises:
        ImportError: Module not found.
        AttributeError: Class not found in the module.
    """
    kwargs: dict[str, Any] = {}
    if policy_kwargs:
        for key, value in policy_kwargs.items():
            kwargs[key] = _coerce_value(value)

    parts = class_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ImportError(
            f"Policy class path must be 'module.ClassName', got {class_path!r}"
        )
    module_path, class_name = parts

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)

    policy = cls(env_info, **kwargs)
    log.info("Instantiated %s.%s", module_path, class_name)
    return policy


def _coerce_value(value: str) -> Any:
    """Coerce a CLI string to a Python type via ``json.loads``.

    Falls back to the raw string if JSON parsing fails (e.g. bare
    words like ``decisions`` that aren't valid JSON literals).
    """
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def parse_policy_kwargs(raw: list[str] | None) -> dict[str, Any]:
    """Parse ``KEY=VALUE`` strings from ``--policy-kwarg`` into a dict."""
    result: dict[str, Any] = {}
    if not raw:
        return result
    for item in raw:
        if "=" not in item:
            raise argparse.ArgumentTypeError(
                f"--policy-kwarg must be KEY=VALUE, got {item!r}"
            )
        key, value = item.split("=", 1)
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Agent result container
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    """Stats collected by one agent during a session."""

    frame_count: int = 0
    action_counts: Counter = field(default_factory=Counter)
    branch_counts: Counter = field(default_factory=Counter)
    phase_counts: Counter = field(default_factory=Counter)
    metrics: list[dict] = field(default_factory=list)
    captured_frames: list[np.ndarray] = field(default_factory=list)
    elapsed: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Agent recv/step/send loop
# ---------------------------------------------------------------------------


def agent_loop(
    agent_id: int,
    player_name: str,
    ws: websocket.WebSocket,
    policy: Any,
    frame_stack: int,
    deadline: float | None,
    stop_event: threading.Event,
    *,
    capture_frames: bool = False,
    collect_metrics: bool = False,
    result: AgentResult | None = None,
) -> AgentResult:
    """WebSocket recv/step/send loop for a single agent.

    Designed to run in its own thread.  Each agent should have its own
    policy instance so there is no cross-thread contention — the only
    shared state is read-only reference data.

    Args:
        agent_id: Numeric identifier (for logging and metric rows).
        player_name: Name sent to the server.
        ws: A connected :class:`websocket.WebSocket`.
        policy: Object with a ``step_batch(obs, actions)`` method.
        frame_stack: Observation frame-stack depth.
        deadline: Monotonic-clock deadline, or ``None`` for indefinite.
        stop_event: Set this to request a clean shutdown.
        capture_frames: Store raw frames for ``.npy`` export.
        collect_metrics: Collect per-tick diagnostic dicts.
        result: Pre-allocated :class:`AgentResult`, or ``None`` to
            create one.

    Returns:
        :class:`AgentResult` with session stats.
    """
    if result is None:
        result = AgentResult()

    tag = f"agent-{agent_id}"
    conn = PlayerConnection(ws=ws, player_index=0, address=player_name)
    first_shape_logged = False
    start = time.monotonic()

    try:
        while not stop_event.is_set() and (
            deadline is None or time.monotonic() < deadline
        ):
            try:
                payload = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:
                log.info("[%s] WebSocket closed: %s", tag, exc)
                break

            if not isinstance(payload, (bytes, bytearray)):
                continue
            if len(payload) != PACKED_FRAME_BYTES:
                continue

            obs = _stack_observation(conn, payload, frame_stack)
            if not first_shape_logged:
                log.info(
                    "[%s] First obs: shape=%s dtype=%s min=%d max=%d",
                    tag,
                    obs.shape,
                    obs.dtype,
                    int(obs.min()),
                    int(obs.max()),
                )
                first_shape_logged = True

            if capture_frames:
                result.captured_frames.append(obs[-1].copy())

            # Policy expects a batch axis: (1, frame_stack, H, W).
            batch_obs = obs[np.newaxis]
            actions_out = np.zeros(1, dtype=np.int32)
            policy.step_batch(batch_obs, actions_out)

            action_index = int(actions_out[0])
            result.action_counts[action_index] += 1

            # Collect diagnostics from modulabot-style policies that
            # expose _cores.  Gracefully skip for other policies.
            if hasattr(policy, "_cores") and 0 in policy._cores:
                bot = policy._cores[0].bot
                result.branch_counts[bot.diag.branch_id or "(empty)"] += 1
                result.phase_counts[bot.percep.phase.name] += 1

                if collect_metrics:
                    m = bot.motion
                    result.metrics.append(
                        {
                            "agent_id": agent_id,
                            "tick": bot.tick,
                            "phase": bot.percep.phase.name,
                            "role": bot.role.name,
                            "localized": bool(bot.percep.localized),
                            "camera_x": bot.percep.camera_x,
                            "camera_y": bot.percep.camera_y,
                            "velocity_x": m.velocity_x,
                            "velocity_y": m.velocity_y,
                            "stuck_ticks": m.stuck_ticks,
                            "jiggle_ticks": m.jiggle_ticks,
                            "goal_has": bool(bot.goal.has),
                            "action": action_index,
                            "action_name": BITWORLD_ACTION_NAMES[action_index],
                            "branch_id": bot.diag.branch_id,
                        }
                    )

            # Send action to server.
            mask = button_mask_for_action(action_index)
            try:
                ws.send(
                    pack_input_packet(mask), opcode=websocket.ABNF.OPCODE_BINARY
                )
            except Exception as exc:
                log.info("[%s] Send failed: %s", tag, exc)
                break

            # Flush chat output (modulabot-specific; no-op for others).
            if hasattr(policy, "last_chat"):
                chat_text = policy.last_chat(0)
                if chat_text:
                    log.info("[%s] chat queued: %r", tag, chat_text)

            result.frame_count += 1
    except Exception as exc:
        result.error = str(exc)
        log.error("[%s] Unhandled error: %s", tag, exc, exc_info=True)
    finally:
        result.elapsed = time.monotonic() - start
        try:
            ws.close()
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Passive capture loop (noop policy)
# ---------------------------------------------------------------------------


def capture_loop(
    ws: websocket.WebSocket,
    deadline: float,
    stop_event: threading.Event | None = None,
) -> list[np.ndarray]:
    """Receive frames and send noops.  Returns raw ``(128, 128)`` frames.

    Used by ``capture.py`` for passive frame recording without any
    policy.
    """
    frames: list[np.ndarray] = []
    while (stop_event is None or not stop_event.is_set()) and time.monotonic() < deadline:
        try:
            payload = ws.recv()
        except Exception as exc:
            log.info("WebSocket closed during capture: %s", exc)
            break
        if (
            isinstance(payload, (bytes, bytearray))
            and len(payload) == PACKED_FRAME_BYTES
        ):
            frames.append(_unpack_frame(payload))
            try:
                ws.send(
                    pack_input_packet(0), opcode=websocket.ABNF.OPCODE_BINARY
                )
            except Exception:
                break
    return frames


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_results(results: list[AgentResult], num_agents: int) -> None:
    """Print aggregated session stats to the log."""
    total_frames = sum(r.frame_count for r in results)
    total_elapsed = max((r.elapsed for r in results), default=0.0)
    log.info(
        "Session ended: %d agent(s), %d total frames, %.1fs elapsed.",
        num_agents,
        total_frames,
        total_elapsed,
    )

    for i, r in enumerate(results):
        if r.error:
            log.error("Agent %d error: %s", i, r.error)

    if total_frames == 0:
        log.warning(
            "No frames received — server may not have started the match."
        )
        return

    combined_actions: Counter[int] = Counter()
    combined_branches: Counter[str] = Counter()
    combined_phases: Counter[str] = Counter()
    for r in results:
        combined_actions.update(r.action_counts)
        combined_branches.update(r.branch_counts)
        combined_phases.update(r.phase_counts)

    if num_agents > 1:
        for i, r in enumerate(results):
            if r.frame_count == 0:
                log.info("Agent %d: 0 frames", i)
                continue
            top = r.action_counts.most_common(3)
            top_str = ", ".join(
                f"{BITWORLD_ACTION_NAMES[idx]}={cnt}" for idx, cnt in top
            )
            fps = r.frame_count / r.elapsed if r.elapsed > 0 else 0
            log.info(
                "Agent %d: %d frames, %.1f fps — top actions: %s",
                i,
                r.frame_count,
                fps,
                top_str,
            )

    log.info("Action mix (top 6 of %d):", len(combined_actions))
    for idx, cnt in combined_actions.most_common(6):
        log.info(
            "  %-14s %5d  (%5.1f%%)",
            BITWORLD_ACTION_NAMES[idx],
            cnt,
            100.0 * cnt / total_frames,
        )
    if combined_branches:
        log.info("Top branch IDs (top 6):")
        for branch, cnt in combined_branches.most_common(6):
            log.info("  %-32s %5d", branch, cnt)
    if combined_phases:
        log.info("Phase distribution:")
        for phase, cnt in combined_phases.most_common():
            log.info("  %-14s %5d", phase, cnt)
    if total_elapsed > 0:
        log.info(
            "Avg throughput: %.1f total frames/s", total_frames / total_elapsed
        )


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_metrics(
    metrics_out: str | Path, results: list[AgentResult]
) -> None:
    """Merge all agent metrics into a single JSONL file, sorted by tick."""
    all_metrics = []
    for r in results:
        all_metrics.extend(r.metrics)
    if not all_metrics:
        return
    all_metrics.sort(key=lambda row: (row["tick"], row["agent_id"]))
    out = Path(metrics_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for row in all_metrics:
            f.write(json.dumps(row) + "\n")
    log.info("Wrote %d metric rows to %s", len(all_metrics), out)


def write_captured_frames(
    capture_path: str | Path,
    results: list[AgentResult],
    num_agents: int,
) -> None:
    """Write per-agent ``.npy`` frame dumps.

    Single-agent runs use the path as-is; multi-agent runs append a
    ``-<i>`` suffix before the extension.
    """
    base = Path(capture_path)
    for i, r in enumerate(results):
        if not r.captured_frames:
            continue
        out = base.with_stem(base.stem + f"-{i}") if num_agents > 1 else base
        out.parent.mkdir(parents=True, exist_ok=True)
        arr = np.stack(r.captured_frames, axis=0).astype(np.uint8)
        np.save(out, arr)
        log.info(
            "Agent %d: wrote %d frames to %s (%.1f MB)",
            i,
            arr.shape[0],
            out,
            arr.nbytes / 1e6,
        )


# ---------------------------------------------------------------------------
# Trace setup
# ---------------------------------------------------------------------------


def setup_trace_env(
    trace_dir: str | None, trace_level: str = "decisions"
) -> None:
    """Set trace env vars for both modulabot and guided_bot from CLI flags.

    Both ``MODULABOT_TRACE_DIR`` / ``MODULABOT_TRACE_LEVEL`` and
    ``GUIDED_BOT_TRACE_DIR`` / ``GUIDED_BOT_TRACE_LEVEL`` are set so
    that either policy type picks up the trace config. Each bot
    implementation generates unique session subdirectories internally,
    so sharing the same root directory is safe.
    """
    if trace_dir:
        os.environ["MODULABOT_TRACE_DIR"] = trace_dir
        os.environ["MODULABOT_TRACE_LEVEL"] = trace_level
        os.environ["GUIDED_BOT_TRACE_DIR"] = trace_dir
        os.environ["GUIDED_BOT_TRACE_LEVEL"] = trace_level
        log.info("Trace enabled: %s (level=%s)", trace_dir, trace_level)


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def install_stop_handler(stop_event: threading.Event) -> None:
    """Install SIGINT/SIGTERM handlers that set the given event."""

    def _handler(signum, _frame):
        log.info("Received signal %s, shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


# ---------------------------------------------------------------------------
# WebSocket connection helpers
# ---------------------------------------------------------------------------


def connect_agents(
    host: str,
    port: int,
    name_base: str,
    num_agents: int,
    *,
    connect_timeout: float = 10.0,
    stagger: float = 0.15,
) -> list[tuple[int, str, websocket.WebSocket]]:
    """Connect *num_agents* WebSocket clients to an existing server.

    Returns ``[(agent_id, player_name, ws), ...]``.  On failure, all
    previously-opened sockets are closed before the exception propagates.
    """
    config = BitWorldRuntime(host=host, port=port)
    connections: list[tuple[int, str, websocket.WebSocket]] = []

    for i in range(num_agents):
        pname = name_base if num_agents == 1 else f"{name_base}{i}"
        log.info(
            "Connecting agent %d as '%s' to ws://%s:%d...",
            i,
            pname,
            host,
            port,
        )
        try:
            ws = _connect_websocket(
                config, "/player", pname, player_name=pname,
                connect_timeout_s=connect_timeout,
            )
        except ConnectionError as exc:
            log.error("Failed to connect agent %d: %s", i, exc)
            for _, _, prev_ws in connections:
                try:
                    prev_ws.close()
                except Exception:
                    pass
            raise
        connections.append((i, pname, ws))
        if i < num_agents - 1:
            time.sleep(stagger)

    log.info("All %d agent(s) connected.", num_agents)
    return connections


# ---------------------------------------------------------------------------
# Env info builder
# ---------------------------------------------------------------------------


def build_env_info(
    frame_stack: int = BITWORLD_DEFAULT_FRAME_STACK,
    num_agents: int = 1,
) -> PolicyEnvInterface:
    """Build the standard PolicyEnvInterface for Among Them.

    Thin wrapper so scripts import from ``_lib`` instead of reaching
    into the private ``bitworld_runner`` helpers directly.
    """
    return _build_bitworld_env_interface(
        frame_stack=frame_stack, num_agents=num_agents
    )


# ---------------------------------------------------------------------------
# Standard argparse flag groups
# ---------------------------------------------------------------------------


def add_server_args(parser: argparse.ArgumentParser) -> None:
    """Add flags for scripts that start a server."""
    parser.add_argument(
        "--server-binary",
        default=None,
        help="Path to the among_them server binary (auto-detect if omitted).",
    )
    parser.add_argument(
        "--filler-binary",
        default=None,
        help="Path to the nottoodumb filler bot binary (auto-detect if omitted).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=2000,
        help="Server port (default: 2000).",
    )
    parser.add_argument(
        "--num-players",
        type=int,
        default=8,
        help="Total lobby size (server config).",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="Server tick cap.  Derived from --duration if omitted.",
    )
    parser.add_argument(
        "--imposter-count",
        type=int,
        default=2,
        help="Number of imposters (server config).",
    )
    parser.add_argument(
        "--imposter-cooldown-ticks",
        type=int,
        default=1200,
        help="Imposter kill cooldown in server ticks (default: 1200).",
    )
    parser.add_argument(
        "--tasks-per-player",
        type=int,
        default=8,
        help="Number of tasks assigned to each crewmate (default: 8).",
    )
    parser.add_argument(
        "--force-role",
        choices=("crewmate", "imposter"),
        default=None,
        help=(
            "Pin the first player slot to this role via the server's "
            "slots config. Useful for testing imposter-specific behavior."
        ),
    )


def add_client_args(parser: argparse.ArgumentParser) -> None:
    """Add flags for scripts that connect to a server."""
    parser.add_argument("--host", default="127.0.0.1", help="Server host.")
    parser.add_argument("--port", type=int, default=2000, help="Server port.")
    parser.add_argument(
        "--num-agents",
        type=int,
        default=1,
        help="Number of agent connections.",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Player name base.  Derived from policy class if omitted.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=10.0,
        help="WebSocket connect timeout in seconds.",
    )


def add_policy_args(parser: argparse.ArgumentParser) -> None:
    """Add policy selection flags."""
    parser.add_argument(
        "-p",
        "--policy",
        # Legacy default retained for modulabot-only overlay scripts that
        # introspect policy internals. Current Among Them work should always
        # pass guided_bot explicitly.
        default="modulabot.policy.AmongThemPolicy",
        help=(
            "Policy class path. Legacy default is deprecated; pass "
            "guided_bot.cogames.amongthem_policy.AmongThemPolicy for "
            "current work."
        ),
    )
    parser.add_argument(
        "--policy-kwarg",
        action="append",
        default=None,
        help="Policy constructor kwarg as KEY=VALUE (repeatable).",
    )


def add_session_args(parser: argparse.ArgumentParser) -> None:
    """Add session-control flags common to all play scripts."""
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Wall-clock seconds of play.  0 = indefinite.",
    )
    parser.add_argument(
        "--frame-stack",
        type=int,
        default=BITWORLD_DEFAULT_FRAME_STACK,
        help="Observation frame-stack depth.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Policy RNG seed.  Agent i gets seed + i.",
    )


def add_output_args(parser: argparse.ArgumentParser) -> None:
    """Add output / trace / capture flags."""
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Trace output directory (sets guided_bot and legacy modulabot trace env vars).",
    )
    parser.add_argument(
        "--trace-level",
        default="decisions",
        choices=("off", "events", "decisions", "full"),
        help="Trace verbosity (full includes raw frame recording).",
    )
    parser.add_argument(
        "--metrics-out",
        default=None,
        help="Per-tick JSONL metrics path.",
    )
    parser.add_argument(
        "--capture-frames",
        default=None,
        help="Frame .npy capture path.",
    )


# ---------------------------------------------------------------------------
# Derived-value helpers
# ---------------------------------------------------------------------------


def derive_max_ticks(args: argparse.Namespace) -> int:
    """Compute ``max_ticks`` from the explicit flag or ``--duration``.

    Uses ``duration * 24 * 2`` (24 ticks/sec with a 2x safety margin),
    matching the formula the old shell scripts used.
    """
    if getattr(args, "max_ticks", None) is not None:
        return args.max_ticks
    if getattr(args, "duration", 0) > 0:
        return int(args.duration * 24 * 2)
    # Fallback: 5 minutes.
    return 14400


def derive_player_name(args: argparse.Namespace) -> str:
    """Derive a short player name from ``--name`` or the policy class path.

    Shorter names produce smaller on-screen nameplates, which reduces
    the number of non-map pixels the localizer must ignore.  When no
    explicit ``--name`` is given, we abbreviate the policy class to a
    compact tag (e.g. ``AmongThemPolicy`` → ``gb`` for guided_bot,
    ``mb`` for modulabot, else first 2 chars of the class name).
    """
    name = getattr(args, "name", None)
    if name:
        return name
    policy = getattr(args, "policy", None) or ""
    cls = policy.rsplit(".", 1)[-1].lower() if policy else ""
    # Well-known abbreviations for common policies.
    if "guided" in policy.lower():
        return "gb"
    if "modulabot" in policy.lower():
        return "mb"
    # Fallback: first 2 chars of the class name, or a single letter.
    if cls:
        return cls[:2]
    return "p"
