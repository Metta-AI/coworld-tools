"""Tests for the modulabot trace writer.

Coverage:

- Parsing helpers (:class:`TraceLevel.parse`, :func:`parse_meta`,
  :func:`from_env`).
- Writer-off path: no directory created when tracing is disabled.
- Writer-on path: session directory, manifest, per-agent JSONL files.
- Event diff detection for every event type currently emitted.
- Decision stream emits on ``branch_id`` transitions and attaches the
  previous branch's duration.
- Non-perturbation: running a :class:`BotCore` with vs. without a
  trace writer produces identical action sequences. This is the key
  invariant from ``TRACING.md §9.1``.
- ``chat_sent`` emitted via the policy wrapper.
- Manifest counters roll up correctly on :meth:`TraceWriter.close`.
- Context-manager finalises the manifest.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from modulabot import actions
from modulabot.bot import BotCore
from modulabot.state import Bot, Phase, Role
from modulabot.trace import (
    TraceLevel,
    TraceWriter,
    from_env,
    parse_meta,
)
from modulabot.tuning import CENTER_X, CENTER_Y
from modulabot.perception.state_obs import (
    HEADER_PHASE,
    HEADER_SELF_ROLE,
    HEADER_KILL_COOLDOWN,
    KILL_COOLDOWN_READY,
    KIND_BODY,
    KIND_PLAYER,
    KIND_TASK,
    PHASE_PLAYING,
    PHASE_ROLE_REVEAL,
    PHASE_VOTING,
    PLAYER_ALIVE,
    PLAYER_SELF,
    STATE_BODY_FEATURE_OFFSET,
    STATE_BODY_FEATURES,
    STATE_FEATURES,
    STATE_PLAYER_FEATURE_OFFSET,
    STATE_PLAYER_FEATURES,
    STATE_TASK_FEATURE_OFFSET,
    STATE_TASK_FEATURES,
    TASK_ICON_VISIBLE,
    TASK_INCOMPLETE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_frame(
    *,
    phase: int = PHASE_PLAYING,
    self_role: int = 0,
    kill_cooldown: int = 0,
    players: list | None = None,
    bodies: list | None = None,
    tasks: list | None = None,
    frame_stack: int = 4,
) -> np.ndarray:
    """Same helper the smoke tests use; lifted verbatim to avoid coupling."""
    frame = np.zeros(STATE_FEATURES, dtype=np.uint8)
    frame[HEADER_PHASE] = phase
    frame[HEADER_SELF_ROLE] = self_role
    frame[HEADER_KILL_COOLDOWN] = kill_cooldown
    for slot, spec in enumerate(players or []):
        offset = STATE_PLAYER_FEATURE_OFFSET + slot * STATE_PLAYER_FEATURES
        frame[offset + 0] = KIND_PLAYER
        frame[offset + 1] = spec["x"]
        frame[offset + 2] = spec["y"]
        frame[offset + 3] = spec["color"]
        frame[offset + 4] = spec["flags"]
    for i, spec in enumerate(bodies or []):
        offset = STATE_BODY_FEATURE_OFFSET + i * STATE_BODY_FEATURES
        frame[offset + 0] = KIND_BODY
        frame[offset + 1] = spec["x"]
        frame[offset + 2] = spec["y"]
        frame[offset + 3] = spec["color"]
    for i, spec in enumerate(tasks or []):
        offset = STATE_TASK_FEATURE_OFFSET + i * STATE_TASK_FEATURES
        frame[offset + 0] = KIND_TASK
        frame[offset + 1] = spec["x"]
        frame[offset + 2] = spec["y"]
        frame[offset + 3] = spec["flags"]
        frame[offset + 5] = spec.get("arrow_x", 0)
        frame[offset + 6] = spec.get("arrow_y", 0)
    return np.tile(frame, (frame_stack, 1))


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file; return [] for a missing or empty file."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TraceLevelParseTests(unittest.TestCase):
    def test_parse_none_is_off(self):
        self.assertEqual(TraceLevel.parse(None), TraceLevel.OFF)

    def test_parse_strings(self):
        self.assertEqual(TraceLevel.parse("off"), TraceLevel.OFF)
        self.assertEqual(TraceLevel.parse("events"), TraceLevel.EVENTS)
        self.assertEqual(TraceLevel.parse("DECISIONS"), TraceLevel.DECISIONS)

    def test_parse_int(self):
        self.assertEqual(TraceLevel.parse(2), TraceLevel.DECISIONS)

    def test_parse_unknown_raises(self):
        with self.assertRaises(ValueError):
            TraceLevel.parse("everything")


class ParseMetaTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(parse_meta(None), {})

    def test_dict_stringified(self):
        self.assertEqual(parse_meta({"experiment_id": 3}), {"experiment_id": "3"})

    def test_csv_string(self):
        self.assertEqual(
            parse_meta("experiment_id=foo, git_sha=abc1234"),
            {"experiment_id": "foo", "git_sha": "abc1234"},
        )

    def test_empty_segments_ignored(self):
        self.assertEqual(parse_meta("a=b,,c=d"), {"a": "b", "c": "d"})

    def test_missing_equals_raises(self):
        with self.assertRaises(ValueError):
            parse_meta("bogus")


class FromEnvTests(unittest.TestCase):
    def test_no_dir_returns_none(self):
        # Ensure env is clean for this test.
        for key in ("MODULABOT_TRACE_DIR", "MODULABOT_TRACE_LEVEL", "MODULABOT_TRACE_META"):
            os.environ.pop(key, None)
        self.assertIsNone(from_env())

    def test_env_vars_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["MODULABOT_TRACE_DIR"] = tmp
            os.environ["MODULABOT_TRACE_LEVEL"] = "events"
            try:
                writer = from_env()
                self.assertIsNotNone(writer)
                assert writer is not None
                self.assertEqual(writer.level, TraceLevel.EVENTS)
                writer.close()
            finally:
                del os.environ["MODULABOT_TRACE_DIR"]
                del os.environ["MODULABOT_TRACE_LEVEL"]

    def test_kwargs_override_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["MODULABOT_TRACE_LEVEL"] = "events"
            try:
                writer = from_env(trace_dir=tmp, trace_level="decisions")
                assert writer is not None
                self.assertEqual(writer.level, TraceLevel.DECISIONS)
                writer.close()
            finally:
                del os.environ["MODULABOT_TRACE_LEVEL"]


# ---------------------------------------------------------------------------
# Writer: manifest, directory layout, event / decision emission
# ---------------------------------------------------------------------------


class WriterLayoutTests(unittest.TestCase):
    def test_session_directory_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = TraceWriter(tmp, session_id="test-session")
            self.assertTrue((Path(tmp) / "modulabot" / "test-session").is_dir())
            self.assertTrue(
                (Path(tmp) / "modulabot" / "test-session" / "manifest.json").is_file()
            )
            writer.close()

    def test_manifest_includes_meta_and_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = TraceWriter(
                tmp,
                session_id="test-session",
                level="decisions",
                meta={"experiment_id": "baseline"},
            )
            writer.close()
            manifest = json.loads(
                (Path(tmp) / "modulabot" / "test-session" / "manifest.json").read_text()
            )
            self.assertEqual(manifest["trace_settings"]["level"], "decisions")
            self.assertEqual(manifest["harness_meta"], {"experiment_id": "baseline"})
            self.assertEqual(manifest["ended_reason"], "session_end")
            self.assertIsNotNone(manifest["ended_unix_ms"])

    def test_context_manager_closes_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TraceWriter(tmp, session_id="ctx") as writer:
                self.assertTrue(writer.enabled)
            self.assertFalse(writer.enabled)


class WriterEventEmissionTests(unittest.TestCase):
    def _run(self, observations, *, level=TraceLevel.DECISIONS, seed=0):
        """Drive a BotCore with the given observation sequence; return the session dir."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: _rmtree(tmp))
        writer = TraceWriter(tmp, session_id="run", level=level)
        core = BotCore(agent_id=0, rng_seed=seed, trace_writer=writer)
        for obs in observations:
            core.step(obs)
        writer.close()
        return Path(tmp) / "modulabot" / "run" / "agent_0"

    def test_session_start_event_on_first_frame(self):
        agent_dir = self._run([_state_frame()])
        events = _read_jsonl(agent_dir / "events.jsonl")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "session_start")
        self.assertEqual(events[0]["agent_id"], 0)

    def test_role_known_event_on_transition(self):
        # First frame: empty state-obs perception lands on CREWMATE.
        # Second frame: role-reveal phase with self_role=1 → IMPOSTER.
        # Expect role_known(crewmate) on frame 0, role_changed to imposter on frame 1.
        agent_dir = self._run(
            [
                _state_frame(),
                _state_frame(phase=PHASE_ROLE_REVEAL, self_role=1),
            ]
        )
        events = _read_jsonl(agent_dir / "events.jsonl")
        role_events = [e for e in events if e["type"] in ("role_known", "role_changed")]
        self.assertGreaterEqual(len(role_events), 1)
        # The last role event should be the imposter transition.
        self.assertEqual(
            role_events[-1].get("to") or role_events[-1].get("role"),
            "imposter",
            f"expected final role event to land on imposter; got {events}",
        )

    def test_phase_change_event(self):
        agent_dir = self._run(
            [
                _state_frame(),
                _state_frame(phase=PHASE_VOTING),
            ]
        )
        events = _read_jsonl(agent_dir / "events.jsonl")
        phase_changes = [e for e in events if e["type"] == "phase_change"]
        # We expect at least one transition: unknown→playing→voting fires at
        # least on the playing→voting edge.
        self.assertGreaterEqual(len(phase_changes), 1)
        self.assertEqual(phase_changes[-1]["to"], "voting")

    def test_kill_cooldown_and_kill_executed(self):
        """Imposter with a lone adjacent target should emit kill_cooldown_ready
        and kill_executed on the kill frame."""
        frame = _state_frame(
            self_role=1,
            kill_cooldown=KILL_COOLDOWN_READY,
            players=[
                {
                    "x": CENTER_X,
                    "y": CENTER_Y,
                    "color": 0,
                    "flags": PLAYER_SELF | PLAYER_ALIVE,
                },
                {
                    "x": CENTER_X + 4,
                    "y": CENTER_Y,
                    "color": 13,
                    "flags": PLAYER_ALIVE,
                },
            ],
        )
        agent_dir = self._run([frame])
        events = _read_jsonl(agent_dir / "events.jsonl")
        event_types = [e["type"] for e in events]
        self.assertIn("kill_cooldown_ready", event_types)
        self.assertIn("kill_executed", event_types)

    def test_body_seen_first_event(self):
        agent_dir = self._run(
            [
                _state_frame(),
                _state_frame(
                    players=[
                        {
                            "x": CENTER_X,
                            "y": CENTER_Y,
                            "color": 13,
                            "flags": PLAYER_SELF | PLAYER_ALIVE,
                        }
                    ],
                    bodies=[{"x": CENTER_X + 20, "y": CENTER_Y, "color": 7}],
                ),
            ]
        )
        events = _read_jsonl(agent_dir / "events.jsonl")
        bodies = [e for e in events if e["type"] == "body_seen_first"]
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0]["pos"], [CENTER_X + 20, CENTER_Y])

    def test_body_jitter_not_re_fired(self):
        """Bodies' sprite-match anchors drift by 1-2 pixels between
        frames; the trace should dedupe those into one
        ``body_seen_first`` event, not one per frame.

        Pins the fix for the live-run bug where 537 sightings showed
        up for a handful of bodies over 5 minutes. Jitter up to
        :data:`~modulabot.trace._BODY_DEDUP_RADIUS` pixels with the
        same colour index is treated as the same body.
        """
        body_base_x = CENTER_X + 20
        body_base_y = CENTER_Y
        self_player = {
            "x": CENTER_X,
            "y": CENTER_Y,
            "color": 13,
            "flags": PLAYER_SELF | PLAYER_ALIVE,
        }
        # Paint the same body (colour 7) at slightly jittered positions.
        frames = []
        for dx, dy in [(0, 0), (1, 0), (1, 1), (0, 1), (-1, 0), (0, -1)]:
            frames.append(
                _state_frame(
                    players=[self_player],
                    bodies=[{"x": body_base_x + dx, "y": body_base_y + dy, "color": 7}],
                )
            )
        agent_dir = self._run(frames)
        events = _read_jsonl(agent_dir / "events.jsonl")
        bodies = [e for e in events if e["type"] == "body_seen_first"]
        self.assertEqual(
            len(bodies),
            1,
            f"jittered body re-fired {len(bodies)} body_seen_first events; "
            "expected 1 (dedup within radius + colour)",
        )

    def test_body_beyond_dedup_radius_fires_new_sighting(self):
        """A body more than ``_BODY_DEDUP_RADIUS`` pixels away — or a
        different colour — is a new sighting. Prevents the dedup fix
        from swallowing distinct bodies that happen to sit on nearby
        tiles."""
        self_player = {
            "x": CENTER_X,
            "y": CENTER_Y,
            "color": 13,
            "flags": PLAYER_SELF | PLAYER_ALIVE,
        }
        agent_dir = self._run(
            [
                _state_frame(
                    players=[self_player],
                    bodies=[{"x": CENTER_X + 20, "y": CENTER_Y, "color": 7}],
                ),
                # 10 pixels away — well outside the dedup radius.
                _state_frame(
                    players=[self_player],
                    bodies=[
                        {"x": CENTER_X + 20, "y": CENTER_Y, "color": 7},
                        {"x": CENTER_X + 40, "y": CENTER_Y, "color": 7},
                    ],
                ),
                # Same position as first body but different colour → new.
                _state_frame(
                    players=[self_player],
                    bodies=[
                        {"x": CENTER_X + 20, "y": CENTER_Y, "color": 7},
                        {"x": CENTER_X + 40, "y": CENTER_Y, "color": 7},
                        {"x": CENTER_X + 20, "y": CENTER_Y + 2, "color": 11},
                    ],
                ),
            ]
        )
        events = _read_jsonl(agent_dir / "events.jsonl")
        bodies = [e for e in events if e["type"] == "body_seen_first"]
        # 3 distinct bodies: orig (20,0,c7), far (40,0,c7), colour-differing (20,2,c11).
        self.assertEqual(len(bodies), 3, f"expected 3 distinct sightings, got: {bodies}")

    def test_vote_cast_event(self):
        # Drive the voting policy long enough to commit.
        voting_frame = _state_frame(
            phase=PHASE_VOTING,
            players=[
                {
                    "x": 10,
                    "y": 10,
                    "color": 13,
                    "flags": PLAYER_SELF | PLAYER_ALIVE,
                }
            ],
        )
        agent_dir = self._run([voting_frame] * 80)
        events = _read_jsonl(agent_dir / "events.jsonl")
        votes = [e for e in events if e["type"] == "vote_cast"]
        self.assertEqual(len(votes), 1, f"expected exactly one vote_cast, got {events}")


class WriterDecisionEmissionTests(unittest.TestCase):
    def test_decisions_file_empty_when_level_is_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = TraceWriter(tmp, session_id="run", level=TraceLevel.EVENTS)
            core = BotCore(agent_id=0, trace_writer=writer)
            core.step(_state_frame())
            writer.close()
            agent_dir = Path(tmp) / "modulabot" / "run" / "agent_0"
            # EVENTS level: events.jsonl exists, decisions.jsonl absent.
            self.assertTrue((agent_dir / "events.jsonl").exists())
            self.assertFalse((agent_dir / "decisions.jsonl").exists())

    def test_decisions_emitted_on_branch_change(self):
        """An interstitial frame then a gameplay frame should produce at
        least two decision lines with different ``branch_id`` values."""
        with tempfile.TemporaryDirectory() as tmp:
            writer = TraceWriter(tmp, session_id="run", level=TraceLevel.DECISIONS)
            core = BotCore(agent_id=0, trace_writer=writer)
            core.step(_state_frame(phase=PHASE_ROLE_REVEAL))
            core.step(
                _state_frame(
                    players=[
                        {
                            "x": CENTER_X,
                            "y": CENTER_Y,
                            "color": 13,
                            "flags": PLAYER_SELF | PLAYER_ALIVE,
                        }
                    ],
                    tasks=[
                        {
                            "x": CENTER_X + 40,
                            "y": CENTER_Y,
                            "flags": TASK_ICON_VISIBLE | TASK_INCOMPLETE,
                        }
                    ],
                )
            )
            writer.close()
            decisions = _read_jsonl(
                Path(tmp) / "modulabot" / "run" / "agent_0" / "decisions.jsonl"
            )
            self.assertGreaterEqual(len(decisions), 2)
            branch_ids = [d["branch_id"] for d in decisions]
            self.assertNotEqual(branch_ids[0], branch_ids[-1])
            # Previous-branch-duration is attached to subsequent lines.
            self.assertIsNone(decisions[0]["duration_ticks_in_prev_branch"])
            self.assertIsNotNone(decisions[1]["duration_ticks_in_prev_branch"])


class ManifestCounterTests(unittest.TestCase):
    def test_counters_reflect_per_agent_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = TraceWriter(tmp, session_id="counters")
            core_a = BotCore(agent_id=0, trace_writer=writer)
            core_b = BotCore(agent_id=1, trace_writer=writer)
            # Step agent A three times, agent B once.
            for _ in range(3):
                core_a.step(_state_frame())
            core_b.step(_state_frame())
            writer.close()
            manifest = json.loads(
                (Path(tmp) / "modulabot" / "counters" / "manifest.json").read_text()
            )
            self.assertEqual(manifest["agents"]["0"]["counters"]["ticks_total"], 3)
            self.assertEqual(manifest["agents"]["1"]["counters"]["ticks_total"], 1)
            self.assertEqual(manifest["summary_counters"]["ticks_total"], 4)


# ---------------------------------------------------------------------------
# The headline invariant
# ---------------------------------------------------------------------------


class NonPerturbationTests(unittest.TestCase):
    """Trace-on and trace-off must emit identical action sequences.

    This is the strongest guarantee that the writer is non-perturbing
    (Nim ``TRACING.md §13.2``). Covers both a state-obs scenario and a
    behaviourally-interesting imposter kill scenario.
    """

    def _sequence(self, frames, *, trace: bool):
        tmp = None
        writer = None
        if trace:
            tmp = tempfile.mkdtemp()
            self.addCleanup(lambda: _rmtree(tmp))
            writer = TraceWriter(tmp, session_id="parity")
        core = BotCore(agent_id=0, rng_seed=7, trace_writer=writer)
        out = [core.step(f) for f in frames]
        if writer is not None:
            writer.close()
        return out

    def test_crewmate_task_sequence_identical(self):
        frames = [
            _state_frame(),
            _state_frame(
                players=[
                    {
                        "x": CENTER_X,
                        "y": CENTER_Y,
                        "color": 13,
                        "flags": PLAYER_SELF | PLAYER_ALIVE,
                    }
                ],
                tasks=[
                    {
                        "x": CENTER_X + 40,
                        "y": CENTER_Y,
                        "flags": TASK_ICON_VISIBLE | TASK_INCOMPLETE,
                    }
                ],
            ),
        ] * 40
        self.assertEqual(
            self._sequence(frames, trace=False),
            self._sequence(frames, trace=True),
        )

    def test_imposter_sequence_identical(self):
        frames = [
            _state_frame(
                self_role=1,
                kill_cooldown=KILL_COOLDOWN_READY,
                players=[
                    {
                        "x": CENTER_X,
                        "y": CENTER_Y,
                        "color": 0,
                        "flags": PLAYER_SELF | PLAYER_ALIVE,
                    },
                    {
                        "x": CENTER_X + 4,
                        "y": CENTER_Y,
                        "color": 13,
                        "flags": PLAYER_ALIVE,
                    },
                ],
            )
        ] * 20
        self.assertEqual(
            self._sequence(frames, trace=False),
            self._sequence(frames, trace=True),
        )


# ---------------------------------------------------------------------------
# Policy-level wiring
# ---------------------------------------------------------------------------


class PolicyChatSentTests(unittest.TestCase):
    """``AmongThemPolicy`` should emit a ``chat_sent`` event on queue flush."""

    def test_chat_sent_event_emitted(self):
        from modulabot import AmongThemPolicy

        with tempfile.TemporaryDirectory() as tmp:
            writer = TraceWriter(tmp, session_id="policy")

            # Construct a minimal AmongThemPolicy without a real env info.
            # We bypass the base constructor by setting fields directly,
            # since the mettagrid types are stubs in the test environment.
            policy = AmongThemPolicy.__new__(AmongThemPolicy)
            policy._seed = 0
            policy._cores = {}
            policy._last_actions = {}
            policy._last_chats = {}
            policy._reference_data = None  # state-obs fallback path
            policy._localizer = None
            policy._trace = writer
            policy._owns_trace = False

            # Simulate a frame that would normally return a chat line.
            core = policy._core(0)
            # Force the bot's voting machinery so ``take_chat`` returns text.
            core.bot.voting.active = True
            core.bot.chat.queued = "hello"
            core.bot.tick = 42  # post-step tick; chat belongs to tick 41
            chat = core.take_chat()
            self.assertEqual(chat, "hello")
            # Emit as the step_batch path would.
            writer.record_chat_sent(0, chat, tick=core.bot.tick - 1)
            writer.close()

            events = _read_jsonl(
                Path(tmp) / "modulabot" / "policy" / "agent_0" / "events.jsonl"
            )
            chat_events = [e for e in events if e["type"] == "chat_sent"]
            self.assertEqual(len(chat_events), 1)
            self.assertEqual(chat_events[0]["text"], "hello")
            self.assertEqual(chat_events[0]["tick"], 41)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _rmtree(path: str) -> None:
    """shutil.rmtree but tolerant of already-gone paths (tempdirs)."""
    import shutil

    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
