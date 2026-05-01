"""Tests for the policy-base motion tracker and deadband plumbing.

Pins the Phase-1 movement fixes the live-run exposed:

- ``update_motion`` must track world-coord velocity when the
  localizer has a lock, not just screen-space (which is always
  centred on the bot in pixel mode).
- Stuck counter only grows during :data:`~modulabot.state.Phase.PLAYING`
  — interstitial / voting frames shouldn't inflate it.
- Teleport samples (post-interstitial respawn, localizer re-lock)
  get swallowed instead of producing a giant velocity spike.
- ``move_toward`` defaults to :data:`~modulabot.tuning.ARRIVAL_DEADBAND`
  so arrival-time oscillation is absorbed; ``CLOSE_DISTANCE`` stays
  tight for the "interact now" check.
"""

from __future__ import annotations

import unittest

from modulabot import actions
from modulabot.policies.base import (
    move_away_from,
    move_toward,
    update_motion,
    world_self_position,
)
from modulabot.state import Bot, Phase, PlayerSighting, Role
from modulabot.tuning import (
    ARRIVAL_DEADBAND,
    CLOSE_DISTANCE,
    CENTER_X,
    CENTER_Y,
    STUCK_TICKS,
    TELEPORT_VELOCITY_THRESHOLD,
)


def _bot_at(world_x: int, world_y: int, *, phase: Phase = Phase.PLAYING) -> Bot:
    """Build a Bot with a world-locked camera at the given position.

    Sets up the :class:`~modulabot.state.Perception` so that
    :func:`world_self_position` returns ``(world_x, world_y)`` — i.e.
    the camera offset is chosen so that
    ``camera_x + PLAYER_WORLD_OFF_X == world_x`` and similarly for Y.
    """
    from modulabot.geometry import camera_x_for_world, camera_y_for_world

    bot = Bot(agent_id=0, role=Role.CREWMATE)
    bot.percep.phase = phase
    bot.percep.localized = True
    bot.percep.camera_x = camera_x_for_world(world_x)
    bot.percep.camera_y = camera_y_for_world(world_y)
    return bot


class WorldSelfPositionTests(unittest.TestCase):
    def test_returns_world_coords_when_localized(self):
        bot = _bot_at(400, 200)
        self.assertEqual(world_self_position(bot), (400, 200))

    def test_returns_sentinel_when_not_localized(self):
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        bot.percep.localized = False
        self.assertEqual(world_self_position(bot), (-1, -1))


class UpdateMotionTests(unittest.TestCase):
    def test_first_frame_seeds_prev_without_velocity(self):
        """A fresh motion tracker should record the first position
        and report zero velocity — not ``world_x - 0 == 400`` as the
        raw diff would."""
        bot = _bot_at(400, 200)
        update_motion(bot)
        self.assertEqual(bot.motion.velocity_x, 0)
        self.assertEqual(bot.motion.velocity_y, 0)
        self.assertTrue(bot.motion.prev_self_valid)
        self.assertEqual(bot.motion.stuck_ticks, 0)

    def test_world_motion_reads_velocity(self):
        """Camera moving = bot moving. Velocity should reflect the
        frame-to-frame world delta, not screen-space (which is
        constant at centre in pixel mode)."""
        bot = _bot_at(400, 200)
        update_motion(bot)  # seed
        bot = _update_camera(bot, 402, 201)
        update_motion(bot)
        self.assertEqual(bot.motion.velocity_x, 2)
        self.assertEqual(bot.motion.velocity_y, 1)
        # Real motion resets stuck.
        self.assertEqual(bot.motion.stuck_ticks, 0)

    def test_stuck_counter_grows_when_not_moving_with_goal(self):
        """Stationary camera + bot.goal.has = True → stuck grows."""
        bot = _bot_at(400, 200)
        bot.goal.has = True
        update_motion(bot)  # seed
        for _ in range(5):
            update_motion(bot)  # no camera change
        self.assertEqual(bot.motion.stuck_ticks, 5)

    def test_stuck_counter_ignored_in_non_playing_phase(self):
        """Voting / interstitial shouldn't grow the stuck counter
        — the sim isn't running player physics there."""
        bot = _bot_at(400, 200, phase=Phase.VOTING)
        bot.goal.has = True
        update_motion(bot)
        for _ in range(10):
            update_motion(bot)
        self.assertEqual(bot.motion.stuck_ticks, 0)

    def test_teleport_is_swallowed(self):
        """A sample with |velocity| > TELEPORT_VELOCITY_THRESHOLD
        should reseed prev without producing a velocity spike.

        This is what fires on the first playing frame after an
        interstitial: camera jumps hundreds of pixels once
        localization re-locks. Without the guard, stuck counters
        and downstream velocity readers would see the jump as
        real motion and misbehave.
        """
        bot = _bot_at(400, 200)
        update_motion(bot)
        bot = _update_camera(bot, 400 + TELEPORT_VELOCITY_THRESHOLD + 5, 200)
        update_motion(bot)
        self.assertEqual(bot.motion.velocity_x, 0)
        self.assertEqual(bot.motion.velocity_y, 0)
        # Subsequent small move from the new position is tracked correctly.
        bot = _update_camera(bot, 400 + TELEPORT_VELOCITY_THRESHOLD + 7, 200)
        update_motion(bot)
        self.assertEqual(bot.motion.velocity_x, 2)


class MoveTowardDeadbandTests(unittest.TestCase):
    def test_default_uses_arrival_deadband(self):
        """A target within ``ARRIVAL_DEADBAND`` of screen centre
        should produce NOOP; a target just outside should steer."""
        # One pixel inside the arrival band → NOOP.
        self.assertEqual(
            move_toward(CENTER_X + ARRIVAL_DEADBAND - 1, CENTER_Y),
            actions.NOOP,
        )
        # One pixel outside → RIGHT.
        self.assertEqual(
            move_toward(CENTER_X + ARRIVAL_DEADBAND + 1, CENTER_Y),
            actions.RIGHT,
        )

    def test_arrival_deadband_exceeds_close_distance(self):
        """Arrival is explicitly looser than interaction. If this
        invariant ever flips the tight-deadband orbit bug is back."""
        self.assertGreater(ARRIVAL_DEADBAND, CLOSE_DISTANCE)

    def test_explicit_deadband_still_honoured(self):
        """Callers that want the tight deadband (body-report,
        press-A-when-arrived) should still be able to override the
        default."""
        # CLOSE_DISTANCE < ARRIVAL_DEADBAND, so a target at
        # CLOSE_DISTANCE+1 is inside the default band but outside
        # the explicit one.
        target_x = CENTER_X + CLOSE_DISTANCE + 1
        self.assertEqual(move_toward(target_x, CENTER_Y, deadband=CLOSE_DISTANCE), actions.RIGHT)
        self.assertEqual(move_toward(target_x, CENTER_Y), actions.NOOP)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _update_camera(bot: Bot, world_x: int, world_y: int) -> Bot:
    """Shift the bot's camera so ``world_self_position`` reports the
    new coordinate, without touching any other state."""
    from modulabot.geometry import camera_x_for_world, camera_y_for_world

    bot.percep.camera_x = camera_x_for_world(world_x)
    bot.percep.camera_y = camera_y_for_world(world_y)
    return bot


if __name__ == "__main__":
    unittest.main()
