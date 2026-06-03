"""Rule-based mode selector (design §10).

A deterministic ``decide(snapshot) -> ModeDirective`` run every tick via
``SynchronousStrategyRunner`` — pure rules over belief. Because it runs every
tick, transitions are re-evaluated each cycle (no reflexes).

Crewmate priority order (design §10):

1. ``phase == Voting`` → Attend Meeting
2. a body in view → Report Body (a meeting protects us; outranks fleeing)
3. a believed imposter approaching → Flee
4. ``phase == Playing`` → Normal (ghosts included — they finish their own tasks)
5. otherwise → idle

``believed_imposters`` (which gates Flee) is filled by the suspicion model
(``strategy.suspicion``, design §10.1), folded into belief each tick.

Imposter priority order (design §10):

1. ``phase == Voting`` → Attend Meeting
2. just killed → Evade (vent / leave the body)
3. a body in view → Report Body (non-fresh bodies only)
4. kill ready + a visible victim → Hunt (commit to a victim and strike / close)
5. kill ready or within ``SEARCH_LEAD_TICKS`` of ready → Search (find/follow a target)
6. otherwise → Pretend (fake tasks in likely occupied rooms)

(2) prevents instant self-reports after our own kill: the imposter first leaves the
scene, preferably through a vent. A non-fresh body can still be reported later if it
remains visible after the evade window.

(5) fires once the kill cooldown is within a short lead window of being ready
(`ticks_until_kill_ready ≤ SEARCH_LEAD_TICKS`, reconstructed from the binary HUD via
`strategy.opportunity`). Search walks occupancy hot spots until it sees a crewmate,
then follows that target. Hunt does not pre-position anymore; it activates only when
the kill is ready and a victim is visible.
"""

from __future__ import annotations

from players.crewrift.crewborg.strategy.opportunity import (
    SEARCH_LEAD_TICKS,
    has_visible_victim,
    ticks_until_kill_ready,
)
from players.crewrift.crewborg.types import ActionState, Belief
from players.player_sdk import ModeDirective
from players.player_sdk.types import BeliefSnapshot

# A believed imposter within this distance (squared, world px) counts as
# "approaching" and triggers Flee.
FLEE_APPROACH_SQ = 60**2
# Ticks after a kill during which the imposter prefers to Evade (≈3s at 24 Hz).
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
            # Live crewmate (or not-yet-known role): full field priority. Reporting a
            # visible body outranks fleeing — a meeting protects us and lets the crew
            # act, which beats running from a suspect we could instead report.
            if any(bid in belief.bodies for bid in belief.visible_body_ids):
                return ModeDirective(mode="report_body", source="strategy", reason="body in view")
            if _threat_approaching(belief):
                return ModeDirective(mode="flee", source="strategy", reason="believed imposter near")
            return ModeDirective(mode="normal", source="strategy", reason="playing: do tasks")

        # All non-play phases (RoleReveal / Lobby / VoteResult / GameOver / unknown).
        return ModeDirective(mode="idle", source="strategy", reason=f"idle in phase {phase}")

    def _select_imposter(self, belief: Belief) -> ModeDirective:
        # Imposter priority (design §10): just killed -> Evade; non-fresh visible
        # body -> Report; kill ready and a victim visible -> Hunt; kill ready or
        # about to be -> Search; else Pretend.
        if _recent_self_kill(belief):
            return ModeDirective(mode="evade", source="strategy", reason="just killed: evade")
        if any(bid in belief.bodies for bid in belief.visible_body_ids):
            return ModeDirective(mode="report_body", source="strategy", reason="body in view after evade window")
        if belief.self_kill_ready and has_visible_victim(belief):
            return ModeDirective(mode="hunt", source="strategy", reason="kill ready: hunt visible victim")
        if ticks_until_kill_ready(belief) <= SEARCH_LEAD_TICKS:
            return ModeDirective(mode="search", source="strategy", reason="kill window near: search for target")
        return ModeDirective(mode="pretend", source="strategy", reason="blend in")


def _recent_self_kill(belief: Belief) -> bool:
    return belief.last_kill_tick is not None and belief.last_tick - belief.last_kill_tick < EVADE_TICKS


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
