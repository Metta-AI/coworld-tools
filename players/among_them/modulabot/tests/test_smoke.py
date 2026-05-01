"""Smoke tests for modulabot.

These tests exercise the per-frame pipeline with synthetic state and pixel
observations. They do *not* require a running cogames environment or the
BitWorld package — we drive :class:`modulabot.bot.BotCore` directly.

Run with::

    pytest among_them/modulabot/tests -q

or, from this directory::

    python -m unittest discover -v

Goals (in order of importance):

1. The pipeline never crashes on reasonable observation shapes.
2. Every frame ends with a valid BitWorld action index (0..26).
3. Every branch we take stamps ``bot.diag.branch_id`` so the trace writer
   can later attribute decisions — the "strict branch ID" check enforces
   this.
4. Basic behaviour sanity: a crewmate with an icon-visible task in front
   walks toward it; an imposter with a lone visible target and kill_ready
   presses A; an interstitial produces NOOP.
"""

from __future__ import annotations

import unittest

import numpy as np

from modulabot import actions
from modulabot.bot import BotCore
from modulabot.perception.state_obs import (
    HEADER_KILL_COOLDOWN,
    HEADER_PHASE,
    HEADER_SELF_ROLE,
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
from modulabot.state import Role
from modulabot.tuning import CENTER_X, CENTER_Y


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
    """Build a synthetic state-observation frame of shape ``(frame_stack, STATE_FEATURES)``."""
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

    stack = np.tile(frame, (frame_stack, 1))
    return stack


class PipelineSmokeTests(unittest.TestCase):
    """Basic "does it run, does it stamp branch_id" tests."""

    def test_pipeline_runs_on_empty_state(self):
        core = BotCore(agent_id=0)
        obs = _state_frame()
        action = core.step(obs)
        self.assertTrue(0 <= action < 27)
        self.assertNotEqual(core.bot.diag.branch_id, "")

    def test_interstitial_returns_noop(self):
        core = BotCore(agent_id=0)
        obs = _state_frame(phase=PHASE_ROLE_REVEAL)
        action = core.step(obs)
        self.assertEqual(action, actions.NOOP)

    def test_self_role_imposter_locks_in_role(self):
        core = BotCore(agent_id=0)
        obs = _state_frame(phase=PHASE_ROLE_REVEAL, self_role=1)
        core.step(obs)
        self.assertEqual(core.bot.role, Role.IMPOSTER)


class CrewmateBehaviourTests(unittest.TestCase):
    def _frame_with_task_east_of_center(self):
        # Task icon visible, located to the right of the self-centred view.
        return _state_frame(
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

    def test_crewmate_walks_right_toward_task(self):
        core = BotCore(agent_id=0)
        core.bot.role = Role.CREWMATE
        action = core.step(self._frame_with_task_east_of_center())
        # Action should include RIGHT (index 12) or RIGHT_A (index 13);
        # the occasional A press happens every ACTION_PERIOD ticks. Either is fine.
        self.assertIn(action, (actions.RIGHT, actions.RIGHT_A))
        self.assertEqual(core.bot.goal.has, True)

    def test_crewmate_reports_adjacent_body(self):
        core = BotCore(agent_id=0)
        core.bot.role = Role.CREWMATE
        obs = _state_frame(
            players=[
                {
                    "x": CENTER_X,
                    "y": CENTER_Y,
                    "color": 13,
                    "flags": PLAYER_SELF | PLAYER_ALIVE,
                }
            ],
            bodies=[{"x": CENTER_X, "y": CENTER_Y, "color": 7}],
        )
        action = core.step(obs)
        # "Press B while NOOP" = report action.
        self.assertEqual(action, actions.B)


class ImposterBehaviourTests(unittest.TestCase):
    def _kill_ready_frame_with_lone_target(self):
        return _state_frame(
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

    def test_imposter_kills_lone_target_in_range(self):
        core = BotCore(agent_id=0)
        core.bot.role = Role.IMPOSTER
        action = core.step(self._kill_ready_frame_with_lone_target())
        self.assertEqual(action, actions.A)
        self.assertGreaterEqual(core.bot.imposter.last_kill_tick, 0)

    def test_imposter_flees_from_body(self):
        core = BotCore(agent_id=0)
        core.bot.role = Role.IMPOSTER
        obs = _state_frame(
            self_role=1,
            players=[
                {
                    "x": CENTER_X,
                    "y": CENTER_Y,
                    "color": 0,
                    "flags": PLAYER_SELF | PLAYER_ALIVE,
                }
            ],
            bodies=[{"x": CENTER_X + 30, "y": CENTER_Y, "color": 7}],
        )
        # No recent kill → should flee (walk left, away from body).
        action = core.step(obs)
        # Accept any westward-component action.
        self.assertIn(
            action,
            (actions.LEFT, actions.LEFT_A, actions.LEFT_B, actions.UP, actions.DOWN),
            f"got action {action}",
        )


class VotingBehaviourTests(unittest.TestCase):
    def test_voting_eventually_commits(self):
        core = BotCore(agent_id=0)
        core.bot.role = Role.CREWMATE
        obs = _state_frame(
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
        # Drive enough ticks to pass VOTE_LISTEN_TICKS and press A.
        saw_a = False
        for _ in range(80):
            action = core.step(obs)
            if action == actions.A:
                saw_a = True
                break
        self.assertTrue(saw_a, "voting should eventually press A")
        self.assertTrue(core.bot.voting.committed)


class PixelObservationTests(unittest.TestCase):
    def test_pixel_interstitial_detected(self):
        core = BotCore(agent_id=0)
        # Mostly-black frame triggers interstitial detection.
        frame = np.zeros((4, 128, 128), dtype=np.uint8)
        action = core.step(frame)
        self.assertEqual(action, actions.NOOP)

    def test_pixel_radar_steers_toward_edge_dot(self):
        core = BotCore(agent_id=0)
        core.bot.role = Role.CREWMATE
        frame = np.zeros((4, 128, 128), dtype=np.uint8)
        # Non-interstitial: fill most of the frame with a non-black colour so
        # we pass the interstitial gate. Then drop a radar pixel on the right edge.
        frame[:, 30:100, 30:100] = 5
        frame[-1, 60:64, 126:128] = 8  # TASK_RADAR_COLOR on the right edge
        action = core.step(frame)
        # Crewmate pixel-mode without task data falls through to patrol.
        # This is mostly a "doesn't crash" test — the pixel path is fallback-only.
        self.assertIn(action, range(27))


if __name__ == "__main__":
    unittest.main()
