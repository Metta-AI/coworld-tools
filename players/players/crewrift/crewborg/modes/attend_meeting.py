"""Attend Meeting mode: chat once, then vote (design §7.1).

Active while ``phase == Voting``. It speaks a short opening line once, then casts
its vote. The default voting policy is **skip** (design §12: always cast a vote
before the timer — not voting costs −10); the action layer drives the cursor onto
the skip cell and confirms. Suspicion-aware voting is a later refinement.
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode

# A short, printable-ASCII opener. Kept minimal until suspicion reasoning exists.
MEETING_CHAT = "no read, skipping"


class AttendMeetingMode(Mode[Belief, ActionState, Intent]):
    name = "attend_meeting"
    params_type = EmptyModeParams

    def __init__(self, params=None) -> None:
        super().__init__(params)
        self._chatted = False

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del belief, action_state
        if not self._chatted:
            self._chatted = True
            return Intent(kind="chat", text=MEETING_CHAT, reason="meeting opener")
        return Intent(kind="vote", reason="default policy: skip")
