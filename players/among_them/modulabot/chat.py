"""Meeting-chat composition.

Port of modulabot's ``chat.nim``. Chat only fires during the voting phase,
so all we need to do during gameplay is *queue* a line; :mod:`~modulabot.
policies.voting` pulls the queue on the voting transition and surfaces it
via the cogames ``Action(talk=...)`` path.

We keep the templates rule-based for v0. An LLM provider can slot in later
by overriding :func:`format_body_report` and :func:`format_kill_defense`.
"""

from __future__ import annotations

from .state import Bot
from .tuning import CHAT_MAX_CHARS

#: PICO-8 palette indices to colour names. Must match the BitWorld server's
#: palette mapping. If the server ever recolours, update this table.
PLAYER_COLOR_NAMES: tuple[str, ...] = (
    "red",
    "orange",
    "yellow",
    "lightblue",
    "pink",
    "lime",
    "blue",
    "paleblue",
    "gray",
    "white",
    "darkbrown",
    "brown",
    "darkteal",
    "green",
    "darknavy",
    "black",
)


def color_name(color: int) -> str:
    if 0 <= color < len(PLAYER_COLOR_NAMES):
        return PLAYER_COLOR_NAMES[color]
    return f"p{color}"


def format_body_report(suspect_color: int = -1) -> str:
    """Crewmate chat: "body found", optional suspicion."""
    if 0 <= suspect_color < len(PLAYER_COLOR_NAMES):
        return _trim(f"body found; {color_name(suspect_color)} sus")
    return _trim("body found, skip unless proof")


def format_kill_defense() -> str:
    """Imposter chat: deny, redirect. Keep it short and plausible."""
    return _trim("was doing tasks, skip")


def queue_body_report(bot: Bot, suspect_color: int = -1) -> None:
    """Queue a crewmate body-seen report. No-op if one is already queued."""
    if bot.chat.queued:
        return
    bot.chat.queued = format_body_report(suspect_color)


def queue_kill_defense(bot: Bot) -> None:
    """Queue an imposter defense line. Overwrites any existing queued chat.

    We overwrite (unlike :func:`queue_body_report`) because if we're about to
    be accused, the defense line matters more than whatever we queued before.
    """
    bot.chat.queued = format_kill_defense()


def take_queued(bot: Bot) -> str:
    """Drain the queued chat line and record the flush tick. Returns "" if empty."""
    if not bot.chat.queued:
        return ""
    text = bot.chat.queued
    bot.chat.queued = ""
    bot.chat.last_flushed_tick = bot.percep.tick
    return text


def _trim(text: str) -> str:
    if len(text) <= CHAT_MAX_CHARS:
        return text
    return text[:CHAT_MAX_CHARS].rstrip()
