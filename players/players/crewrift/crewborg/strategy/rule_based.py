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
2. a body in view → Report Body (**self-report** — see below)
3. kill ready + a trackable victim → Hunt (commit to a victim, stalk it, strike when isolated)
4. otherwise → Pretend (blend in: follow the crew, fake tasks, wander rooms when none in sight)

(2) is a deliberate tempo play, not a crewmate hand-me-down. A body on the floor
*always* triggers a meeting eventually (some crewmate finds it), and a meeting resets
our kill cooldown — so the reset is inevitable. Self-reporting the instant we see the
body (typically our own fresh kill, while we are on cooldown anyway) fires that
meeting at the earliest possible moment: it advances our *next* kill window by the
whole discovery lag, and denies the crew the task-time they would have banked while
the body sat unfound (tasks pause during meetings). The old Evade behaviour — slink
away and leave the body — handed the crew that time for free; it is gone.

(3) fires whenever the kill is ready and some crewmate is trackable — Hunt then
*stalks* the chosen victim and only fires the kill when it would go unwitnessed
(``strategy.opportunity``), the witness bar relaxing with urgency. When no crewmate
is trackable (e.g. none seen recently), the imposter stays in Pretend and wanders to
find the crew.
"""

from __future__ import annotations

from players.crewrift.crewborg.strategy.opportunity import has_trackable_victim
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
        # Imposter priority (design §10): self-report a visible body (tempo — fire the
        # inevitable meeting + cooldown reset at once, denying the crew task-time);
        # else kill ready *and* a victim trackable -> Hunt (commit + stalk + strike when
        # isolated); else Pretend (blend in: follow crew, fake tasks, wander rooms).
        if any(bid in belief.bodies for bid in belief.visible_body_ids):
            return ModeDirective(mode="report_body", source="strategy", reason="self-report the body (tempo)")
        if belief.self_kill_ready and has_trackable_victim(belief):
            return ModeDirective(mode="hunt", source="strategy", reason="kill ready: stalk a victim")
        return ModeDirective(mode="pretend", source="strategy", reason="blend in")


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
