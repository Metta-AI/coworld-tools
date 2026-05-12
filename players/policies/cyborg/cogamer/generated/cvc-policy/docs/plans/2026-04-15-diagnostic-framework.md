# Diagnostic Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land an end-to-end diagnostic framework for the CvC policy:
structured event recording, a standalone `cgp` CLI, programmatic
scenarios with pass/fail assertions, a static HTML replay+logs
viewer, and a coverage audit with CI gate.

**Architecture:** Single `runs/<id>/` folder contract. `EventRecorder`
is the one producer — events fan out to stderr (formatted), JSON file,
and mettagrid's per-step `policyInfos` (so every replay carries our
data). Scenarios and ad-hoc `cgp play` both write run folders; the
viewer renders a self-contained HTML report. Coverage audit happens
after recorder refactor to pick up the new surface.

**Tech Stack:** Python 3.12, Typer (CLI), Pydantic (existing mission
overrides), Jinja2 (viewer), pytest + pytest-cov + hypothesis.

**Source of truth:** `docs/plans/2026-04-15-diagnostic-framework-design.md`.

---

## Batches

1. **Recorder foundation** — replace `LogConfig` with `EventRecorder`,
   wire to stderr + events.json + `policyInfos`; convert every current
   `log.log(...)` site to structured `recorder.emit(...)`.
2. **`cgp` CLI skeleton + scenario harness + 5 initial scenarios.**
3. **HTML viewer** (`cgp view`).
4. **Coverage audit + CI gate + hypothesis property tests.**

Each task is TDD: failing test → verify failure → minimal
implementation → verify pass → commit.

---

# Batch 1 — Recorder foundation

## Task 1.1: EventRecorder skeleton + test harness

**Files:**
- Create: `src/cvc_policy/recorder.py`
- Create: `tests/test_recorder.py`

**Step 1: Write the failing test**

```python
# tests/test_recorder.py
from cvc_policy.recorder import EventRecorder


def test_emit_appends_event_with_step_and_stream():
    rec = EventRecorder()
    rec.set_step(7)
    rec.emit(type="action", agent=0, stream="py", payload={"role": "miner"})
    assert rec.events == [
        {"step": 7, "agent": 0, "stream": "py", "type": "action",
         "payload": {"role": "miner"}}
    ]


def test_emit_without_step_defaults_to_zero():
    rec = EventRecorder()
    rec.emit(type="note", agent=None, stream="py", payload={"text": "hi"})
    assert rec.events[0]["step"] == 0
```

**Step 2: Run test to verify failure**

```bash
.venv/bin/pytest tests/test_recorder.py -v
# Expected: ModuleNotFoundError: cvc_policy.recorder
```

**Step 3: Minimal implementation**

```python
# src/cvc_policy/recorder.py
from __future__ import annotations
from typing import Any


class EventRecorder:
    def __init__(self) -> None:
        self._step = 0
        self.events: list[dict[str, Any]] = []

    def set_step(self, step: int) -> None:
        self._step = step

    def emit(self, *, type: str, agent: int | None, stream: str,
             payload: dict[str, Any]) -> None:
        self.events.append({
            "step": self._step, "agent": agent, "stream": stream,
            "type": type, "payload": dict(payload),
        })
```

**Step 4: Verify pass**

```bash
.venv/bin/pytest tests/test_recorder.py -v
```

**Step 5: Commit**

```bash
git add src/cvc_policy/recorder.py tests/test_recorder.py
git commit -m "recorder: EventRecorder skeleton"
```

---

## Task 1.2: `fmt(event)` — one-liner renderer

**Files:**
- Modify: `src/cvc_policy/recorder.py`
- Modify: `tests/test_recorder.py`

**Step 1: Failing test**

```python
from cvc_policy.recorder import fmt


def test_fmt_action_event():
    ev = {"step": 3, "agent": 0, "stream": "py", "type": "action",
          "payload": {"role": "miner", "summary": "mine_carbon"}}
    assert fmt(ev) == "[py] a0 step=3 action role=miner summary=mine_carbon"


def test_fmt_team_event_has_no_agent_prefix():
    ev = {"step": 10, "agent": None, "stream": "py", "type": "note",
          "payload": {"text": "season changed"}}
    assert fmt(ev) == "[py] step=10 note text='season changed'"


def test_fmt_patch_applied_shows_applied_fields():
    ev = {"step": 500, "agent": 2, "stream": "llm", "type": "patch_applied",
          "payload": {"applied": {"resource_bias": "carbon"}, "rationale": "low supply"}}
    s = fmt(ev)
    assert s.startswith("[llm] a2 step=500 patch_applied")
    assert "resource_bias=carbon" in s
```

**Step 2: Verify failure**

**Step 3: Implement `fmt` with per-type rendering dispatch (dict of
type → callable returning payload-bit). Default: join k=v for all
payload keys, string values quoted if they contain whitespace.**

**Step 4: Verify pass**

**Step 5: Commit** `recorder: fmt(event) renderer`

---

## Task 1.3: Sinks — stderr + `events.json` + `policyInfos`

**Files:**
- Modify: `src/cvc_policy/recorder.py`
- Modify: `tests/test_recorder.py`

**Step 1: Failing tests**

```python
def test_stderr_sink_filters_by_stream(capsys):
    rec = EventRecorder(stderr_streams={"py"})
    rec.emit(type="action", agent=0, stream="py", payload={"role": "miner"})
    rec.emit(type="llm_tool_call", agent=0, stream="llm", payload={"tool": "patch"})
    err = capsys.readouterr().err.splitlines()
    assert any(line.startswith("[py]") for line in err)
    assert not any(line.startswith("[llm]") for line in err)


def test_flush_to_json(tmp_path):
    rec = EventRecorder()
    rec.emit(type="action", agent=0, stream="py", payload={})
    rec.flush_json(tmp_path / "events.json")
    import json
    data = json.loads((tmp_path / "events.json").read_text())
    assert len(data) == 1
    assert data[0]["type"] == "action"


def test_per_step_drain_returns_events_for_current_step():
    rec = EventRecorder()
    rec.set_step(5)
    rec.emit(type="action", agent=0, stream="py", payload={})
    rec.emit(type="role_change", agent=1, stream="py", payload={})
    rec.set_step(6)
    rec.emit(type="action", agent=0, stream="py", payload={})
    events_at_5 = rec.events_for_step(5)
    assert len(events_at_5) == 2
```

**Step 2: Failure**

**Step 3: Implement:**
- `EventRecorder(stderr_streams: set[str] | None = None)` — default empty set.
- `flush_json(path: Path)` — dump self.events.
- `events_for_step(step) -> list[dict]` — scan self.events for matches.
- `emit` writes to stderr via `print(fmt(ev), file=sys.stderr)` if stream in stderr_streams.

**Step 4: Verify**

**Step 5: Commit** `recorder: stderr + json + per-step sinks`

---

## Task 1.4: Recorder factory per policy; retire LogConfig

**Files:**
- Modify: `src/cvc_policy/cogamer_policy.py`
- Modify: `src/cvc_policy/logcfg.py` (delete)
- Modify: `src/cvc_policy/llm_worker.py` (LogConfig → EventRecorder)
- Modify: `tests/agent/test_world_model.py` (remove debug if any)

**Step 1: Failing test** — add `tests/test_cogamer_policy_kwargs.py` for recorder init:

```python
def test_cvc_policy_record_dir_kwarg_creates_recorder(tmp_path, monkeypatch):
    from cvc_policy.cogamer_policy import CvCPolicy
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # no-op; keeps LLM off
    p = CvCPolicy(_fake_policy_env_info(), record_dir=str(tmp_path))
    assert p._recorder is not None
    assert p._recorder._record_dir == str(tmp_path)

def test_cvc_policy_log_py_enables_stderr(capsys):
    p = CvCPolicy(_fake_policy_env_info(), log_py=True)
    p._recorder.emit(type="note", agent=None, stream="py", payload={"text":"hi"})
    assert "[py]" in capsys.readouterr().err
```

(`_fake_policy_env_info` lives in `tests/conftest.py` — add if missing.)

**Step 2: Failure**

**Step 3: Replace LogConfig usage in `cogamer_policy.py`:**
- Import `EventRecorder`.
- In `CvCPolicy.__init__`: replace `self._log = LogConfig(...)` with
  `self._recorder = EventRecorder(stderr_streams=_derive_streams(log, log_py, log_llm), record_dir=record_dir)`.
- Delete `logcfg.py`. Delete `_truthy` helper from cogamer_policy (move into recorder if still needed, or inline).
- Replace `LogConfig` references in `llm_worker.py` with `EventRecorder`.
- Update `CvCPolicyImpl.__init__` to accept `recorder: EventRecorder`.

**Step 4: Verify all existing tests still pass**

```bash
.venv/bin/pytest -q
```

**Step 5: Commit** `recorder: retire LogConfig, route through EventRecorder`

---

## Task 1.5: Instrument `step_with_state` → `action` and `role_change` events

**Files:**
- Modify: `src/cvc_policy/cogamer_policy.py`
- Modify: `tests/test_recorder_integration.py` (new)

**Step 1: Failing test**

```python
# tests/test_recorder_integration.py
def test_step_emits_action_event_per_tick():
    # Using the real policy with a no-op env stub that returns 3 ticks
    impl, state = _make_impl_and_state()
    rec = impl._recorder
    for _ in range(3):
        _, state = impl.step_with_state(_fake_obs(), state)
    action_events = [e for e in rec.events if e["type"] == "action"]
    assert len(action_events) == 3
    assert all(e["payload"].get("role") for e in action_events)


def test_role_change_event_fires_on_transition():
    impl, state = _make_impl_and_state(initial_role="miner", new_role="aligner")
    impl.step_with_state(_fake_obs(), state)
    events = impl._recorder.events
    assert any(e["type"] == "role_change" and e["payload"] == {"from": "miner", "to": "aligner"} for e in events)
```

(Reuses conftest fixtures; stub engine that just returns fixed role and Action.)

**Step 2: Failure**

**Step 3: Replace stderr log lines in `step_with_state` with
`recorder.emit(type="action", ...)` and `recorder.emit(type="role_change", ...)`.

**Step 4: Verify**

**Step 5: Commit** `recorder: emit action and role_change events`

---

## Task 1.6: Instrument `cap_discovered`

**Files:**
- Modify: `src/cvc_policy/agent/cargo_cap.py` (accept optional `on_discovery: Callable[[sig, cap], None]`)
- Modify: `src/cvc_policy/game_state.py` (wire recorder callback into tracker)
- Modify: `tests/agent/test_cargo_cap.py` (callback test)

**Step 1: Failing test**

```python
def test_discovery_callback_fires_once_on_new_cap():
    seen: list[tuple[tuple[str, ...], int]] = []
    tracker = CargoCapTracker(on_discovery=lambda sig, cap: seen.append((sig, cap)))
    for i, c in enumerate([0, 10, 20, 30, 40, 40]):
        tracker.observe(gear_sig=("miner",), cargo=c, mined_last_tick=i > 0)
    assert seen == [(("miner",), 40)]
```

**Step 2: Failure**

**Step 3: Add `on_discovery` param to `CargoCapTracker.__init__`; fire
inside `observe` when a new cap is recorded (not on later false
plateaus). In `game_state.py`, when engine is constructed, pass
`on_discovery=lambda sig, cap: recorder.emit(type="cap_discovered", ...)`.

**Step 4: Verify**

**Step 5: Commit** `recorder: emit cap_discovered via tracker callback`

---

## Task 1.7: Instrument `target` and `heartbeat`

**Files:**
- Modify: `src/cvc_policy/agent/roles.py` (or `targeting.py`) — emit `target` when a role picks a concrete entity
- Modify: `src/cvc_policy/cogamer_policy.py` — emit `heartbeat` on existing cadence
- Modify: `tests/test_recorder_integration.py`

**Step 1: Failing tests**

```python
def test_miner_target_event_when_extractor_chosen():
    # Engine with one visible carbon_extractor at (5,5)
    impl, state = _make_impl_with_extractor(pos=(5, 5))
    impl.step_with_state(_fake_obs(), state)
    events = impl._recorder.events
    targets = [e for e in events if e["type"] == "target"]
    assert len(targets) == 1
    assert targets[0]["payload"]["kind"] == "carbon_extractor"
    assert targets[0]["payload"]["pos"] == (5, 5)


def test_heartbeat_every_N_steps():
    impl, state = _make_impl_and_state()
    for step_idx in range(1, 401):
        _, state = impl.step_with_state(_fake_obs(), state)
    heartbeats = [e for e in impl._recorder.events if e["type"] == "heartbeat"]
    assert len(heartbeats) == 2  # at steps 200, 400
```

**Step 2–5: Failure, implement, verify, commit** `recorder: target + heartbeat events`

---

## Task 1.8: Instrument `llm_tool_call` and `patch_applied`

**Files:**
- Modify: `src/cvc_policy/llm_worker.py`
- Modify: `tests/test_llm_worker.py` (new file)

**Step 1: Failing test**

```python
def test_tool_call_emits_event(fake_anthropic_client):
    worker = _start_worker_with(fake_anthropic_client, agent_id=0)
    fake_anthropic_client.queue_tool_use("read_recent_logs", {})
    fake_anthropic_client.queue_end_turn()
    worker.join(timeout=2)
    tool_events = [e for e in worker._recorder.events if e["type"] == "llm_tool_call"]
    assert tool_events[0]["payload"]["tool"] == "read_recent_logs"


def test_patch_emits_patch_applied():
    ...
```

Use a FakeAnthropicClient that returns scripted responses — mocks not required for core logic but needed here to avoid API calls.

**Step 2–5: Failure, implement, verify, commit** `recorder: llm_tool_call + patch_applied events`

---

## Task 1.9: Wire recorder events to `policyInfos`

**Files:**
- Modify: `src/cvc_policy/cogamer_policy.py` — in `step_with_state`, after emitting events for the tick, copy `recorder.events_for_step(step)` into `self._infos` (per-agent dict key stored via StatefulAgentPolicy).
- Modify: `tests/test_recorder_integration.py` — assert `_infos` is populated.

**Step 1: Failing test**

```python
def test_policyinfos_contains_this_tick_events():
    impl, state = _make_impl_and_state()
    impl.step_with_state(_fake_obs(), state)
    # StatefulAgentPolicy.infos should reflect impl._infos
    assert "events" in state.game_state.engine._infos  # or wherever it lands
```

**Step 2–5** — use the `AgentPolicy._infos` hook; key as `{"events": [...]}`. For mettascope friendliness, also include a `summary` text field (join of fmt() lines).

Commit: `recorder: surface per-tick events via policyInfos`

---

## Task 1.10: Record-dir wiring + episode-end flush

**Files:**
- Modify: `src/cvc_policy/cogamer_policy.py` — `record_dir` kwarg triggers `recorder.flush_json(record_dir / "events.json")` in `_on_episode_end`.
- Modify: `tests/test_cogamer_policy_kwargs.py`

**Step 1: Failing test**

```python
def test_record_dir_writes_events_json(tmp_path, ...):
    p = CvCPolicy(_fake_policy_env_info(), record_dir=str(tmp_path))
    p._recorder.emit(type="note", agent=None, stream="py", payload={"text":"x"})
    p._on_episode_end()
    assert (tmp_path / "events.json").exists()
```

**Step 2–5** — add the flush; commit `recorder: flush events.json on episode end`

---

**Batch 1 checkpoint** — run full suite:

```bash
.venv/bin/pytest -q
```

All 429+ tests pass plus new ones. Push and review before Batch 2.

---

# Batch 2 — `cgp` CLI + scenario harness + 5 scenarios

## Task 2.1: Create `cgp` CLI entry point

**Files:**
- Create: `src/cvc_policy/cli.py`
- Modify: `pyproject.toml` — add `[project.scripts] cgp = "cvc_policy.cli:app"`
- Create: `tests/test_cli.py`

**Step 1: Failing test**

```python
from typer.testing import CliRunner
from cvc_policy.cli import app


def test_cli_exists_with_help():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "scenario" in result.output


def test_scenario_list_prints_empty_initially():
    result = CliRunner().invoke(app, ["scenario", "list"])
    assert result.exit_code == 0
```

**Steps 2–5:** create the typer app skeleton with `scenario`, `view`, `play`, `runs`, `test-cov` groups. Stubs for most; only `scenario list` needs to render the (empty) registry. Commit.

Commit: `cli: cgp skeleton with subcommand groups`

---

## Task 2.2: Scenario dataclass + registry

**Files:**
- Create: `src/cvc_policy/scenarios/__init__.py` (exports `Scenario`, `scenario` decorator, `registry()`)
- Create: `tests/test_scenarios_registry.py`

**Step 1: Failing test**

```python
from cvc_policy.scenarios import Scenario, scenario, registry


def test_decorator_registers_scenario_by_name():
    @scenario
    def my_scenario() -> Scenario:
        return Scenario(name="my_scenario", tier=1, mission="x")
    assert "my_scenario" in registry()


def test_list_sorted_by_tier_then_name():
    ...
```

**Step 2–5:** implement the dataclass (matching §3 of design), module-level registry dict, `scenario` decorator storing the factory. Commit.

---

## Task 2.3: `Run` typed view

**Files:**
- Create: `src/cvc_policy/scenarios/_run.py`
- Create: `tests/test_scenarios_run.py`

**Step 1: Failing test**

Write tests that build a fake run folder (events.json + result.json), load `Run(path)`, and assert helpers:
- `run.events_of_type("action")`
- `run.events_for_agent(0)`
- `run.mining_trips(agent=0)` — segmented list of (start_step, end_step, mine_bump_count, target_pos)
- `run.first_target_for_agent(0)`
- `run.agent_final_inventory(0)`

**Step 2–5** — implement `Run` reading the two files and exposing those helpers. Commit.

---

## Task 2.4: Assertion helpers

**Files:**
- Create: `src/cvc_policy/scenarios/assertions.py`
- Create: `tests/test_scenarios_assertions.py`

Assertion helpers (return `AssertResult` dataclass with `name`, `passed`, `message`, `failed_at_step`):
- `no_crash()`
- `has_action_event_per_agent(cogs)`
- `cap_discovered_by(agent, gear_sig, expected_cap, by_step)`
- `no_target_at(position)`
- `mining_trips_efficient(agent, extract_amount, cap)`
- `map_coverage_at_least(agent, fraction)`

TDD one at a time. Commit after each helper + its test.

---

## Task 2.5: Harness — drive the game via library

**Files:**
- Create: `src/cvc_policy/scenarios/harness.py`
- Create: `tests/test_scenarios_harness.py`

Harness steps:

```python
def run_scenario(s: Scenario, *, steps_override: int | None = None) -> Run:
    run_id = _make_run_id(s.name)
    run_dir = Path("runs") / run_id
    run_dir.mkdir(parents=True)

    # Build env
    game = CvCGame()
    mission = _resolve_mission(s.mission)
    mission = mission.with_variants(list(s.variants))
    for k, v in s.mission_overrides.items():
        mission = mission.model_copy(update={k: v})
    # apply variant_overrides
    for vname, patches in s.variant_overrides.items():
        variant = mission.required_variant(_variant_class(vname))
        for k, v in patches.items():
            setattr(variant, k, v)
    env = mission.make_env(seed=s.seed)

    # setup hook
    if s.setup:
        s.setup(env)

    # policy
    policy = CvCPolicy(
        env.policy_env_info(), record_dir=str(run_dir),
        **s.policy_kwargs,
    )

    # rollout
    steps = steps_override or s.steps
    sim = env.build_simulation([policy])
    sim.run(steps=steps, replay_path=run_dir / "replay.json.z")

    # evaluate assertions
    run = Run(run_dir)
    results = [a(run) for a in s.assertions]
    write_result_json(run_dir, s, results)
    return run
```

Tests: mock the env with a trivial 3-step simulation; assert run folder contents.

Commit: `scenarios: harness.run_scenario with mettagrid library driver`

---

## Task 2.6–2.10: Five scenarios (one task each)

Each adds `src/cvc_policy/scenarios/cases/<name>.py` + a test that runs it and expects `status=passed`.

- 2.6: `smoke_machina1_runs`
- 2.7: `exploration_small` (emit `world_model_summary` first — adjust recorder)
- 2.8: `mining_discovers_cap`
- 2.9: `mining_trip_efficiency`
- 2.10: `empty_extractor_skipped`

Each mark as `@pytest.mark.scenario` (new marker, excluded by default).

Commit per scenario.

---

## Task 2.11: `cgp scenario run` / `run-all` / `list` impl

**Files:**
- Modify: `src/cvc_policy/cli.py`
- Modify: `tests/test_cli.py`

TDD: invoke CLI, assert it creates `runs/<id>/` and prints pass/fail.

Commit: `cli: scenario subcommands`

---

## Task 2.12: `cgp play` with overrides

**Files:**
- Modify: `src/cvc_policy/cli.py`
- Create: `src/cvc_policy/overrides.py` (parse `KEY=VALUE` / `VARIANT.KEY=VALUE` with type coercion int/float/bool/json/str)
- Create: `tests/test_overrides.py`

Tests for override parser:
- `parse_override("num_agents=4") == ("num_agents", 4)`
- `parse_override("ratio=0.5") == ("ratio", 0.5)`
- `parse_override("enabled=true") == ("enabled", True)`
- `parse_override("config={\"k\":1}") == ("config", {"k": 1})`
- `parse_override("name=foo") == ("name", "foo")`

Commit: `cli: cgp play with mission/variant overrides`

---

**Batch 2 checkpoint** — all five scenarios pass; CLI works:

```bash
uv run cgp scenario run-all --tier 1
# Expect: 5 passed
```

Push and review.

---

# Batch 3 — HTML viewer

## Task 3.1: `fmt` exported + viewer package skeleton

**Files:**
- Create: `src/cvc_policy/viewer/__init__.py`, `render.py`
- Create: `src/cvc_policy/viewer/report.html.j2`

Test writes a tiny fake run folder → `render(run_dir) → report.html`.
Assert resulting HTML has the run_id in the header and the event
count matches.

Commit: `viewer: skeleton with jinja template`

---

## Task 3.2: Per-agent timeline strip (static SVG or divs)

HTML/CSS timeline with N rows, colored ticks per event type. Use
inline SVG generated server-side. Test: assert ticks count ==
events count for each agent.

Commit.

---

## Task 3.3: Step scrubber JS + log panel

Client-side JS:
- Slider 0..max_step.
- Currently-selected step highlights events in log panel, highlights
  tick under cursor in each agent row.
- Tabs: All / Py / LLM / Team.
- Text search.

Test: playwright/selenium not worth — instead, assert the JSON blob
embedded in the HTML is well-formed and matches the events.

Commit: `viewer: scrubber + filter tabs`

---

## Task 3.4: Replay card + mettascope deep-link

Render thumbnail placeholder; "Open in mettascope" button shells to
`softmax cogames replay <path>`. Validate the `<a href>` in test.

Commit.

---

## Task 3.5: Failure view + `cgp view` command

- If `result.status=failed`: red banner, clickable failed assertions,
  jumps slider to `failed_at_step`.
- `cgp view <run_id>`: regenerate, open with `webbrowser.open`.

Commit.

---

**Batch 3 checkpoint** — open a scenario run's report in browser,
scrub through events, confirm failure-view works by breaking an
assertion.

Push.

---

# Batch 4 — Coverage audit + gate + property tests

## Task 4.1: Add pytest-cov, cgp test-cov

Add `pytest-cov>=6` and `hypothesis>=6` to dev deps. Implement
`cgp test-cov` that shells `pytest --cov=cvc_policy --cov-report=term-missing`.

Commit: `dev: add pytest-cov + hypothesis`

---

## Task 4.2: Audit pass

Run coverage, list modules <85%, file `docs/coverage-audit.md` with
the gap table. (No code change; a working document.)

Commit the audit doc.

---

## Tasks 4.3–4.6: Fill gaps per under-covered module

One task per module, TDD. Modules to touch based on current suspicion:
- `cvc_policy/agent/main.py`
- `cvc_policy/agent/coglet_policy.py`
- `cvc_policy/agent/navigation.py`
- `cvc_policy/game_state.py`

Each task: add tests to bring module to ≥85% line coverage; mark
untestable glue with `# pragma: no cover` + one-line justification.
Commit per module.

---

## Task 4.7: CI gate

Add `.github/workflows/ci.yml` running:

```yaml
- run: uv sync
- run: uv run pytest --cov=cvc_policy --cov-fail-under=85
```

Commit: `ci: coverage gate at 85%`

---

## Task 4.8: Hypothesis property tests

Property tests for:
- `resource_priority`: invariant — resources sorted ascending by shared_inventory; bias element comes first among ties.
- `CargoCapTracker.observe`: monotonicity — recorded cap never decreases for a given gear_sig.
- `scramble_target_score`: distance-monotonicity within same candidate class.

Commit per property test suite.

---

**Batch 4 checkpoint** — CI passes with coverage gate; property tests
green; coverage-audit.md reflects current state.

---

# Wrap-up

After all four batches land, PR #2 already has the recorder +
scenarios + viewer + coverage. Squash optional. Merge into main.

Deferred items from design doc (§7): Tier 2/3 scenarios, live web
server viewer, mettascope panel — track as follow-up issues.
