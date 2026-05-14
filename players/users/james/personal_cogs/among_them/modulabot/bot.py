"""Per-agent orchestrator.

:class:`BotCore` owns one :class:`~modulabot.state.Bot` and the three
policies. Its :meth:`step` method runs the modulabot per-frame pipeline:

1. Clear diag.
2. Update :class:`~modulabot.state.Perception` from the observation —
   either the full pixel pipeline (when ``reference_data`` is
   supplied) or the legacy state-obs / minimal-pixel dispatcher.
3. Dispatch by phase:
   - voting → :class:`~modulabot.policies.voting.VotingPolicy`
   - interstitial (non-voting) → NOOP + reset voting state
   - playing → role dispatch (crewmate / imposter)
4. Update motion + evidence + tick.
5. (Optional) notify the attached :class:`~modulabot.trace.TraceWriter`.

This mirrors the shape of ``decideNextMask`` in the Nim bot (``bot.nim``),
with the pixel pipeline now driving perception in the tournament path
the same way ``actors.scanAll`` + ``localize.updateLocation`` drive it
in Nim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

from . import actions, diag, evidence
from .perception import update_perception
from .perception.pixel_pipeline import update_from_pixel_observation
from .policies import CrewmatePolicy, ImposterPolicy, VotingPolicy
from .policies.base import update_motion
from .state import Bot, Phase, Role

if TYPE_CHECKING:  # pragma: no cover
    from .data import ReferenceData
    from .localize import Localizer
    from .trace import TraceWriter


class BotCore:
    """One instance per controlled agent.

    Parameters
    ----------
    agent_id, rng_seed:
        Standard per-agent identifiers used by the policy layer.
    reference_data:
        Optional shipped static data (sprites, font, game map). When
        supplied, :meth:`step` runs the full pixel-perception pipeline
        (scan actors → localize → parse voting on interstitials → adapt
        to policy-facing state). When ``None``, falls back to the
        legacy state-obs parser + minimal pixel fallback — kept for
        synthetic unit tests that don't want to load the assets.
    localizer:
        Optional pre-built :class:`~modulabot.localize.Localizer`. If
        ``reference_data`` is supplied but ``localizer`` is ``None``,
        one is constructed here. A multi-agent harness can share a
        single localizer across bots (the localizer's internal caches
        are per-instance so sharing is fine).
    trace_writer:
        Optional trace sink. When supplied, :meth:`step` calls
        ``trace_writer.record_frame(self.bot, action)`` at the end of
        every tick, before ``bot.tick`` is advanced — so the recorded
        tick matches the frame the decision was made on. Errors
        inside the writer are swallowed by the writer itself to
        preserve the non-perturbation invariant.
    """

    def __init__(
        self,
        agent_id: int,
        rng_seed: int = 0,
        *,
        reference_data: "Optional[ReferenceData]" = None,
        localizer: "Optional[Localizer]" = None,
        trace_writer: "Optional[TraceWriter]" = None,
    ) -> None:
        self.bot = Bot(agent_id=agent_id, rng_seed=rng_seed)
        self._crewmate = CrewmatePolicy()
        self._imposter = ImposterPolicy()
        self._voting = VotingPolicy()
        self._trace = trace_writer
        self._reference_data = reference_data
        if reference_data is not None and localizer is None:
            from .localize import Localizer as _Localizer

            localizer = _Localizer(reference_data.map)
        self._localizer = localizer

    # ------------------------------------------------------------------

    def step(self, observation: np.ndarray) -> int:
        bot = self.bot
        bot.percep.tick = bot.tick

        diag.clear(bot)
        if self._reference_data is not None and self._localizer is not None:
            update_from_pixel_observation(
                bot,
                self._reference_data,
                self._localizer,
                observation,
                bot.tick,
            )
        else:
            update_perception(bot, observation)

        # Evidence bookkeeping runs every frame so diff detection stays honest.
        evidence.update_evidence(bot)
        update_motion(bot)

        action = self._dispatch()

        # Record the completed frame *before* advancing the tick so the
        # trace's ``tick`` matches ``bot.percep.tick`` / the tick the
        # decision fired on.
        if self._trace is not None:
            self._trace.record_frame(bot, int(action))

        bot.tick += 1
        return int(action)

    # ------------------------------------------------------------------

    def take_chat(self) -> str | None:
        """Return a chat line queued during this frame, or ``None``.

        Only returns a message when ``voting`` is active and there's a
        queued line. Callers must invoke this exactly once per step — it
        drains the queue.
        """
        if not self.bot.voting.active:
            return None
        from .chat import take_queued

        text = take_queued(self.bot)
        return text if text else None

    # ------------------------------------------------------------------

    def _dispatch(self) -> int:
        bot = self.bot
        phase = bot.percep.phase
        game_map = self._reference_data.map if self._reference_data is not None else None

        if phase == Phase.VOTING:
            return self._voting.decide(bot, game_map)

        if phase != Phase.PLAYING and bot.percep.interstitial:
            # Role reveal, game-over, round splash, etc. Do nothing but
            # clear any lingering voting state so the next vote starts clean.
            if bot.voting.active:
                self._voting.reset(bot)
            bot.fired("interstitial.wait", "interstitial, idle")
            return actions.NOOP

        # PLAYING (or UNKNOWN falling through). Close out voting if we were
        # just voting a tick ago.
        if bot.voting.active:
            self._voting.reset(bot)

        if bot.role == Role.IMPOSTER:
            return self._imposter.decide(bot, game_map)
        return self._crewmate.decide(bot, game_map)
