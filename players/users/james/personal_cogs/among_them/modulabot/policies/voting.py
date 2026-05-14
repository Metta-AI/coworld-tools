"""Voting-phase decision tree.

Port of modulabot's ``voting.nim`` decision half (parse half lives in
:mod:`modulabot.voting`). Reads the parse cache populated by
:func:`modulabot.voting.parse_voting_screen` — slots, cursor,
choices, chat-derived sus colour — and drives the cursor one
edge-triggered step at a time until we've committed our vote.

Decision flow:

1. First voting frame (``player_count == 0``) → idle NOOP until the
   parser runs.
2. Subsequent frames pick a target slot from evidence / chat, then:
   - Already voted (``self_vote_choice != VOTE_UNKNOWN``) → idle.
   - Cursor not on target → nudge LEFT / RIGHT toward it
     (:func:`modulabot.voting.vote_move_direction` picks the shorter
     direction), with off-ticks as NOOP so the UI's edge-trigger
     movement registers one cell per press.
   - Cursor on target but listen timer hasn't expired → NOOP to
     absorb late "sus X" chat calls.
   - Otherwise → press A.

Target selection asymmetry — **this is the policy core**:

- IMPOSTER: bandwagon onto the most prominent "sus <colour>" chat
  call, then fall back to our own evidence, then skip. Blends in
  with herd voting.
- CREWMATE: evidence only. Immune to chat-first imposter
  manipulation; votes only when we personally witnessed something
  suspect, else skips.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import actions, chat, diag
from .. import voting as voting_mod
from ..state import Bot, Role
from ..tuning import (
    VOTE_CURSOR_MAX_STEPS,
    VOTE_CURSOR_STEP_TICKS,
    VOTE_LISTEN_TICKS,
)
from .base import Policy

if TYPE_CHECKING:  # pragma: no cover
    from ..data import GameMap


class VotingPolicy(Policy):
    """Voting play: pick a target based on evidence / chat, drive the cursor, commit."""

    def decide(self, bot: Bot, game_map: "GameMap | None" = None) -> int:
        v = bot.voting

        # Parser hasn't populated yet — most commonly the very first
        # voting frame before :func:`parse_voting_screen` has been
        # called. Idle until the parse cache appears.
        if v.player_count == 0:
            bot.fired("vote.idle.not_parsed", "voting screen not yet parsed")
            return actions.NOOP

        # Initialise per-meeting state on first entry.
        if not v.active or v.start_tick < 0:
            v.active = True
            v.start_tick = bot.percep.tick
            v.listen_done = False
            v.committed = False
            v.target_slot = self._pick_target_slot(bot)

        # Drain any queued chat from evidence / body reports. The
        # Action(talk=...) surface belongs to the wrapper; we just
        # flush the queue so it can attach the message on the next
        # step_batch call.
        queued = chat.take_queued(bot)
        if queued:
            diag.thought(bot, f"flushing chat: {queued}")

        # Already voted? The UI can't un-vote so there's nothing more
        # to do this meeting — idle.
        own_vote = voting_mod.self_vote_choice(bot)
        if own_vote != voting_mod.VOTE_UNKNOWN:
            v.committed = True
            bot.fired(
                "vote.idle.already_voted",
                f"voted {voting_mod.vote_target_name(bot, own_vote)}",
            )
            return actions.NOOP

        # Pick target lazily if not yet set (e.g. chat/evidence
        # changed mid-meeting so the initial pick became stale).
        if v.target_slot < 0:
            v.target_slot = self._pick_target_slot(bot)

        # Cursor not on target — drive it, with a hard-cap fallback
        # so a lost cursor (e.g. the sim stops acknowledging our
        # presses for a few ticks, or our target-slot read is stale)
        # can't stall the whole meeting. Past the cap we press A
        # wherever the cursor actually is, matching the Nim
        # ``VoteCursorMaxSteps`` safety valve.
        if v.cursor != v.target_slot:
            elapsed = bot.percep.tick - v.start_tick
            cursor_budget = VOTE_CURSOR_MAX_STEPS * VOTE_CURSOR_STEP_TICKS * 2
            if elapsed >= cursor_budget and elapsed >= VOTE_LISTEN_TICKS:
                v.committed = True
                bot.fired(
                    "vote.press_a.stuck_cursor",
                    "cursor stuck; pressing A anyway",
                )
                return actions.A
            return self._drive_cursor(bot)

        # Cursor on target. Wait through the listen window so late
        # chat can bandwagon us onto a better target.
        elapsed = bot.percep.tick - v.start_tick
        if elapsed < VOTE_LISTEN_TICKS:
            bot.fired(
                "vote.cursor.listen",
                f"listening {elapsed}/{VOTE_LISTEN_TICKS}",
            )
            return actions.NOOP

        v.listen_done = True
        v.committed = True
        bot.fired(
            "vote.press_a",
            f"voting for {voting_mod.vote_target_name(bot, v.target_slot)}",
        )
        return actions.A

    # ------------------------------------------------------------------

    def _pick_target_slot(self, bot: Bot) -> int:
        """Choose whose slot to vote on.

        Imposter: chat-sus → evidence-accusation → skip.
        Crewmate: evidence-accusation → skip.

        Returns the SKIP cursor position (``player_count``) as the
        skip target so cursor-direction math treats it as just
        another selectable index.
        """
        v = bot.voting
        skip = v.player_count  # SKIP cursor position

        if bot.role == Role.IMPOSTER:
            if v.chat_sus_color >= 0:
                slot = self._slot_for_color(bot, v.chat_sus_color)
                if slot != voting_mod.VOTE_UNKNOWN:
                    return slot

        # Evidence-based accusation (available to both roles — it's
        # just that crewmates won't get here without personal
        # evidence, whereas imposters use it as a chat fallback).
        if v.accusation_color >= 0:
            slot = self._slot_for_color(bot, v.accusation_color)
            if slot != voting_mod.VOTE_UNKNOWN:
                return slot

        return skip

    def _slot_for_color(self, bot: Bot, color_index: int) -> int:
        """Return the slot index for ``color_index`` if it's
        selectable (alive, not self), otherwise :data:`VOTE_UNKNOWN`.

        Prevents us from voting for ourselves or for a body (which
        the UI doesn't allow anyway — the cursor skips dead slots
        — but the target picker should match the cursor's universe).
        """
        slot = voting_mod.vote_slot_for_color(bot, color_index)
        v = bot.voting
        if slot == voting_mod.VOTE_UNKNOWN:
            return voting_mod.VOTE_UNKNOWN
        if slot == v.self_slot:
            return voting_mod.VOTE_UNKNOWN
        if not v.slots[slot].alive:
            return voting_mod.VOTE_UNKNOWN
        return slot

    def _drive_cursor(self, bot: Bot) -> int:
        """Emit an edge-triggered cursor nudge toward the target.

        BitWorld's voting cursor advances on edge presses of LEFT /
        RIGHT — holding the button doesn't scroll. We alternate
        direction + NOOP every ``VOTE_CURSOR_STEP_TICKS`` ticks so
        the server registers a fresh press each cell.
        """
        v = bot.voting
        if bot.percep.tick % (VOTE_CURSOR_STEP_TICKS * 2) < VOTE_CURSOR_STEP_TICKS:
            direction = voting_mod.vote_move_direction(bot, v.target_slot)
            action = actions.LEFT if direction < 0 else actions.RIGHT
            bot.fired(
                "vote.cursor.nudge",
                f"cursor → {voting_mod.vote_target_name(bot, v.target_slot)}",
            )
            return action
        bot.fired("vote.cursor.wait", "between cursor nudges")
        return actions.NOOP

    def reset(self, bot: Bot) -> None:
        """Called by the orchestrator when voting ends.

        Clears transient per-meeting fields but leaves the parse
        cache (``slots``, ``choices``, ``chat_*``) alone — the
        pixel pipeline re-clears those on the next interstitial
        transition via
        :func:`modulabot.voting.clear_voting_state`. ``accusation_color``
        persists across meetings so evidence gathered earlier can
        still feed later votes.
        """
        v = bot.voting
        v.active = False
        v.committed = False
        v.listen_done = False
        v.target_slot = -1
        v.start_tick = -1
