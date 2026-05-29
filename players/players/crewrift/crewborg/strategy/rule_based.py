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

# Ticks after a kill during which the imposter prefers to Evade (≈ 3s at 24 Hz).
EVADE_TICKS = 72


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

        if phase == "Playing":
            # A crewmate ghost can't report or be threatened; it only finishes its
            # own tasks (design §7.3), so it goes straight to Normal.
            if belief.self_role == "dead":
                return ModeDirective(mode="normal", source="strategy", reason="ghost: finish own tasks")
            if belief.self_role == "imposter":
                return self._select_imposter(belief)
            # Live crewmate (or not-yet-known role): full field priority.
            if _threat_approaching(belief):
                return ModeDirective(mode="flee", source="strategy", reason="believed imposter near")
            if any(bid in belief.bodies for bid in belief.visible_body_ids):
                return ModeDirective(mode="report_body", source="strategy", reason="body in view")
            return ModeDirective(mode="normal", source="strategy", reason="playing: do tasks")

        # All non-play phases (RoleReveal / Lobby / VoteResult / GameOver / unknown).
        return ModeDirective(mode="idle", source="strategy", reason=f"idle in phase {phase}")

    def _select_imposter(self, belief: Belief) -> ModeDirective:
        # Imposter priority (design §10): just killed -> Evade; kill ready with a
        # target -> Hunt; else Pretend.
        if belief.last_kill_tick is not None and belief.last_tick - belief.last_kill_tick < EVADE_TICKS:
            return ModeDirective(mode="evade", source="strategy", reason="just killed: lay low")
        if belief.self_kill_ready and _has_visible_target(belief):
            return ModeDirective(mode="hunt", source="strategy", reason="kill ready: hunt")
        return ModeDirective(mode="pretend", source="strategy", reason="blend in")


def _has_visible_target(belief: Belief) -> bool:
    """Whether another player is currently in view (a candidate kill target)."""

    return any(entry.last_seen_tick == belief.last_tick for entry in belief.roster.values())


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
