"""Crewborg domain trace events (design §11).

The SDK runtime emits canonical *framework* boundary events (``perception``,
``belief_updated``, ``action_intent``, ``act_command``, ``mode_*``, …). Those
describe the loop; they can't name game-level happenings. This module derives
Crewrift events — phase transitions, sightings, and the objective/kill/vote
*outcomes* plus the *attempts* behind them — and emits them through the SDK's
domain-event seam (``EventEmitter``, so names are ``domain.``-prefixed and carry
the runtime tick).

``CrewborgEventTracer`` is wired into :func:`...build_runtime` as the runtime's
``on_step_complete`` hook. The runtime calls that hook once per ``step`` after
``perceive`` → ``update_belief`` → ``mode.decide`` → ``resolve_action``, so the
:class:`~players.player_sdk.StepContext` it receives is the single point where
this tick's finalized belief, the mode's chosen intent, and the produced command
all coexist. That matters because:

- *Attempt* events (kill/report/vent/chat) key on the wire ``command`` — the
  actual button edge — which modes never see (they run before the action layer).
- ``task_completed`` is concluded inside Normal mode's ``decide`` (see
  :mod:`...modes.normal`), so it is only visible after the mode has run.

The tracer keeps the previous tick's salient state and emits a trace event (and,
for countable outcomes, a metrics counter) on each transition. It only observes —
it never mutates belief.
"""

from __future__ import annotations

from players.crewrift.crewborg.action import BTN_A, BTN_B
from players.crewrift.crewborg.types import ActionState, Belief, Command, Intent
from players.player_sdk import EventEmitter, StepContext


class CrewborgEventTracer:
    """Derive crewborg domain events from each tick's :class:`StepContext`.

    Usable directly as an ``on_step_complete`` hook: ``on_step_complete=tracer``.
    """

    def __init__(self) -> None:
        # Previous-tick state for edge/delta detection. ``phase`` starts at the
        # Belief default so the first real transition (unknown → …) is reported.
        self._phase: str = "unknown"
        self._role: str | None = None
        self._seen_body_ids: set[int] = set()
        self._completed_task_indices: set[int] = set()
        self._last_kill_tick: int | None = None
        self._vote_confirmed: bool = False
        self._started_task_index: int | None = None

    def __call__(self, context: StepContext[Belief, ActionState, Intent, Command]) -> None:
        belief = context.belief
        emit = context.emit
        self._observe_phase(belief, emit)
        self._observe_role(belief, emit)
        self._observe_bodies(belief, emit)
        self._observe_completed_tasks(belief, emit)
        self._observe_kill_landed(belief, emit)
        self._observe_vote(context.action_state, emit)
        self._observe_action(context.intent, context.command, emit)

    # --- state-transition / outcome events (belief & action-state deltas) ---

    def _observe_phase(self, belief: Belief, emit: EventEmitter) -> None:
        if belief.phase != self._phase:
            emit.event("phase_change", {"from": self._phase, "to": belief.phase})
            self._phase = belief.phase

    def _observe_role(self, belief: Belief, emit: EventEmitter) -> None:
        if self._role is None and belief.self_role is not None:
            self._role = belief.self_role
            emit.event("role_resolved", {"role": belief.self_role})

    def _observe_bodies(self, belief: Belief, emit: EventEmitter) -> None:
        for body_id in sorted(belief.bodies.keys() - self._seen_body_ids):
            body = belief.bodies[body_id]
            self._seen_body_ids.add(body_id)
            emit.event(
                "body_sighted",
                {"body_id": body_id, "color": body.color, "world_x": body.world_x, "world_y": body.world_y},
            )
            emit.counter("body_sighted")

    def _observe_completed_tasks(self, belief: Belief, emit: EventEmitter) -> None:
        for index in sorted(belief.completed_task_indices - self._completed_task_indices):
            emit.event("task_completed", {"task_index": index, "crew_tasks_remaining": belief.crew_tasks_remaining})
            emit.counter("task_completed")
        self._completed_task_indices = set(belief.completed_task_indices)

    def _observe_kill_landed(self, belief: Belief, emit: EventEmitter) -> None:
        # ``last_kill_tick`` advances on the kill-ready → cooldown edge that
        # update_belief records when our own kill lands (imposter only).
        if belief.last_kill_tick is not None and belief.last_kill_tick != self._last_kill_tick:
            self._last_kill_tick = belief.last_kill_tick
            emit.event("kill_landed", {"world_x": belief.self_world_x, "world_y": belief.self_world_y})
            emit.counter("kill_landed")

    def _observe_vote(self, action_state: ActionState, emit: EventEmitter) -> None:
        # vote_confirmed flips False→True the tick the vote is cast, and the action
        # layer resets it when the intent changes — so this fires once per meeting.
        if action_state.vote_confirmed and not self._vote_confirmed:
            emit.event("vote_cast", {})
            emit.counter("vote_cast")
        self._vote_confirmed = action_state.vote_confirmed

    # --- attempt events (intent + the wire command it produced) -------------

    def _observe_action(self, intent: Intent, command: Command, emit: EventEmitter) -> None:
        kind = intent.kind

        # task_started fires when we commit to a new task, and again if we resume
        # one after an interruption (any non-task intent clears the latch).
        if kind == "complete_task":
            if intent.task_index != self._started_task_index:
                self._started_task_index = intent.task_index
                emit.event("task_started", {"task_index": intent.task_index})
        else:
            self._started_task_index = None

        # The remaining events key on the actual button edge in the command, which
        # only the action layer produces (so they cannot live in a mode emitter).
        if kind == "chat" and command.chat is not None:
            emit.event("chat_sent", {"text": command.chat})
            emit.counter("chat_sent")
        elif kind == "kill" and command.held_mask & BTN_A:
            emit.event("kill_attempted", {"target_id": intent.target_id})
            emit.counter("kill_attempted")
        elif kind == "report" and command.held_mask & BTN_A:
            emit.event("report_attempted", {"body_id": intent.target_id})
            emit.counter("report_attempted")
        elif kind in ("vent", "escape") and command.held_mask & BTN_B:
            # ``escape`` presses B only on a vent teleport leg, so a B edge here is a
            # vent use just like the dedicated ``vent`` intent.
            emit.event("vent_attempted", {})
            emit.counter("vent_attempted")
