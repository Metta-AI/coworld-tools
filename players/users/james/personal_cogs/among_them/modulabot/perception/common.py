"""Perception dispatcher and shared helpers.

:func:`update_perception` is the **fallback** entrypoint used when
:class:`~modulabot.bot.BotCore` was constructed without a
``ReferenceData`` bundle (i.e. without sprites, map, font). It routes
to either the state-obs or minimal-pixel backend based on the
observation shape.

In tournament play `BotCore` always has `reference_data` and goes
through :mod:`modulabot.perception.pixel_pipeline` directly, bypassing
this module entirely. The production code path is documented in
``modulabot/README.md``; ``common.py`` is kept for tests and any
training-harness consumer that wants a no-FFI cheap path.

Observation-shape conventions (matching the ``bitworld_among_them_cyborg``
reference policy and the cogames BitWorld shim):

- State observations: either ``(frame_stack, STATE_FEATURES)`` or
  ``(STATE_FEATURES * frame_stack,)`` where ``STATE_FEATURES`` is the
  structured-state feature count.
- Pixel observations: ``(frame_stack, 128, 128)`` uint8, or ``(128, 128)``
  uint8, or ``(packed_bytes,)`` 4-bit packed. For stacked frames we always
  take the most recent.

Only the most recent frame of the stack is ever read. Frame-stack history is
available via :attr:`modulabot.state.Motion` (we store last-frame deltas,
not the whole stack).
"""

from __future__ import annotations

import numpy as np

from ..state import Bot
from . import pixel_obs, state_obs


def update_perception(bot: Bot, observation: np.ndarray) -> None:
    """Dispatch ``observation`` to the correct backend and fill ``bot.percep``.

    Always leaves ``bot.percep.tick`` unchanged — the tick is owned by the
    :class:`~modulabot.bot.BotCore` orchestrator, not by perception.
    """
    if state_obs.looks_like_state_observation(observation):
        state_obs.update_from_state_obs(bot, observation)
    else:
        pixel_obs.update_from_pixel_obs(bot, observation)
