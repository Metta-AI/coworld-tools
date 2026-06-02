"""Unit tests for the crewborg domain-event tracer (events.py).

The tracer is the runtime's ``on_step_complete`` hook; here we drive it directly
with fabricated :class:`StepContext` values and assert the ``domain.*`` events and
counters it emits through an :class:`EventEmitter` bound to list sinks.
"""

from __future__ import annotations

from players.crewrift.crewborg.action import BTN_A, BTN_B, BTN_LEFT
from players.crewrift.crewborg.events import CrewborgEventTracer
from players.crewrift.crewborg.strategy.suspicion import VOTE_PROBABILITY
from players.crewrift.crewborg.types import ActionState, Belief, BodyEntry, Command, Intent
from players.player_sdk import EventEmitter, ListMetricsSink, ListTraceSink, StepContext


class _Harness:
    """A tracer plus list sinks and a tick-advancing StepContext builder."""

    def __init__(self, *, debug: bool | None = None) -> None:
        self.trace = ListTraceSink()
        self.metrics = ListMetricsSink()
        self.emit = EventEmitter(self.trace, self.metrics, tick=0)
        # Pin debug explicitly (default off) so an ambient CREWBORG_TRACE=debug in the
        # test environment can't perturb the lean-mode assertions.
        self.tracer = CrewborgEventTracer(debug=bool(debug))

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

    def gauges(self, name: str) -> list:
        return [s for s in self.metrics.samples if s.name == name and s.kind == "gauge"]


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


# --- knowledge layer: per-player event log + suspicion reasoning -----------


def _crewmate_belief(**kwargs) -> Belief:
    return Belief(self_role="crewmate", total_player_count=8, **kwargs)


def test_player_event_emitted_for_each_newly_opened_interval() -> None:
    from players.crewrift.crewborg.types import PlayerEvent, PlayerRecord

    h = _Harness()
    belief = Belief()
    record = belief.roster["red"] = PlayerRecord(color="red")
    record.events.append(PlayerEvent(kind="vent", start_tick=5, end_tick=5, region_index=2))
    h.step(belief=belief)
    # Extending the open interval (same list length) emits nothing new...
    record.events[0].end_tick = 9
    h.step(belief=belief)
    # ...a freshly opened interval does.
    record.events.append(PlayerEvent(kind="near_body", start_tick=10, end_tick=10, target_color="green", min_dist=7))
    h.step(belief=belief)

    events = h.events("domain.player_event")
    assert [(e.data["kind"], e.data["color"]) for e in events] == [("vent", "red"), ("near_body", "red")]
    assert events[1].data["min_dist"] == 7
    assert [s.tags["kind"] for s in h.counters("domain.player_event")] == ["vent", "near_body"]


def test_player_died_fires_once_on_the_alive_to_dead_edge() -> None:
    from players.crewrift.crewborg.types import PlayerRecord

    h = _Harness()
    belief = Belief()
    record = belief.roster["blue"] = PlayerRecord(color="blue", life_status="alive")
    h.step(belief=belief)  # alive: nothing
    record.mark_dead(tick=40, source="body", body_xy=(120, 80))
    h.step(belief=belief)  # edge
    h.step(belief=belief)  # still dead: no re-emit

    [event] = h.events("domain.player_died")
    assert event.data == {"color": "blue", "source": "body", "death_tick": 40, "body_xy": [120, 80]}
    assert len(h.counters("domain.player_died")) == 1


def test_imposter_confirmed_and_believed_changed_on_set_moves() -> None:
    h = _Harness()
    belief = _crewmate_belief()
    h.step(belief=belief)  # empty: nothing

    belief.confirmed_imposters = {"red"}
    belief.suspicion = {"red": 0.999}
    belief.believed_imposters = {"red"}
    h.step(belief=belief)

    [confirmed] = h.events("domain.imposter_confirmed")
    assert confirmed.data["color"] == "red"
    [changed] = h.events("domain.believed_changed")
    assert changed.data == {"added": ["red"], "removed": [], "believed": ["red"]}

    # Believed set shrinking is reported too; confirmed (a fixed latent) is not re-emitted.
    belief.believed_imposters = set()
    h.step(belief=belief)
    assert h.events("domain.believed_changed")[-1].data["removed"] == ["red"]
    assert len(h.events("domain.imposter_confirmed")) == 1


def test_suspicion_snapshot_once_per_meeting_with_ranking_and_vote() -> None:
    from players.crewrift.crewborg.types import PlayerEvent, PlayerRecord

    h = _Harness()
    belief = _crewmate_belief(phase="Playing")
    red = belief.roster["red"] = PlayerRecord(color="red", life_status="alive")
    red.events.append(PlayerEvent(kind="near_body", start_tick=3, end_tick=6, target_color="green", min_dist=5))
    belief.roster["blue"] = PlayerRecord(color="blue", life_status="alive")
    belief.suspicion = {"red": 0.91, "blue": 0.12}
    belief.believed_imposters = {"red"}
    h.step(belief=belief)  # Playing: no snapshot

    belief.phase = "Voting"
    h.step(belief=belief)  # meeting opens: snapshot
    h.step(belief=belief)  # still Voting: no re-emit

    [snap] = h.events("domain.suspicion_snapshot")
    assert [r["color"] for r in snap.data["ranking"]] == ["red", "blue"]  # sorted desc by P
    assert snap.data["would_vote"] == "red"
    assert snap.data["would_vote_p"] == 0.91
    assert snap.data["vote_bar"] == VOTE_PROBABILITY
    assert snap.data["ranking"][0]["events"][0] == {
        "kind": "near_body", "dur": 4, "target": "green", "region": None, "min_dist": 5,
    }

    # Leaving and re-entering Voting arms a second snapshot.
    belief.phase = "Playing"
    h.step(belief=belief)
    belief.phase = "Voting"
    h.step(belief=belief)
    assert len(h.events("domain.suspicion_snapshot")) == 2


def test_suspicion_snapshot_skipped_when_no_suspicion() -> None:
    # An imposter / ghost has its suspicion cleared, so a meeting yields no snapshot.
    h = _Harness()
    belief = Belief(self_role="imposter", phase="Voting")
    h.step(belief=belief)
    assert not h.events("domain.suspicion_snapshot")


def test_debug_tick_dump_is_gated() -> None:
    off = _Harness(debug=False)
    belief = _crewmate_belief(phase="Playing")
    belief.suspicion = {"red": 0.4, "blue": 0.2}
    belief.believed_imposters = set()
    off.step(belief=belief)
    assert not off.events("domain.suspicion_tick")
    assert not off.gauges("domain.suspicion.top_p")

    on = _Harness(debug=True)
    on.step(belief=belief)
    [tick] = on.events("domain.suspicion_tick")
    assert tick.data["p"] == {"red": 0.4, "blue": 0.2}
    assert on.gauges("domain.suspicion.top_p")[0].value == 0.4
    assert on.gauges("domain.suspicion.believed_count")[0].value == 0.0


def test_env_flag_enables_debug_dump(monkeypatch) -> None:
    monkeypatch.setenv("CREWBORG_TRACE", "debug")
    tracer = CrewborgEventTracer()
    assert tracer._debug is True
    monkeypatch.setenv("CREWBORG_TRACE", "")
    assert CrewborgEventTracer()._debug is False


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
