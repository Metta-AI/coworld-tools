"""Rule-based mode selector (design §10).

A deterministic ``decide(snapshot) -> ModeDirective`` run every tick via
``SynchronousStrategyRunner`` — pure rules over belief. Because it runs every
tick, transitions are re-evaluated each cycle (no reflexes).

Crewmate priority order (design §10):

1. ``phase == Voting`` → Attend Meeting
2. a body in view → Report Body (a meeting protects us; outranks fleeing)
3. a believed imposter approaching → Flee, with hysteresis so we do not bounce
   back to tasks while skirting the trigger radius
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

Aggressive experiment: ``CREWBORG_BE_DUMB=1`` (or ``BE_DUMB=1``) replaces the
imposter ``Playing`` priority with only Search/Hunt: Hunt when kill-ready with a
visible victim, otherwise Search. It deliberately skips Pretend, Evade, and
Report Body so we can isolate "always prepare to kill" behavior.
"""

from __future__ import annotations

import os

from players.crewrift.crewborg.strategy.opportunity import (
    SEARCH_LEAD_TICKS,
    has_visible_victim,
    ticks_until_kill_ready,
)
from players.crewrift.crewborg.types import ActionState, Belief, PlayerRecord
from players.player_sdk import ModeDirective
from players.player_sdk.types import BeliefSnapshot

# A recently seen believed imposter within this distance (squared, world px)
# counts as "approaching" and triggers Flee.
FLEE_ENTER_SQ = 60**2
# Once Flee is active, keep it until the current threat is clearly farther away.
FLEE_EXIT_SQ = 100**2
# Stop fleeing a stale last-known position after this many unseen ticks.
FLEE_STALE_TICKS = 48
# Ticks after a kill during which the imposter prefers to Evade (≈3s at 24 Hz).
EVADE_TICKS = 72


class RuleBasedStrategy:
    def __init__(self) -> None:
        self._flee_target: str | None = None

    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> ModeDirective:
        with snapshot.read() as memory:
            belief = memory.belief
            directive = self._select(belief)
        return directive

    def _select(self, belief: Belief) -> ModeDirective:
        phase = belief.phase

        if phase == "Voting":
            self._clear_flee()
            return ModeDirective(mode="attend_meeting", source="strategy", reason="meeting open")

        if phase == "Playing":
            # A crewmate ghost can't report or be threatened; it only finishes its
            # own tasks (design §7.3), so it goes straight to Normal.
            if belief.self_role == "dead":
                self._clear_flee()
                return ModeDirective(mode="normal", source="strategy", reason="ghost: finish own tasks")
            if belief.self_role == "imposter":
                self._clear_flee()
                return self._select_imposter(belief)
            # Live crewmate (or not-yet-known role): full field priority. Reporting a
            # visible body outranks fleeing — a meeting protects us and lets the crew
            # act, which beats running from a suspect we could instead report.
            if any(bid in belief.bodies for bid in belief.visible_body_ids):
                self._clear_flee()
                return ModeDirective(mode="report_body", source="strategy", reason="body in view")
            if self._sticky_flee_target(belief) is not None:
                return ModeDirective(mode="flee", source="strategy", reason="believed imposter near")
            self._clear_flee()
            return ModeDirective(mode="normal", source="strategy", reason="playing: do tasks")

        # All non-play phases (RoleReveal / Lobby / VoteResult / GameOver / unknown).
        self._clear_flee()
        return ModeDirective(mode="idle", source="strategy", reason=f"idle in phase {phase}")

    def _select_imposter(self, belief: Belief) -> ModeDirective:
        # Imposter priority (design §10): just killed -> Evade; non-fresh visible
        # body -> Report; kill ready and a victim visible -> Hunt; kill ready or
        # about to be -> Search; else Pretend.
        if _be_dumb_enabled():
            if belief.self_kill_ready and has_visible_victim(belief):
                return ModeDirective(mode="hunt", source="strategy", reason="be dumb: kill ready with visible victim")
            return ModeDirective(mode="search", source="strategy", reason="be dumb: always seek kill setup")
        if _recent_self_kill(belief):
            return ModeDirective(mode="evade", source="strategy", reason="just killed: evade")
        if any(bid in belief.bodies for bid in belief.visible_body_ids):
            return ModeDirective(mode="report_body", source="strategy", reason="body in view after evade window")
        if belief.self_kill_ready and has_visible_victim(belief):
            return ModeDirective(mode="hunt", source="strategy", reason="kill ready: hunt visible victim")
        if ticks_until_kill_ready(belief) <= SEARCH_LEAD_TICKS:
            return ModeDirective(mode="search", source="strategy", reason="kill window near: search for target")
        return ModeDirective(mode="pretend", source="strategy", reason="blend in")

    def _sticky_flee_target(self, belief: Belief) -> str | None:
        """Return the threat that should keep Flee active this tick.

        Flee enters on the existing 60px trigger, then exits only when the same
        threat is clearly farther away or its last-known position is stale. This
        prevents the normal/task selector and flee selector from fighting at the
        exact trigger radius.
        """

        if self._flee_target is not None and _should_continue_flee(belief, self._flee_target):
            return self._flee_target
        self._flee_target = _nearest_enter_threat(belief)
        return self._flee_target

    def _clear_flee(self) -> None:
        self._flee_target = None


def _recent_self_kill(belief: Belief) -> bool:
    return belief.last_kill_tick is not None and belief.last_tick - belief.last_kill_tick < EVADE_TICKS


def _be_dumb_enabled() -> bool:
    return _truthy_env("CREWBORG_BE_DUMB") or _truthy_env("BE_DUMB")


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _threat_approaching(belief: Belief) -> bool:
    return _nearest_enter_threat(belief) is not None


def _nearest_enter_threat(belief: Belief) -> str | None:
    self_xy = _self_xy(belief)
    if self_xy is None:
        return None
    candidates: list[tuple[int, str]] = []
    for color in belief.believed_imposters:
        record = _fresh_believed_record(belief, color)
        if record is None:
            continue
        dist2 = _dist2(self_xy, (record.world_x, record.world_y))
        if dist2 <= FLEE_ENTER_SQ:
            candidates.append((dist2, color))
    if not candidates:
        return None
    return min(candidates)[1]


def _should_continue_flee(belief: Belief, color: str) -> bool:
    self_xy = _self_xy(belief)
    record = _fresh_believed_record(belief, color)
    if self_xy is None or record is None:
        return False
    return _dist2(self_xy, (record.world_x, record.world_y)) <= FLEE_EXIT_SQ


def _fresh_believed_record(belief: Belief, color: str) -> PlayerRecord | None:
    if color not in belief.believed_imposters:
        return None
    record = belief.roster.get(color)
    if record is None or record.life_status == "dead":
        return None
    if belief.last_tick - record.last_seen_tick > FLEE_STALE_TICKS:
        return None
    return record


def _self_xy(belief: Belief) -> tuple[int, int] | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
