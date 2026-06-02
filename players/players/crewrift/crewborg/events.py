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

**Knowledge-layer tracing** (the per-player event log + Bayesian suspicion, the
reasoning *behind* the actions): this is the single most useful thing to see when
a live game goes weird ("why did it vote X / never flee the obvious imposter").
The tracer reads it off the finalized belief — keeping ``strategy/`` itself pure —
in two tiers:

- **Always on (deltas + meeting snapshots), lean enough for the tournament:**
  ``player_event`` when a new observation interval opens on someone's log,
  ``player_died`` on an alive→dead transition, ``imposter_confirmed`` /
  ``believed_changed`` when the suspicion sets move, and a full ``suspicion_snapshot``
  (ranked posteriors + each suspect's event log + the would-be vote and the bar)
  at the start of every meeting.
- **Debug only (``CREWBORG_TRACE=debug``):** the entire live ``P(imposter)`` vector
  every tick (``suspicion_tick``) plus ``suspicion.top_p`` / ``believed_count``
  gauges — heavy (~one line per tick), for deep single-game forensics.
"""

from __future__ import annotations

import os

from players.crewrift.crewborg.action import BTN_A, BTN_B
from players.crewrift.crewborg.strategy.suspicion import (
    VOTE_PROBABILITY,
    _prior_imposter_p,
    top_suspect,
)
from players.crewrift.crewborg.types import ActionState, Belief, Command, Intent, PlayerRecord
from players.player_sdk import EventEmitter, StepContext


class CrewborgEventTracer:
    """Derive crewborg domain events from each tick's :class:`StepContext`.

    Usable directly as an ``on_step_complete`` hook: ``on_step_complete=tracer``.
    """

    def __init__(self, *, debug: bool | None = None) -> None:
        # Previous-tick state for edge/delta detection. ``phase`` starts at the
        # Belief default so the first real transition (unknown → …) is reported.
        self._phase: str = "unknown"
        self._role: str | None = None
        self._seen_body_ids: set[int] = set()
        self._completed_task_indices: set[int] = set()
        self._last_kill_tick: int | None = None
        self._vote_confirmed: bool = False
        self._started_task_index: int | None = None

        # Knowledge-layer delta state (per color where noted).
        self._event_counts: dict[str, int] = {}  # color → events logged so far (emit the new tail)
        self._life: dict[str, str] = {}  # color → last-seen life_status (alive→dead edge)
        self._confirmed: set[str] = set()  # last confirmed_imposters (witnessed catches)
        self._believed: set[str] = set()  # last believed_imposters (over the flee bar)
        self._meeting_snapshotted: bool = False  # one suspicion snapshot per meeting
        # Full per-tick suspicion dump is opt-in: heavy, for single-game forensics.
        self._debug: bool = (
            os.environ.get("CREWBORG_TRACE", "").strip().lower() == "debug" if debug is None else debug
        )

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
        # Knowledge layer: the event log + suspicion reasoning behind the actions.
        self._observe_player_events(belief, emit)
        self._observe_deaths(belief, emit)
        self._observe_suspicion_deltas(belief, emit)
        self._observe_meeting_suspicion(belief, emit)
        if self._debug:
            self._observe_debug_tick(belief, emit)

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

    # --- knowledge layer: per-player event log + suspicion reasoning --------

    def _observe_player_events(self, belief: Belief, emit: EventEmitter) -> None:
        """Emit each newly opened observation interval on any player's event log.

        A player's ``events`` list only grows (the open interval is extended in
        place), so the tail past the count we last saw is exactly the intervals
        opened since — the live "started seeing X doing Y" stream.
        """

        for color, record in belief.roster.items():
            seen = self._event_counts.get(color, 0)
            for event in record.events[seen:]:
                emit.event(
                    "player_event",
                    {
                        "color": color,
                        "kind": event.kind,
                        "start_tick": event.start_tick,
                        "target_color": event.target_color,
                        "region_index": event.region_index,
                        "min_dist": event.min_dist,
                    },
                )
                emit.counter("player_event", tags={"kind": event.kind})
            self._event_counts[color] = len(record.events)

    def _observe_deaths(self, belief: Belief, emit: EventEmitter) -> None:
        """Emit an alive/unknown → dead transition for any player (role-agnostic)."""

        for color, record in belief.roster.items():
            if record.life_status == "dead" and self._life.get(color) != "dead":
                emit.event(
                    "player_died",
                    {
                        "color": color,
                        "source": record.death_source,
                        "death_tick": record.death_seen_tick,
                        "body_xy": list(record.body_xy) if record.body_xy is not None else None,
                    },
                )
                emit.counter("player_died", tags={"source": record.death_source or "unknown"})
            self._life[color] = record.life_status

    def _observe_suspicion_deltas(self, belief: Belief, emit: EventEmitter) -> None:
        """Emit moves in the confirmed (witnessed) and believed (over flee bar) sets."""

        for color in sorted(belief.confirmed_imposters - self._confirmed):
            emit.event("imposter_confirmed", {"color": color, "p": round(belief.suspicion.get(color, 1.0), 4)})
            emit.counter("imposter_confirmed")
        self._confirmed = set(belief.confirmed_imposters)

        if belief.believed_imposters != self._believed:
            emit.event(
                "believed_changed",
                {
                    "added": sorted(belief.believed_imposters - self._believed),
                    "removed": sorted(self._believed - belief.believed_imposters),
                    "believed": sorted(belief.believed_imposters),
                },
            )
            self._believed = set(belief.believed_imposters)

    def _observe_meeting_suspicion(self, belief: Belief, emit: EventEmitter) -> None:
        """Snapshot the full suspicion picture once at the start of each meeting.

        The ranked posteriors, each suspect's event log, and the would-be vote
        (``top_suspect`` against the same vote bar Attend Meeting uses) — the one
        record that explains a meeting's vote after the fact.
        """

        if belief.phase != "Voting":
            self._meeting_snapshotted = False
            return
        if self._meeting_snapshotted:
            return
        self._meeting_snapshotted = True
        # Suspicion is crewmate-only (cleared for imposter/ghost), so nothing to show otherwise.
        if not belief.suspicion:
            return
        target = top_suspect(belief)
        ranking = [
            {
                "color": color,
                "p": round(p, 4),
                "confirmed": color in belief.confirmed_imposters,
                "events": _event_summary(belief.roster.get(color)),
            }
            for color, p in sorted(belief.suspicion.items(), key=lambda kv: kv[1], reverse=True)
        ]
        emit.event(
            "suspicion_snapshot",
            {
                "prior": round(_prior_imposter_p(belief), 4),
                "ranking": ranking,
                "confirmed": sorted(belief.confirmed_imposters),
                "believed": sorted(belief.believed_imposters),
                "would_vote": target,
                "would_vote_p": round(belief.suspicion[target], 4) if target is not None else None,
                "vote_bar": VOTE_PROBABILITY,
            },
        )

    def _observe_debug_tick(self, belief: Belief, emit: EventEmitter) -> None:
        """Debug-only: the entire live P(imposter) vector + summary gauges, per tick."""

        if not belief.suspicion:
            return
        emit.event("suspicion_tick", {"p": {c: round(p, 4) for c, p in belief.suspicion.items()}})
        emit.gauge("suspicion.top_p", max(belief.suspicion.values()))
        emit.gauge("suspicion.believed_count", float(len(belief.believed_imposters)))


def _event_summary(record: PlayerRecord | None) -> list[dict[str, object]]:
    """Compact per-player event log for a suspicion snapshot (durations, not spans)."""

    if record is None:
        return []
    return [
        {
            "kind": event.kind,
            "dur": event.duration_ticks,
            "target": event.target_color,
            "region": event.region_index,
            "min_dist": event.min_dist,
        }
        for event in record.events
    ]
