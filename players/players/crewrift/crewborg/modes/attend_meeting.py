"""Attend Meeting mode: chat once, then vote (design §7.1).

Active while ``phase == Voting``. It speaks a short opening line once, then casts
its vote: **the most-suspicious live player** if our posterior P(imposter) for them
clears ``VOTE_PROBABILITY`` (``strategy.suspicion.top_suspect``), otherwise **skip**
(design §12: always cast *something* before the timer — not voting costs −10). The
action layer drives the cursor onto the chosen cell and confirms. Chat is still a
canned opener; suspicion-aware chat is a later refinement.
"""

from __future__ import annotations

from players.crewrift.crewborg.strategy.suspicion import top_suspect
from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode

# A short, printable-ASCII opener. Kept minimal until suspicion-aware chat exists.
MEETING_CHAT = "no read, skipping"


class AttendMeetingMode(Mode[Belief, ActionState, Intent]):
    name = "attend_meeting"
    params_type = EmptyModeParams

    def __init__(self, params=None) -> None:
        super().__init__(params)
        self._chatted = False

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        if not self._chatted:
            self._chatted = True
            return Intent(kind="chat", text=MEETING_CHAT, reason="meeting opener")
        suspect = top_suspect(belief)
        if suspect is not None:
            return Intent(kind="vote", target_color=suspect, reason=f"voting suspect: {suspect}")
        return Intent(kind="vote", reason="no confident suspect: skip")
