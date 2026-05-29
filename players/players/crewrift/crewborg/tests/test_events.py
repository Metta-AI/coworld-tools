"""Unit tests for the crewborg domain-event tracer (events.py).

The tracer is the runtime's ``on_step_complete`` hook; here we drive it directly
with fabricated :class:`StepContext` values and assert the ``domain.*`` events and
counters it emits through an :class:`EventEmitter` bound to list sinks.
"""

from __future__ import annotations

from players.crewrift.crewborg.action import BTN_A, BTN_B, BTN_LEFT
from players.crewrift.crewborg.events import CrewborgEventTracer
from players.crewrift.crewborg.types import ActionState, Belief, BodyEntry, Command, Intent
from players.player_sdk import EventEmitter, ListMetricsSink, ListTraceSink, StepContext


class _Harness:
    """A tracer plus list sinks and a tick-advancing StepContext builder."""

    def __init__(self) -> None:
        self.trace = ListTraceSink()
        self.metrics = ListMetricsSink()
        self.emit = EventEmitter(self.trace, self.metrics, tick=0)
        self.tracer = CrewborgEventTracer()

    def step(
        self,
        *,
        belief: Belief | None = None,
        action_state: ActionState | None = None,
        intent: Intent | None = None,
        command: Command | None = None,
    ) -> None:
        self.emit.tick += 1
        context: StepContext[Belief, ActionState, Intent, Command] = StepContext(
            tick=self.emit.tick,
            belief=belief if belief is not None else Belief(),
            action_state=action_state if action_state is not None else ActionState(),
            intent=intent if intent is not None else Intent(kind="idle"),
            command=command if command is not None else Command(),
            active_mode_name="test",
            emit=self.emit,
        )
        self.tracer(context)

    def events(self, name: str) -> list:
        return [event for event in self.trace.events if event.name == name]

    def counters(self, name: str) -> list:
        return [s for s in self.metrics.samples if s.name == name and s.kind == "counter"]


def test_events_are_domain_prefixed_and_carry_runtime_tick() -> None:
    h = _Harness()
    belief = Belief(phase="Playing")
    h.step(belief=belief)  # tick 1: unknown -> Playing

    [event] = h.events("domain.phase_change")
    assert event.tick == 1
    assert event.data == {"from": "unknown", "to": "Playing"}


def test_phase_change_fires_once_per_transition() -> None:
    h = _Harness()
    h.step(belief=Belief(phase="Playing"))
    h.step(belief=Belief(phase="Playing"))  # no change
    h.step(belief=Belief(phase="Voting"))

    changes = h.events("domain.phase_change")
    assert [e.data["to"] for e in changes] == ["Playing", "Voting"]


def test_role_resolved_emitted_once() -> None:
    h = _Harness()
    h.step(belief=Belief(self_role=None))
    h.step(belief=Belief(self_role="imposter"))
    h.step(belief=Belief(self_role="imposter"))

    [event] = h.events("domain.role_resolved")
    assert event.data == {"role": "imposter"}


def test_body_sighted_once_per_body_with_counter() -> None:
    h = _Harness()
    belief = Belief()
    belief.bodies[2003] = BodyEntry(object_id=2003, color="green", world_x=110, world_y=100, first_seen_tick=1)
    h.step(belief=belief)
    h.step(belief=belief)  # same body still present: no re-emit

    [event] = h.events("domain.body_sighted")
    assert event.data == {"body_id": 2003, "color": "green", "world_x": 110, "world_y": 100}
    assert len(h.counters("domain.body_sighted")) == 1


def test_task_completed_on_set_growth() -> None:
    h = _Harness()
    belief = Belief(crew_tasks_remaining=5)
    belief.completed_task_indices = {2}
    h.step(belief=belief)
    belief.completed_task_indices = {2, 7}
    h.step(belief=belief)

    completed = h.events("domain.task_completed")
    assert [e.data["task_index"] for e in completed] == [2, 7]
    assert completed[1].data["crew_tasks_remaining"] == 5
    assert len(h.counters("domain.task_completed")) == 2


def test_kill_landed_on_cooldown_edge() -> None:
    h = _Harness()
    h.step(belief=Belief(self_role="imposter", last_kill_tick=None))
    belief = Belief(self_role="imposter", last_kill_tick=12, self_world_x=300, self_world_y=200)
    h.step(belief=belief)
    h.step(belief=belief)  # same kill tick: no re-emit

    [event] = h.events("domain.kill_landed")
    assert event.data == {"world_x": 300, "world_y": 200}
    assert len(h.counters("domain.kill_landed")) == 1


def test_vote_cast_fires_once_per_meeting() -> None:
    h = _Harness()
    h.step(action_state=ActionState(vote_confirmed=False))
    h.step(action_state=ActionState(vote_confirmed=True))  # cast
    h.step(action_state=ActionState(vote_confirmed=True))  # still held: no re-emit
    h.step(action_state=ActionState(vote_confirmed=False))  # action layer reset (intent changed)
    h.step(action_state=ActionState(vote_confirmed=True))  # next meeting cast

    assert len(h.events("domain.vote_cast")) == 2
    assert len(h.counters("domain.vote_cast")) == 2


def test_task_started_on_new_target_and_resume_after_interruption() -> None:
    h = _Harness()
    h.step(intent=Intent(kind="complete_task", task_index=4))
    h.step(intent=Intent(kind="complete_task", task_index=4))  # same target: no re-emit
    h.step(intent=Intent(kind="complete_task", task_index=9))  # new target
    h.step(intent=Intent(kind="flee_from", target_id=1))  # interruption clears the latch
    h.step(intent=Intent(kind="complete_task", task_index=9))  # resume counts as a new start

    started = h.events("domain.task_started")
    assert [e.data["task_index"] for e in started] == [4, 9, 9]


def test_kill_attempted_requires_the_a_edge_in_the_command() -> None:
    h = _Harness()
    # Navigating toward the target (d-pad held, no A) is not an attempt.
    h.step(intent=Intent(kind="kill", target_id=1007), command=Command(held_mask=BTN_LEFT))
    assert not h.events("domain.kill_attempted")

    # The fresh A press is the attempt.
    h.step(intent=Intent(kind="kill", target_id=1007), command=Command(held_mask=BTN_A))
    [event] = h.events("domain.kill_attempted")
    assert event.data == {"target_id": 1007}
    assert len(h.counters("domain.kill_attempted")) == 1


def test_report_vent_and_chat_attempts() -> None:
    h = _Harness()
    h.step(intent=Intent(kind="report", target_id=2003), command=Command(held_mask=BTN_A))
    h.step(intent=Intent(kind="vent", target_id=0), command=Command(held_mask=BTN_B))
    h.step(intent=Intent(kind="chat", text="no read, skipping"), command=Command(chat="no read, skipping"))

    assert h.events("domain.report_attempted")[0].data == {"body_id": 2003}
    assert h.events("domain.vent_attempted")
    assert h.events("domain.chat_sent")[0].data == {"text": "no read, skipping"}


def test_build_runtime_wires_the_tracer_as_on_step_complete() -> None:
    from players.crewrift.crewborg import build_runtime

    runtime = build_runtime()
    assert isinstance(runtime.on_step_complete, CrewborgEventTracer)


def test_domain_event_flows_through_a_real_runtime_step() -> None:
    """End-to-end: a real step drives the hook and routes through the trace sink."""

    from players.crewrift.crewborg import build_runtime
    from players.crewrift.crewborg.coworld.scene import SceneState
    from players.crewrift.crewborg.tests import sprite_wire as w
    from players.crewrift.crewborg.types import Observation

    trace = ListTraceSink()
    runtime = build_runtime(trace_sink=trace)
    scene = SceneState()
    scene.apply(w.clear_objects())
    scene.apply(w.define_sprite(50, 1, 1, "STARTING"))  # interstitial text => Lobby
    scene.apply(w.define_object(9000, 10, 10, 0, 0, 50))
    scene.tick += 1
    runtime.step(Observation(scene=scene, tick=scene.tick))
    runtime.close()

    phase_events = [e for e in trace.events if e.name == "domain.phase_change"]
    assert phase_events
    assert phase_events[0].data == {"from": "unknown", "to": "Lobby"}
    assert phase_events[0].tick == 1
