"""Rule-based mode selector (design §10).

A deterministic ``decide(snapshot) -> ModeDirective`` run every tick via
``SynchronousStrategyRunner`` — pure rules over belief. Because it runs every
tick, transitions are re-evaluated each cycle (no reflexes).

Crewmate priority order (design §10):

1. ``phase == Voting`` → Attend Meeting
2. with ``CREWBORG_DICK_MODE=1``, once the first kill cooldown is near ready →
   Dick Mode (call the emergency button, taunt only if that call opens the
   meeting, then resume tasking)
3. a body in view → Report Body (a meeting protects us; outranks fleeing)
4. a believed imposter approaching → Flee, with hysteresis so we do not bounce
   back to tasks while skirting the trigger radius
5. ``phase == Playing`` → Normal (ghosts included — they finish their own tasks)
6. otherwise → idle

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

Crewmate nuisance experiment: ``CREWBORG_DICK_MODE=1`` (or ``DICK_MODE=1``)
interrupts normal tasking once per game, far enough before the first kill
cooldown clears that a worst-case walk to the emergency button should still land
with a small buffer. The selector switches to ``dick_mode`` until either our
button press opens the emergency meeting or the attempt times out.
"""

from __future__ import annotations

import os

from players.crewrift.crewborg.strategy.meeting import MeetingParams, read_meeting_params_from_env
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
# Conservative upper bound for walking from the far side of Croatoan to the bridge
# emergency button. Croatoan is 1235x659 px (diagonal ≈1400 px); with MaxSpeed
# 704/256≈2.75 px/tick the straight-line bound is ≈510 ticks, rounded up for path
# shape, controller settling, and route churn.
DICK_MAX_BUTTON_TRAVEL_TICKS = 600
# Start the button run this many ticks before the kill cooldown would clear after
# the worst-case walk.
DICK_KILL_COOLDOWN_BUFFER_TICKS = 10
# Once the action layer has actually pressed A on the emergency button, wait this
# long for a meeting before assuming the server refused the call (for example,
# because ButtonCalls is already spent) and resuming normal tasking.
DICK_CALL_NO_MEETING_GRACE_TICKS = 48


class RuleBasedStrategy:
    def __init__(
        self,
        *,
        be_dumb: bool | None = None,
        meeting_params: MeetingParams | None = None,
        dick_enabled: bool | None = None,
    ) -> None:
        self._be_dumb = be_dumb if be_dumb is not None else _be_dumb_enabled()
        self._meeting_params = meeting_params if meeting_params is not None else read_meeting_params_from_env()
        self._dick_enabled = dick_enabled if dick_enabled is not None else _dick_mode_enabled()
        self._flee_target: str | None = None
        self._dick_state: str = "idle"
        self._dick_call_started_tick: int | None = None
        self._dick_button_spent = False

    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> ModeDirective:
        with snapshot.read() as memory:
            belief = memory.belief
            directive = self._select(belief, memory.action_state)
        return directive

    def _select(self, belief: Belief, action_state: ActionState) -> ModeDirective:
        phase = belief.phase

        if phase == "Voting":
            self._clear_flee()
            if self._dick_state == "calling":
                if self._did_press_emergency_button(action_state):
                    self._dick_state = "meeting"
                else:
                    self._finish_dick_attempt()
            if self._dick_state == "meeting":
                return ModeDirective(mode="dick_mode", source="strategy", reason="dick mode: emergency meeting")
            return ModeDirective(
                mode="attend_meeting",
                params=self._meeting_params,
                source="strategy",
                reason="meeting open",
            )

        if phase == "Playing":
            if self._dick_state == "meeting":
                self._finish_dick_attempt()
            # A crewmate ghost can't report or be threatened; it only finishes its
            # own tasks (design §7.3), so it goes straight to Normal.
            if belief.self_role == "dead":
                self._clear_flee()
                self._reset_dick_mode()
                return ModeDirective(mode="normal", source="strategy", reason="ghost: finish own tasks")
            if belief.self_role == "imposter":
                self._clear_flee()
                self._reset_dick_mode()
                return self._select_imposter(belief)
            # Live crewmate (or not-yet-known role): full field priority. Reporting a
            # visible body outranks fleeing — a meeting protects us and lets the crew
            # act, which beats running from a suspect we could instead report.
            if self._dick_state == "calling":
                if self._dick_call_timed_out(belief, action_state):
                    self._finish_dick_attempt()
                else:
                    return ModeDirective(mode="dick_mode", source="strategy", reason="dick mode: call meeting")
            if self._should_start_dick_mode(belief):
                self._dick_state = "calling"
                self._dick_call_started_tick = belief.last_tick
                self._dick_button_spent = True
                self._clear_flee()
                return ModeDirective(mode="dick_mode", source="strategy", reason="dick mode: kill cooldown reset")
            if any(bid in belief.bodies for bid in belief.visible_body_ids):
                self._clear_flee()
                return ModeDirective(mode="report_body", source="strategy", reason="body in view")
            if self._sticky_flee_target(belief) is not None:
                return ModeDirective(mode="flee", source="strategy", reason="believed imposter near")
            self._clear_flee()
            return ModeDirective(mode="normal", source="strategy", reason="playing: do tasks")

        # All non-play phases (RoleReveal / Lobby / VoteResult / GameOver / unknown).
        self._clear_flee()
        if self._dick_state == "meeting":
            self._finish_dick_attempt()
        elif phase in {"Lobby", "RoleReveal", "GameOver", "unknown"}:
            self._reset_dick_mode()
        return ModeDirective(mode="idle", source="strategy", reason=f"idle in phase {phase}")

    def _select_imposter(self, belief: Belief) -> ModeDirective:
        # Imposter priority (design §10): just killed -> Evade; non-fresh visible
        # body -> Report; kill ready and a victim visible -> Hunt; kill ready or
        # about to be -> Search; else Pretend.
        if self._be_dumb:
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

    def _should_start_dick_mode(self, belief: Belief) -> bool:
        if not self._dick_enabled:
            self._reset_dick_mode()
            return False
        if self._dick_button_spent:
            return False
        if belief.self_role not in {None, "crewmate"}:
            return False
        trigger_window = DICK_MAX_BUTTON_TRAVEL_TICKS + DICK_KILL_COOLDOWN_BUFFER_TICKS
        return ticks_until_kill_ready(belief) <= trigger_window

    def _did_press_emergency_button(self, action_state: ActionState) -> bool:
        if self._dick_call_started_tick is None or action_state.last_call_meeting_attempt_tick is None:
            return False
        return action_state.last_call_meeting_attempt_tick >= self._dick_call_started_tick

    def _dick_call_timed_out(self, belief: Belief, action_state: ActionState) -> bool:
        if self._dick_call_started_tick is None:
            return False
        attempt_tick = action_state.last_call_meeting_attempt_tick
        if attempt_tick is None or attempt_tick < self._dick_call_started_tick:
            return False
        return belief.last_tick - attempt_tick >= DICK_CALL_NO_MEETING_GRACE_TICKS

    def _finish_dick_attempt(self) -> None:
        self._dick_state = "idle"
        self._dick_call_started_tick = None

    def _reset_dick_mode(self) -> None:
        self._dick_state = "idle"
        self._dick_call_started_tick = None
        self._dick_button_spent = False


def _recent_self_kill(belief: Belief) -> bool:
    return belief.last_kill_tick is not None and belief.last_tick - belief.last_kill_tick < EVADE_TICKS


def _be_dumb_enabled() -> bool:
    return _truthy_env("CREWBORG_BE_DUMB") or _truthy_env("BE_DUMB")


def _dick_mode_enabled() -> bool:
    return _truthy_env("CREWBORG_DICK_MODE") or _truthy_env("DICK_MODE")


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
