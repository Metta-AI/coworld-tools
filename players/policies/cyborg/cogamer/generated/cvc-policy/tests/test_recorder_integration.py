"""Integration tests that drive CvCPolicyImpl.step_with_state with stubbed
programs and GameState to verify recorder emissions."""

from __future__ import annotations

from typing import Any

from cvc_policy.cogamer_policy import CvCAgentState, CvCPolicyImpl
from cvc_policy.programs import Program
from cvc_policy.recorder import EventRecorder
from mettagrid.simulator import Action
from tests.conftest import _fake_policy_env_info


class _StubEngine:
    def __init__(self) -> None:
        self._llm_objective: str | None = None
        self._current_target_position: tuple[int, int] | None = None
        self._current_target_kind: str | None = None


class _StubGameState:
    def __init__(self) -> None:
        self.role: str = "miner"
        self.step_index: int = 0
        self.resource_bias: str | None = None
        self.engine = _StubEngine()
        self.finalized: list[str] = []

    def process_obs(self, obs: Any) -> None:
        self.step_index += 1

    def finalize_step(self, summary: str) -> None:
        self.finalized.append(summary)


def _make_impl(
    desired_role: str = "miner",
    summary: str = "mine_carbon",
    action_name: str = "noop",
) -> tuple[CvCPolicyImpl, CvCAgentState]:
    recorder = EventRecorder()
    programs = {
        "desired_role": Program(executor="code", fn=lambda gs: desired_role),
        "step": Program(
            executor="code", fn=lambda gs: (Action(action_name), summary)
        ),
        "summarize": Program(executor="code", fn=lambda gs: {"role": gs.role}),
    }
    impl = CvCPolicyImpl(
        _fake_policy_env_info(),
        agent_id=0,
        programs=programs,
        llm_client=None,
        recorder=recorder,
    )
    state = CvCAgentState(game_state=_StubGameState())  # type: ignore[arg-type]
    return impl, state


def test_step_emits_action_event_on_change():
    impl, state = _make_impl()
    for _ in range(3):
        impl.step_with_state(object(), state)
    action_events = [e for e in impl._recorder.events if e["type"] == "action"]
    # Same action repeated — only emitted once (on first tick).
    assert len(action_events) == 1
    assert action_events[0]["payload"]["role"] == "miner"
    assert action_events[0]["agent"] == 0
    assert action_events[0]["stream"] == "py"


def test_role_change_event_fires_on_transition():
    impl, state = _make_impl(desired_role="aligner")
    # initial role on stub gs is "miner"
    impl.step_with_state(object(), state)
    events = impl._recorder.events
    changes = [e for e in events if e["type"] == "role_change"]
    assert len(changes) == 1
    assert changes[0]["payload"] == {"from": "miner", "to": "aligner"}
    assert changes[0]["agent"] == 0


def test_no_role_change_event_when_role_stable():
    impl, state = _make_impl(desired_role="miner")
    impl.step_with_state(object(), state)
    impl.step_with_state(object(), state)
    assert [e for e in impl._recorder.events if e["type"] == "role_change"] == []


def test_recorder_step_advances():
    impl, state = _make_impl()
    impl.step_with_state(object(), state)
    impl.step_with_state(object(), state)
    # Recorder's internal step counter advances each tick.
    assert impl._recorder._step == 2


def _make_impl_with_target(kind: str, pos: tuple[int, int]):
    impl, state = _make_impl()

    original_step = impl._programs["step"].fn

    def step_with_target(gs):
        gs.engine._current_target_kind = kind
        gs.engine._current_target_position = pos
        return original_step(gs)

    impl._programs["step"].fn = step_with_target
    return impl, state


def test_target_event_when_target_chosen():
    impl, state = _make_impl_with_target("carbon_extractor", (5, 5))
    impl.step_with_state(object(), state)
    targets = [e for e in impl._recorder.events if e["type"] == "target"]
    assert len(targets) == 1
    assert targets[0]["payload"]["kind"] == "carbon_extractor"
    assert targets[0]["payload"]["pos"] == [5, 5]


def test_no_target_event_when_no_target():
    impl, state = _make_impl()
    impl.step_with_state(object(), state)
    assert [e for e in impl._recorder.events if e["type"] == "target"] == []


def test_no_heartbeat_events_recorded():
    """Heartbeats feed the LLM queue only, not the recorder."""
    impl, state = _make_impl()
    for _ in range(400):
        impl.step_with_state(object(), state)
    heartbeats = [e for e in impl._recorder.events if e["type"] == "heartbeat"]
    assert len(heartbeats) == 0


def test_policyinfos_carries_role_and_summary():
    impl, state = _make_impl()
    impl.step_with_state(object(), state)
    # Minimal mettascope-compatible policy_info: role + summary.
    assert impl._infos.get("role") == "miner"
    assert "summary" in impl._infos
    # Events still appear in the recorder (and events.json), not in infos.
    types = [e["type"] for e in impl._recorder.events]
    assert "action" in types


def test_inventory_event_emits_team_and_team_resources():
    """The per-tick `inventory` event exposes team id, shared team inventory,
    and junction counts so the viewer can group agents by team."""
    impl, state = _make_impl()

    class _FakeAttrs:
        def get(self, k: str, default: Any = None) -> Any:
            return {"team": "team_blue"}.get(k, default)

    class _FakeSelf:
        attributes = _FakeAttrs()
        inventory = {"hp": 80, "carbon": 3, "energy": 40}

    class _FakeTeamSummary:
        shared_inventory = {"carbon": 12, "oxygen": 4, "heart": 1}

    class _FakeMgState:
        self_state = _FakeSelf()
        team_summary = _FakeTeamSummary()

    # Attach to stub gs + provide a known_junctions hook that returns a stub
    # list so the junction-counting branch fires.
    class _Junction:
        def __init__(self, owner: str | None) -> None:
            self.owner = owner

    def known_junctions(pred: Any = None) -> list[Any]:
        js = [_Junction("team_blue"), _Junction("team_red"), _Junction(None)]
        if pred is None:
            return js
        return [j for j in js if pred(j)]

    gs = state.game_state
    gs.mg_state = _FakeMgState()  # type: ignore[attr-defined]
    gs.position = (10, 20)  # type: ignore[attr-defined]
    gs.known_junctions = known_junctions  # type: ignore[attr-defined]

    impl.step_with_state(object(), state)
    inv_events = [e for e in impl._recorder.events if e["type"] == "inventory"]
    assert len(inv_events) == 1
    p = inv_events[0]["payload"]
    assert p["team"] == "team_blue"
    assert p["team_resources"] == {"carbon": 12, "oxygen": 4, "heart": 1}
    assert p["junctions"] == {"friendly": 1, "enemy": 1, "neutral": 1}


def test_inventory_event_omits_team_fields_cleanly_when_unavailable():
    """When team_summary is None and attributes lack `team`, the payload
    omits `team`, `team_resources`, and `junctions` rather than crashing."""
    impl, state = _make_impl()

    class _FakeAttrs:
        def get(self, k: str, default: Any = None) -> Any:
            return default

    class _FakeSelf:
        attributes = _FakeAttrs()
        inventory = {"hp": 50}

    class _FakeMgState:
        self_state = _FakeSelf()
        team_summary = None

    state.game_state.mg_state = _FakeMgState()  # type: ignore[attr-defined]
    impl.step_with_state(object(), state)
    inv_events = [e for e in impl._recorder.events if e["type"] == "inventory"]
    assert len(inv_events) == 1
    p = inv_events[0]["payload"]
    assert "team" not in p
    assert "team_resources" not in p
    assert "junctions" not in p


def test_cap_discovered_fires_with_kind_heart_on_aligner_plateau():
    """When the aligner's heart count plateaus after a pickup attempt, a
    `cap_discovered` event with `payload.kind == "heart"` fires via the
    HeartCapTracker callback plumbed through CvCPolicyImpl."""
    impl, state = _make_impl()
    # Driving the tracker directly proves the end-to-end wiring: constructor
    # forwards on_heart_cap_discovery → CogletAgentPolicy → HeartCapTracker,
    # whose callback emits the recorder event with kind=heart.
    gs = impl.initial_agent_state().game_state
    # `gs` is a real GameState here (not the stub); drive its tracker.
    for i, h in enumerate([0, 1, 2, 3, 3]):
        gs.engine._heart_cap.observe(
            gear_sig=("aligner",), hearts=h, tried_pickup_last_tick=i > 0
        )
    heart_caps = [
        e for e in impl._recorder.events
        if e["type"] == "cap_discovered" and e["payload"].get("kind") == "heart"
    ]
    assert len(heart_caps) == 1
    assert heart_caps[0]["payload"]["gear_sig"] == ["aligner"]
    assert heart_caps[0]["payload"]["cap"] == 3


def test_cap_discovered_cargo_kind_still_emits():
    """Regression: the pre-existing cargo-cap callback must still fire with
    payload.kind == 'cargo'."""
    impl, state = _make_impl()
    gs = impl.initial_agent_state().game_state
    for i, c in enumerate([0, 10, 20, 30, 40, 40]):
        gs.engine._cargo_cap.observe(
            gear_sig=("miner",), cargo=c, mined_last_tick=i > 0
        )
    cargo_caps = [
        e for e in impl._recorder.events
        if e["type"] == "cap_discovered" and e["payload"].get("kind") == "cargo"
    ]
    assert len(cargo_caps) == 1
    assert cargo_caps[0]["payload"]["cap"] == 40


def test_policyinfos_does_not_leak_across_agents():
    # Two impls sharing the same recorder — each agent's `_infos` reflects
    # only that agent's tick-local policy state (role + summary), never
    # the other agent's data.
    recorder = EventRecorder()
    def mkimpl(aid, role):
        programs = {
            "desired_role": Program(executor="code", fn=lambda gs: role),
            "step": Program(executor="code", fn=lambda gs: (Action("noop"), f"sum{aid}")),
            "summarize": Program(executor="code", fn=lambda gs: {"role": role}),
        }
        return CvCPolicyImpl(
            _fake_policy_env_info(),
            agent_id=aid,
            programs=programs,
            llm_client=None,
            recorder=recorder,
        )

    impl0 = mkimpl(0, "miner")
    impl1 = mkimpl(1, "aligner")
    s0 = CvCAgentState(game_state=_StubGameState())  # type: ignore[arg-type]
    s1 = CvCAgentState(game_state=_StubGameState())  # type: ignore[arg-type]
    impl0.step_with_state(object(), s0)
    impl1.step_with_state(object(), s1)
    assert impl0._infos["role"] == "miner"
    assert impl0._infos["summary"] == "sum0"
    assert impl1._infos["role"] == "aligner"
    assert impl1._infos["summary"] == "sum1"
