"""Integration tests for the pixel-observation pipeline.

These tests drive :class:`~modulabot.bot.BotCore` end-to-end with
``reference_data`` set, exercising the full pixel path:
frame → :func:`~modulabot.perception.pixel_pipeline.update_from_pixel_observation`
→ :func:`~modulabot.actors.scan_all` / :func:`~modulabot.localize.Localizer.update_location`
→ adapter → policy decision.

Layers:

1. **Phase detection** — real fixture frames produce the expected
   phases (interstitials → ``INTERSTITIAL``, gameplay frames →
   ``PLAYING``).
2. **Localization wired in** — on gameplay frames the pipeline leaves
   ``bot.percep.localized = True`` and a non-zero camera.
3. **Policy-facing state adapters** — when we detect crewmates /
   bodies / task icons, they surface as ``bot.percep.players /
   bodies / tasks`` so the existing policies can read them.
4. **Voting path** — a synthetic voting frame (player sprites +
   SKIP banner) drives the bot into ``Phase.VOTING`` and populates
   ``bot.voting.*`` parse-cache fields.

We use the real captured ``fixtures_frames.npy`` for phase /
localization integration and synthesize voting frames inline —
matching the same approach the isolated voting-parser tests use.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from modulabot import ascii as ascii_mod
from modulabot import voting as voting_mod
from modulabot.bot import BotCore
from modulabot.data import (
    PLAYER_COLORS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHADE_TINT_COLOR,
    SHADOW_MAP,
    TINT_COLOR,
    TRANSPARENT_INDEX,
    load_reference_data,
)
from modulabot.state import Phase, Role
from modulabot.voting import (
    VOTE_CELL_W,
    VOTE_CHAT_ICON_X,
    VOTE_CHAT_TEXT_X,
    vote_cell_origin,
    vote_grid_layout,
)


_FIXTURES = Path(__file__).resolve().parent / "fixtures_frames.npy"


def _paint_crewmate(frame, sprite, x, y, tint):
    for sy in range(sprite.height):
        for sx in range(sprite.width):
            color = int(sprite.pixels[sy, sx])
            if color == TRANSPARENT_INDEX:
                continue
            if color == TINT_COLOR:
                frame[y + sy, x + sx] = tint
            elif color == SHADE_TINT_COLOR:
                frame[y + sy, x + sx] = int(SHADOW_MAP[tint & 0x0F])
            else:
                frame[y + sy, x + sx] = color


def _paint_text(frame, font, text, x, y, color=2):
    pen = x
    for ch in text:
        g = ascii_mod.glyph_at(font, ch)
        for gy in range(g.height):
            for gx in range(g.width):
                if g.pixels[gy, gx]:
                    yy = y + gy
                    xx = pen + gx
                    if 0 <= yy < SCREEN_HEIGHT and 0 <= xx < SCREEN_WIDTH:
                        frame[yy, xx] = color
        pen += ascii_mod.glyph_advance(font, ch)


def _build_voting_frame(data, count, cursor_index=None):
    """Same builder the voting tests use, repeated here so this
    module doesn't import from the voting test module."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    for i in range(count):
        cx, cy = vote_cell_origin(count, i)
        spx = cx + (VOTE_CELL_W - data.sprites.player.width) // 2
        spy = cy + 1
        _paint_crewmate(frame, data.sprites.player, spx, spy, int(PLAYER_COLORS[i]))
    layout = vote_grid_layout(count)
    _paint_text(frame, data.font, "SKIP", layout.skip_x, layout.skip_y, color=2)
    if cursor_index is not None:
        _CURSOR_COLOR = 2
        if cursor_index == count:
            frame[layout.skip_y - 1, layout.skip_x : layout.skip_x + 28] = _CURSOR_COLOR
            frame[layout.skip_y + 6, layout.skip_x : layout.skip_x + 28] = _CURSOR_COLOR
        elif 0 <= cursor_index < count:
            cx, cy = vote_cell_origin(count, cursor_index)
            frame[cy - 1, cx : cx + VOTE_CELL_W] = _CURSOR_COLOR
            frame[cy + 17 - 2, cx : cx + VOTE_CELL_W] = _CURSOR_COLOR
    return frame


# ---------------------------------------------------------------------------
# Fixture-based tests
# ---------------------------------------------------------------------------


class PixelPipelineFixtureTests(unittest.TestCase):
    """Run the real captured frames through ``BotCore``.

    Asserts the pipeline wires together correctly: phase detection
    lights up correctly, localization locks on gameplay frames, and
    the adapter layer populates ``bot.percep.players`` (at minimum
    the self-sighting is always present on gameplay frames).
    """

    @classmethod
    def setUpClass(cls):
        if not _FIXTURES.exists():
            raise unittest.SkipTest(f"fixtures_frames.npy not found at {_FIXTURES}")
        cls.frames = np.load(_FIXTURES)
        cls.data = load_reference_data()

    def test_interstitial_frames_classified_as_interstitial(self):
        """Early fixture frames are the pre-round splash + role reveal
        (≥30% black). The pipeline should route them to
        ``Phase.INTERSTITIAL`` (not VOTING — the voting parser's
        strict slot check rejects non-voting interstitials)."""
        core = BotCore(agent_id=0, reference_data=self.data)
        core.step(self.frames[25])  # pre-round splash
        self.assertEqual(core.bot.percep.phase, Phase.INTERSTITIAL)
        self.assertTrue(core.bot.percep.interstitial)

    def test_gameplay_frame_localizes_and_populates_self_sighting(self):
        """A real gameplay frame should land on ``Phase.PLAYING``,
        populate a camera lock, and include the self-player sighting
        in ``bot.percep.players``."""
        core = BotCore(agent_id=0, reference_data=self.data)
        core.step(self.frames[150])
        bot = core.bot
        self.assertEqual(bot.percep.phase, Phase.PLAYING)
        self.assertTrue(bot.percep.localized)
        # Camera is at the skeld2 lobby area; just assert it's non-zero
        # which rules out "stuck at default".
        self.assertNotEqual((bot.percep.camera_x, bot.percep.camera_y), (0, 0))
        # Self sighting always first in the list.
        self.assertGreaterEqual(len(bot.percep.players), 1)
        self.assertTrue(bot.percep.players[0].is_self)

    def test_role_inference_fires_on_real_frame(self):
        """Role HUD detection runs as part of ``scan_all`` inside the
        pipeline, so after one gameplay frame the role should no
        longer be UNKNOWN."""
        core = BotCore(agent_id=0, reference_data=self.data)
        core.step(self.frames[150])
        self.assertIn(core.bot.role, (Role.CREWMATE, Role.IMPOSTER))

    def test_pipeline_step_returns_valid_action(self):
        """The full per-frame pipeline must always yield a valid
        BitWorld action index regardless of perception noise."""
        core = BotCore(agent_id=0, reference_data=self.data)
        action = core.step(self.frames[150])
        self.assertTrue(0 <= action < 27)


# ---------------------------------------------------------------------------
# Synthetic voting frame end-to-end
# ---------------------------------------------------------------------------


class PixelPipelineVotingTests(unittest.TestCase):
    """Drive a synthetic voting frame through ``BotCore`` and confirm
    the pixel pipeline + policy stack land on the voting path.

    The phase check here is the end-to-end proof that the pipeline
    routes interstitial frames through the voting parser, populates
    the parse cache, and surfaces the result to the policy layer.
    """

    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()

    def test_voting_frame_drives_phase_voting(self):
        frame = _build_voting_frame(self.data, 4, cursor_index=1)
        core = BotCore(agent_id=0, reference_data=self.data)
        core.bot.role = Role.CREWMATE
        core.step(frame)
        self.assertEqual(core.bot.percep.phase, Phase.VOTING)
        self.assertTrue(core.bot.voting.active)
        self.assertEqual(core.bot.voting.player_count, 4)
        self.assertEqual(core.bot.voting.cursor, 1)

    def test_voting_policy_eventually_presses_a(self):
        """Crewmate with no accusation_color and chat-sus off should
        pick SKIP as the target and press A once the cursor reaches
        it (or after the stuck-cursor timeout, whichever comes
        first). The cursor stays at position 1 in every frame of
        this synthetic capture — so the stuck-cursor fallback is
        what fires here. Good: it proves the safety valve works."""
        frame = _build_voting_frame(self.data, 4, cursor_index=1)
        core = BotCore(agent_id=0, reference_data=self.data)
        core.bot.role = Role.CREWMATE
        saw_a = False
        for _ in range(500):
            action = core.step(frame)
            if action == 1:  # actions.A
                saw_a = True
                break
        self.assertTrue(saw_a, "voting policy should eventually press A")
        self.assertTrue(core.bot.voting.committed)

    def test_chat_sus_drives_imposter_bandwagon(self):
        """Imposter with a visible 'red is sus' chat line should
        target the red slot (index 0), not skip."""
        frame = _build_voting_frame(self.data, 4, cursor_index=0)
        layout = vote_grid_layout(4)
        chat_y = layout.skip_y + 10
        # Paint a red speaker pip + "red is sus" text.
        _paint_crewmate(
            frame, self.data.sprites.player,
            VOTE_CHAT_ICON_X, chat_y + 1, int(PLAYER_COLORS[1]),
        )
        _paint_text(
            frame, self.data.font, "red is sus",
            VOTE_CHAT_TEXT_X, chat_y + 3, color=7,
        )

        core = BotCore(agent_id=0, reference_data=self.data)
        core.bot.role = Role.IMPOSTER
        core.step(frame)
        self.assertEqual(core.bot.voting.chat_sus_color, 0)  # red
        # Target should be the red slot (slot 0) since red is alive
        # and not us.
        self.assertEqual(core.bot.voting.target_slot, 0)


if __name__ == "__main__":
    unittest.main()
