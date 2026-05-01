"""Offline trace writer for modulabot.

Emits structured JSONL + a session manifest that an outer-loop LLM
harness can consume to drive self-improvement on the policy code. See
``/Users/jamesboggs/coding/bitworld/among_them/players/modulabot/TRACING.md``
for the full Nim design spec; this module ships a deliberately small
Python v1 covering that doc's Phase 1 equivalent. Gaps vs. the Nim
implementation are documented under :ref:`scope`.

Design goals (inherited from the Nim design):

1. **Decision-grounded.** Every policy branch's ``bot.fired("<id>")``
   transition produces a line that names both the source branch and the
   mask emitted. No guessing at why a frame returned a given action.
2. **Self-experience only.** All fields are read from ``Bot`` state
   post-``step``; we never peek at server ground truth.
3. **Non-perturbing.** The writer never mutates ``Bot``. If it raises,
   we catch and disable further output for the session rather than
   taking the bot down. Verified by tests that compare trace-on vs.
   trace-off action sequences.
4. **Compact.** Events use sparse, edge-triggered diffs from a per-agent
   shadow record; decisions emit only on ``branch_id`` changes.
5. **LLM-friendly.** Action names, phase names, role names are spelled
   out. No raw masks, no sprite scores, no packed bytes.

.. _scope:

Scope vs. the Nim trace
-----------------------

v1 ships:

- Manifest per session (not per round). The Python bot has no stable
  way to detect round boundaries from the cogames observation stream
  yet — the harness can segment by ``phase_change`` events instead.
- Events: ``session_start``, ``role_known``, ``self_color_known``,
  ``phase_change``, ``kill_cooldown_ready``, ``kill_cooldown_used``,
  ``kill_executed``, ``body_seen_first``, ``vote_cast``, ``chat_sent``.
- Decisions: branch-transition stream at level
  :attr:`TraceLevel.DECISIONS`.
- Two log levels: :attr:`TraceLevel.EVENTS` (events only) and
  :attr:`TraceLevel.DECISIONS` (events + decisions).

Explicitly out of scope for v1:

- ``snapshots.jsonl`` periodic belief dumps.
- Per-round directories (``round-0000/``).
- Frames-dump capture and deterministic replay.
- Chat-observed OCR diffing (pixel-perception side isn't in yet).
- Schema validator script.

Usage
-----

Construct a :class:`TraceWriter` and pass it to the policy::

    from modulabot import AmongThemPolicy

    policy = AmongThemPolicy(
        policy_env_info,
        trace_dir="/tmp/modulabot_runs",
        trace_level="decisions",
        trace_meta={"experiment_id": "baseline"},
    )

Or opt in via environment variables (useful for tournament workers
and shell-driven experiments)::

    export MODULABOT_TRACE_DIR=/tmp/modulabot_runs
    export MODULABOT_TRACE_LEVEL=decisions
    export MODULABOT_TRACE_META=experiment_id=baseline,git_sha=abc1234

Reading the output::

    import glob, json
    for path in glob.glob("/tmp/modulabot_runs/*/*/agent_*/events.jsonl"):
        for line in open(path):
            event = json.loads(line)
            ...
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional, TextIO

from .state import Bot, Phase, Role

_logger = logging.getLogger("modulabot.trace")


#: Match radius (pixels) used to dedupe body sightings across frames.
#: Sprite-matching anchors drift by 0-2 pixels between frames; anything
#: within this radius with the same colour index is treated as the same
#: body, not a new ``body_seen_first`` event.
_BODY_DEDUP_RADIUS = 4


# ---------------------------------------------------------------------------
# Public configuration types
# ---------------------------------------------------------------------------


class TraceLevel(IntEnum):
    """How much detail to emit.

    :attr:`OFF` disables tracing entirely and is the default when no
    ``trace_dir`` is configured. :attr:`EVENTS` emits only the sparse
    edge-triggered event stream. :attr:`DECISIONS` adds per-branch
    decision lines.
    """

    OFF = 0
    EVENTS = 1
    DECISIONS = 2

    @classmethod
    def parse(cls, value: "str | int | TraceLevel | None") -> "TraceLevel":
        """Accept any of: enum member, int, string ``"off"``/``"events"``/``"decisions"``.

        Unknown strings raise :class:`ValueError`.
        """
        if value is None:
            return cls.OFF
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        key = str(value).strip().lower()
        if key in ("off", "none", "disabled", ""):
            return cls.OFF
        if key in ("events", "event"):
            return cls.EVENTS
        if key in ("decisions", "decision"):
            return cls.DECISIONS
        raise ValueError(f"unknown trace level {value!r}")


def parse_meta(value: "str | dict | None") -> dict[str, str]:
    """Parse a ``"k=v,k=v"`` string (or dict) into a dict.

    Used for the ``trace_meta`` kwarg and the ``MODULABOT_TRACE_META``
    environment variable. Ignores empty segments. Raises
    :class:`ValueError` on a segment without ``=``.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    out: dict[str, str] = {}
    for seg in str(value).split(","):
        seg = seg.strip()
        if not seg:
            continue
        if "=" not in seg:
            raise ValueError(f"trace_meta segment {seg!r} missing '='")
        k, v = seg.split("=", 1)
        out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------------------
# Per-agent shadow state (for diff detection)
# ---------------------------------------------------------------------------


@dataclass
class _AgentShadow:
    """Last-frame snapshot of the fields we diff events from.

    Lives entirely on the writer side; never copied back into ``Bot``,
    which preserves the non-perturbation invariant.
    """

    initialised: bool = False
    role: Role = Role.UNKNOWN
    self_color: int = -1
    phase: Phase = Phase.UNKNOWN
    kill_ready: bool = False
    last_kill_tick: int = -1
    voted: bool = False
    body_positions: tuple[tuple[int, int, int], ...] = ()
    branch_id: str = ""
    branch_enter_tick: int = 0
    branch_enter_wall_ms: int = 0
    # File handles for this agent (lazily created).
    events_fp: Optional[TextIO] = None
    decisions_fp: Optional[TextIO] = None
    # Per-agent counters for the manifest.
    ticks_total: int = 0
    branch_transitions: int = 0
    events_emitted: int = 0
    kills_executed: int = 0
    votes_cast: int = 0
    chats_sent: int = 0
    bodies_seen_first: int = 0


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _session_id(pid: int, when: Optional[datetime] = None) -> str:
    """Filesystem-safe ISO8601 session id + pid.

    Uses UTC, drops microseconds, replaces ``:`` with ``-`` (invalid on
    Windows). Matches the Nim convention from ``TRACING.md §5``.
    """
    when = when or datetime.now(timezone.utc)
    iso = when.replace(microsecond=0).isoformat().replace("+00:00", "Z").replace(":", "-")
    return f"{iso}-{pid}"


class TraceWriter:
    """Append-only structured trace sink for one modulabot session.

    One writer serves all agents in a batch; each agent gets its own
    subdirectory with ``events.jsonl`` and ``decisions.jsonl``. The
    session-level ``manifest.json`` is written at construction and
    rewritten with rolled-up counters on :meth:`close`.

    All I/O is synchronous. The manifest's ``ended_reason`` is only
    populated after :meth:`close`; if the process is SIGKILLed, the
    manifest will still exist but with ``ended_reason = "open"``.

    The writer is **not** thread-safe. Callers must serialise access,
    which is natural inside :meth:`modulabot.policy.AmongThemPolicy.
    step_batch` — one writer, called from one thread.
    """

    #: Schema version stamped into every manifest. Bump on breaking
    #: shape changes so outer-loop readers can reject old data cleanly.
    SCHEMA_VERSION = 1

    def __init__(
        self,
        root_dir: str | os.PathLike,
        *,
        level: "TraceLevel | str | int" = TraceLevel.DECISIONS,
        bot_name: str = "modulabot",
        meta: "dict | str | None" = None,
        session_id: Optional[str] = None,
        clock: Optional[object] = None,
    ) -> None:
        self.level = TraceLevel.parse(level)
        self.bot_name = bot_name
        self.meta = parse_meta(meta)
        self._clock = clock or time.monotonic
        self._start_monotonic = float(self._clock())
        self._start_unix_ms = int(time.time() * 1000)
        self.session_id = session_id or _session_id(os.getpid())

        self._session_dir = Path(root_dir) / bot_name / self.session_id
        self._agents: dict[int, _AgentShadow] = {}
        self._closed = False
        self._disabled_reason: str | None = None

        try:
            self._session_dir.mkdir(parents=True, exist_ok=True)
            self._write_manifest(ended_reason="open")
        except OSError as exc:
            self._disable(f"could not create trace directory: {exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True when the writer is still accepting frames.

        False after :meth:`close`, or after any disk error disabled the
        writer mid-session.
        """
        return not self._closed and self._disabled_reason is None and self.level != TraceLevel.OFF

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    def record_frame(self, bot: Bot, action: int) -> None:
        """Diff ``bot`` against its shadow, emit events + decisions.

        Call once per agent per tick, *after* ``BotCore.step`` has
        returned — ``bot.diag.branch_id`` and ``bot.tick`` must already
        reflect the just-completed frame.

        Swallows any I/O error and disables the writer for the rest of
        the session. This keeps the bot alive at the cost of a
        truncated trace, which matches the Nim non-perturbation
        invariant.
        """
        if not self.enabled:
            return
        try:
            self._record_frame_inner(bot, action)
        except Exception as exc:  # pragma: no cover — defensive
            self._disable(f"record_frame failed: {exc!r}")

    def record_chat_sent(self, agent_id: int, text: str, tick: int) -> None:
        """Emit a ``chat_sent`` event for one agent.

        Called from :class:`~modulabot.policy.AmongThemPolicy` when a
        queued chat line is flushed. Safe to call before the first
        :meth:`record_frame` for this agent — shadow state will be
        lazily initialised.
        """
        if not self.enabled:
            return
        try:
            shadow = self._shadow(agent_id)
            shadow.chats_sent += 1
            self._emit_event(
                agent_id,
                shadow,
                tick=tick,
                type="chat_sent",
                payload={"text": text, "length": len(text)},
            )
        except Exception as exc:  # pragma: no cover — defensive
            self._disable(f"record_chat_sent failed: {exc!r}")

    def close(self, *, reason: str = "session_end") -> None:
        """Flush pending I/O and rewrite the manifest with final counters.

        Idempotent: subsequent calls after the first return immediately.
        ``reason`` is recorded as ``ended_reason`` in the manifest.
        Typical values: ``"session_end"`` (default), ``"process_exit"``,
        ``"disconnect"``.
        """
        if self._closed:
            return
        self._closed = True
        for shadow in self._agents.values():
            for fp in (shadow.events_fp, shadow.decisions_fp):
                if fp is not None:
                    try:
                        fp.flush()
                        fp.close()
                    except OSError:
                        pass
        if self._disabled_reason is None:
            try:
                self._write_manifest(ended_reason=reason)
            except OSError as exc:  # pragma: no cover — defensive
                _logger.warning("trace: could not finalise manifest: %s", exc)

    # Context-manager niceties so tests can `with TraceWriter(...) as t:`.
    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close(reason="exception" if exc_type is not None else "session_end")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _disable(self, reason: str) -> None:
        if self._disabled_reason is None:
            _logger.warning("trace disabled: %s", reason)
        self._disabled_reason = reason

    def _shadow(self, agent_id: int) -> _AgentShadow:
        shadow = self._agents.get(agent_id)
        if shadow is None:
            shadow = _AgentShadow()
            self._agents[agent_id] = shadow
            agent_dir = self._session_dir / f"agent_{agent_id}"
            agent_dir.mkdir(parents=True, exist_ok=True)
            shadow.events_fp = (agent_dir / "events.jsonl").open("a", buffering=1)
            if self.level >= TraceLevel.DECISIONS:
                shadow.decisions_fp = (agent_dir / "decisions.jsonl").open("a", buffering=1)
        return shadow

    def _wall_ms(self) -> int:
        return int((float(self._clock()) - self._start_monotonic) * 1000)

    def _record_frame_inner(self, bot: Bot, action: int) -> None:
        shadow = self._shadow(bot.agent_id)
        shadow.ticks_total += 1
        tick = bot.tick
        wall_ms = self._wall_ms()

        if not shadow.initialised:
            shadow.initialised = True
            # Prime shadows to "uninitialised" values so the first
            # frame's observations still produce role_known /
            # self_color_known / phase_change / kill_cooldown_ready
            # / body_seen_first events as appropriate. This matches
            # the Nim writer's behaviour where every first observation
            # is an explicit transition.
            shadow.role = Role.UNKNOWN
            shadow.self_color = -1
            shadow.phase = Phase.UNKNOWN
            shadow.kill_ready = False
            shadow.last_kill_tick = -1
            shadow.voted = False
            shadow.body_positions = ()
            shadow.branch_id = ""
            shadow.branch_enter_tick = tick
            shadow.branch_enter_wall_ms = wall_ms
            self._emit_event(
                bot.agent_id,
                shadow,
                tick=tick,
                type="session_start",
                wall_ms_override=wall_ms,
                payload={"agent_id": bot.agent_id},
            )
            # Fall through into the diff logic below so first-observation
            # transitions fire as normal events.

        # Role transition.
        if bot.role != shadow.role:
            if shadow.role == Role.UNKNOWN:
                self._emit_event(
                    bot.agent_id,
                    shadow,
                    tick=tick,
                    type="role_known",
                    wall_ms_override=wall_ms,
                    payload={"role": bot.role.name.lower()},
                )
            else:
                self._emit_event(
                    bot.agent_id,
                    shadow,
                    tick=tick,
                    type="role_changed",
                    wall_ms_override=wall_ms,
                    payload={"from": shadow.role.name.lower(), "to": bot.role.name.lower()},
                )
            shadow.role = bot.role

        # Self-colour transition (first time we learn our colour).
        if bot.identity.self_color != shadow.self_color:
            if shadow.self_color < 0 and bot.identity.self_color >= 0:
                self._emit_event(
                    bot.agent_id,
                    shadow,
                    tick=tick,
                    type="self_color_known",
                    wall_ms_override=wall_ms,
                    payload={"color_index": bot.identity.self_color},
                )
            shadow.self_color = bot.identity.self_color

        # Phase transition.
        if bot.percep.phase != shadow.phase:
            self._emit_event(
                bot.agent_id,
                shadow,
                tick=tick,
                type="phase_change",
                wall_ms_override=wall_ms,
                payload={
                    "from": shadow.phase.name.lower(),
                    "to": bot.percep.phase.name.lower(),
                },
            )
            shadow.phase = bot.percep.phase

        # Kill cooldown transitions (imposter only).
        if bot.imposter.kill_ready != shadow.kill_ready:
            kind = "kill_cooldown_ready" if bot.imposter.kill_ready else "kill_cooldown_used"
            self._emit_event(
                bot.agent_id,
                shadow,
                tick=tick,
                type=kind,
                wall_ms_override=wall_ms,
                payload={},
            )
            shadow.kill_ready = bot.imposter.kill_ready

        # Kill executed: last_kill_tick was just updated to the current tick.
        if (
            bot.imposter.last_kill_tick != shadow.last_kill_tick
            and bot.imposter.last_kill_tick >= 0
            and bot.imposter.last_kill_tick == tick
        ):
            shadow.kills_executed += 1
            self._emit_event(
                bot.agent_id,
                shadow,
                tick=tick,
                type="kill_executed",
                wall_ms_override=wall_ms,
                payload={
                    "target_pos": [bot.imposter.last_kill_x, bot.imposter.last_kill_y]
                },
            )
            shadow.last_kill_tick = bot.imposter.last_kill_tick
        else:
            shadow.last_kill_tick = bot.imposter.last_kill_tick

        # New-body discovery.
        #
        # Sprite-matching jitter drifts body anchors by ~1 pixel from
        # frame to frame, so exact-position dedup (the v0 approach)
        # inflated the counter roughly by the body's on-screen lifetime.
        # We dedupe against a small radius + colour match instead —
        # a body that appears at (66,62) this frame and (66,61) next
        # frame with the same colour is the *same body*, not a new
        # sighting.
        current_bodies = tuple(
            (int(b.x), int(b.y), int(b.color)) for b in bot.percep.bodies
        )
        dedup_radius = _BODY_DEDUP_RADIUS
        new_bodies: list[tuple[int, int, int]] = []
        for bx, by, color in current_bodies:
            seen = False
            for px, py, pc in shadow.body_positions:
                if (
                    pc == color
                    and abs(bx - px) <= dedup_radius
                    and abs(by - py) <= dedup_radius
                ):
                    seen = True
                    break
            if not seen:
                new_bodies.append((bx, by, color))
        for bx, by, color in sorted(new_bodies):
            shadow.bodies_seen_first += 1
            self._emit_event(
                bot.agent_id,
                shadow,
                tick=tick,
                type="body_seen_first",
                wall_ms_override=wall_ms,
                payload={"pos": [bx, by], "color_index": color},
            )
        shadow.body_positions = current_bodies

        # Vote-cast transition.
        if bot.voting.committed and not shadow.voted:
            shadow.votes_cast += 1
            self._emit_event(
                bot.agent_id,
                shadow,
                tick=tick,
                type="vote_cast",
                wall_ms_override=wall_ms,
                payload={"target_slot": bot.voting.target_slot},
            )
            shadow.voted = True
        elif not bot.voting.committed and shadow.voted:
            # Voting screen ended — reset for the next meeting.
            shadow.voted = False

        # Decisions (branch transitions).
        self._maybe_emit_decision(bot, shadow, action, tick, wall_ms)

    def _maybe_emit_decision(
        self,
        bot: Bot,
        shadow: _AgentShadow,
        action: int,
        tick: int,
        wall_ms: int,
    ) -> None:
        """Emit a decisions.jsonl line iff the branch changed.

        Stamps the previous branch's duration on the *new* line so
        readers can compute both edges without doubling line count (see
        Nim TRACING.md §4.3).
        """
        if self.level < TraceLevel.DECISIONS:
            return
        branch_id = bot.diag.branch_id
        if branch_id == shadow.branch_id:
            return
        prev_id = shadow.branch_id
        prev_duration = tick - shadow.branch_enter_tick if prev_id else None
        line = {
            "tick": tick,
            "wall_ms": wall_ms,
            "branch_id": branch_id,
            "intent": bot.diag.intent,
            "from": prev_id or None,
            "duration_ticks_in_prev_branch": prev_duration,
            "action": int(action),
            "role": bot.role.name.lower(),
            "phase": bot.percep.phase.name.lower(),
        }
        # Include the goal if one is set — the harness wants to know
        # *where* we were going, not just *what* branch fired.
        if bot.goal.has:
            line["goal"] = {
                "name": bot.goal.name,
                "index": bot.goal.index,
                "pos": [bot.goal.x, bot.goal.y],
            }
        self._write_line(shadow.decisions_fp, line)
        shadow.branch_transitions += 1
        shadow.branch_id = branch_id
        shadow.branch_enter_tick = tick
        shadow.branch_enter_wall_ms = wall_ms

    def _emit_event(
        self,
        agent_id: int,
        shadow: _AgentShadow,
        *,
        tick: int,
        type: str,
        payload: dict[str, Any],
        wall_ms_override: Optional[int] = None,
    ) -> None:
        wall_ms = wall_ms_override if wall_ms_override is not None else self._wall_ms()
        line: dict[str, Any] = {
            "tick": tick,
            "wall_ms": wall_ms,
            "agent_id": agent_id,
            "type": type,
        }
        line.update(payload)
        self._write_line(shadow.events_fp, line)
        shadow.events_emitted += 1

    def _write_line(self, fp: Optional[TextIO], data: dict[str, Any]) -> None:
        if fp is None:
            return
        try:
            fp.write(json.dumps(data, separators=(",", ":")) + "\n")
        except OSError as exc:  # pragma: no cover — defensive
            self._disable(f"write failed: {exc}")

    def _write_manifest(self, *, ended_reason: str) -> None:
        """Serialise the per-session manifest.

        Rewrites in place on :meth:`close`. Aggregates per-agent
        counters for a session-wide summary at the top; per-agent
        counters live under ``agents``.
        """
        now_ms = int(time.time() * 1000)
        agents_section = {}
        totals = {
            "ticks_total": 0,
            "branch_transitions": 0,
            "events_emitted": 0,
            "kills_executed": 0,
            "votes_cast": 0,
            "chats_sent": 0,
            "bodies_seen_first": 0,
        }
        for agent_id, shadow in sorted(self._agents.items()):
            counters = {
                "ticks_total": shadow.ticks_total,
                "branch_transitions": shadow.branch_transitions,
                "events_emitted": shadow.events_emitted,
                "kills_executed": shadow.kills_executed,
                "votes_cast": shadow.votes_cast,
                "chats_sent": shadow.chats_sent,
                "bodies_seen_first": shadow.bodies_seen_first,
            }
            agents_section[str(agent_id)] = {
                "role_final": shadow.role.name.lower(),
                "self_color_final": shadow.self_color,
                "phase_final": shadow.phase.name.lower(),
                "counters": counters,
            }
            for k, v in counters.items():
                totals[k] += v
        manifest = {
            "schema_version": self.SCHEMA_VERSION,
            "session_id": self.session_id,
            "bot_name": self.bot_name,
            "pid": os.getpid(),
            "started_unix_ms": self._start_unix_ms,
            "ended_unix_ms": now_ms if ended_reason != "open" else None,
            "ended_reason": ended_reason,
            "trace_settings": {
                "level": self.level.name.lower(),
                "snapshot_period_ticks": None,  # v1: no snapshots
            },
            "harness_meta": self.meta,
            "summary_counters": totals,
            "agents": agents_section,
        }
        path = self._session_dir / "manifest.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        tmp.replace(path)


# ---------------------------------------------------------------------------
# Factory helpers (policy / env wiring)
# ---------------------------------------------------------------------------


def from_env(
    *,
    trace_dir: "str | os.PathLike | None" = None,
    trace_level: "TraceLevel | str | int | None" = None,
    trace_meta: "dict | str | None" = None,
    bot_name: str = "modulabot",
) -> Optional[TraceWriter]:
    """Build a :class:`TraceWriter` from kwargs + ``MODULABOT_TRACE_*`` env vars.

    Explicit kwargs win over env vars (matches Nim §10.2 resolution
    order). Returns ``None`` when tracing is disabled — no directory
    configured, or the level resolves to :attr:`TraceLevel.OFF`. This
    is the hook the :class:`~modulabot.policy.AmongThemPolicy`
    constructor uses.

    Environment variables (all optional):

    - ``MODULABOT_TRACE_DIR``
    - ``MODULABOT_TRACE_LEVEL`` (``events`` / ``decisions``)
    - ``MODULABOT_TRACE_META`` (``k=v,k=v`` string)
    """
    resolved_dir = trace_dir if trace_dir is not None else os.environ.get("MODULABOT_TRACE_DIR")
    if not resolved_dir:
        return None
    resolved_level = TraceLevel.parse(
        trace_level if trace_level is not None else os.environ.get("MODULABOT_TRACE_LEVEL", "decisions")
    )
    if resolved_level == TraceLevel.OFF:
        return None
    resolved_meta: "dict | str | None"
    if trace_meta is not None:
        resolved_meta = trace_meta
    else:
        resolved_meta = os.environ.get("MODULABOT_TRACE_META")
    return TraceWriter(
        root_dir=resolved_dir,
        level=resolved_level,
        bot_name=bot_name,
        meta=resolved_meta,
    )


__all__ = [
    "TraceLevel",
    "TraceWriter",
    "parse_meta",
    "from_env",
]
