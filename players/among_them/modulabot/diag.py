"""Diagnostic helpers.

Thin wrappers around :attr:`~modulabot.state.Bot.diag` for logging intent
and thoughts. Segregated from real state so a log-line change can never
affect behaviour (Nim ``Diag`` design note).

Policy modules should call :func:`thought` and :meth:`~modulabot.state.Bot.
fired` freely. Nothing here should ever read from these fields — if you
need a signal to drive a decision, it belongs in a state sub-record, not
in ``Diag``.
"""

from __future__ import annotations

import logging

from .state import Bot

_logger = logging.getLogger("modulabot")


def thought(bot: Bot, text: str) -> None:
    """Record a free-form debug note. Also emitted at DEBUG level."""
    bot.diag.thought = text
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug("agent %d tick %d: %s", bot.agent_id, bot.percep.tick, text)


def clear(bot: Bot) -> None:
    """Clear the diag sub-record at frame start.

    Called once per tick from the orchestrator before the policy runs, so
    a missed :meth:`Bot.fired` call shows up as an empty ``branch_id``
    (making the omission detectable in tests — see
    :data:`modulabot.tuning.STRICT_BRANCH_ID`).
    """
    bot.diag.branch_id = ""
    bot.diag.intent = ""
    bot.diag.thought = ""
