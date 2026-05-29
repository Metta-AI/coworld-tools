"""Rule-based mode selector (design §10).

A deterministic ``decide(snapshot) -> ModeDirective`` run every tick via
``SynchronousStrategyRunner`` — pure rules over belief. Because it runs every
tick, transitions are re-evaluated each cycle (no reflexes).

Crewmate priority order (design §10):

1. ``phase == Voting`` → Attend Meeting
2. a believed imposter approaching → Flee
3. a body in view → Report Body
4. ``phase == Playing`` → Normal (ghosts included — they finish their own tasks)
5. otherwise → idle

Imposter selection lands in P4; until then an imposter falls through to idle.
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief
from players.player_sdk import ModeDirective
from players.player_sdk.types import BeliefSnapshot

# A believed imposter within this distance (squared, world px) counts as
# "approaching" and triggers Flee.
FLEE_APPROACH_SQ = 60**2


class RuleBasedStrategy:
    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> ModeDirective:
        with snapshot.read() as memory:
            belief = memory.belief
            directive = self._select(belief)
        return directive

    def _select(self, belief: Belief) -> ModeDirective:
        phase = belief.phase

        if phase == "Voting":
            return ModeDirective(mode="attend_meeting", source="strategy", reason="meeting open")

        # Crewmate (or not-yet-known / ghost) field behaviour during play.
        if phase == "Playing" and belief.self_role in (None, "crewmate", "dead"):
            if _threat_approaching(belief):
                return ModeDirective(mode="flee", source="strategy", reason="believed imposter near")
            if any(bid in belief.bodies for bid in belief.visible_body_ids):
                return ModeDirective(mode="report_body", source="strategy", reason="body in view")
            return ModeDirective(mode="normal", source="strategy", reason="playing: do tasks")

        # Imposter behaviour (P4) and all non-play phases idle.
        return ModeDirective(mode="idle", source="strategy", reason=f"idle in phase {phase}")


def _threat_approaching(belief: Belief) -> bool:
    if belief.self_world_x is None or belief.self_world_y is None:
        return False
    sx, sy = belief.self_world_x, belief.self_world_y
    for pid in belief.believed_imposters:
        entry = belief.roster.get(pid)
        if entry is None:
            continue
        if (entry.world_x - sx) ** 2 + (entry.world_y - sy) ** 2 <= FLEE_APPROACH_SQ:
            return True
    return False
