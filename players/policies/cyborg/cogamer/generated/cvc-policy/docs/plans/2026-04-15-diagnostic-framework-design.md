# CvC Policy — Diagnostic Framework Design

**Status:** approved via brainstorming 2026-04-15.
**Scope:** three workstreams landing together:
1. Scenario suite (escalating, programmatic pass/fail).
2. HTML report + replay viewer (per-agent, per-team logs).
3. Unit-test coverage audit + gate.

All three share a single **run folder** contract.

## 1. Data model & run layout

Every run (scenario, `cgp play`, or live `softmax cogames play` with
`--policy-args record_dir=...`) produces:

```
runs/<run_id>/
├── replay.json.z       # mettagrid replay
├── events.json         # structured events, sorted by (step, agent)
├── result.json         # scenario metadata + pass/fail + timing
└── report.html         # written by `cgp view`
```

`run_id` = `<scenario_name | "manual">-<yyyyMMdd-HHmmss>`.

### Event schema

```python
{
  "step": int,
  "agent": int | None,          # None for team/global events
  "stream": "py" | "llm",
  "type": str,                  # see type list below
  "payload": {...},             # type-specific
}
```

### Event types (initial, additive)

| type              | stream | payload                                                    |
| ----------------- | ------ | ---------------------------------------------------------- |
| `action`          | py     | `{role, summary, cargo, hp, pos}`                          |
| `role_change`     | py     | `{from, to}`                                               |
| `target`          | py     | `{kind, pos, distance}`                                    |
| `cap_discovered`  | py     | `{gear_sig, cap}`                                          |
| `heartbeat`       | py     | full `summarize()` dict                                    |
| `world_model_summary` | py | `{known_cells, frontier_cells, extractors_known}`         |
| `patch_applied`   | llm    | `{applied, rationale}`                                     |
| `llm_tool_call`   | llm    | `{tool, input, latency_ms}`                                |
| `note`            | any    | `{text}` — escape hatch                                    |
| `error`           | any    | `{where, message}`                                         |

### `result.json`

```python
{
  "run_id": str, "scenario": str | null,
  "started_at": iso, "duration_s": float,
  "steps": int, "cogs": int, "mission": str, "variants": [str],
  "seed": int, "policy_kwargs": {...},
  "status": "passed" | "failed" | "crashed",
  "assertions": [{"name": str, "passed": bool, "message": str, "failed_at_step": int?}],
}
```

## 2. EventRecorder + policy instrumentation

`cvc_policy.recorder.EventRecorder` is the single producer. Replaces
the stderr-only `LogConfig`.

```python
recorder.emit(type="action", agent=0, stream="py",
              payload={"role": "miner", "summary": "mine_carbon", ...})
```

Each emit fans out to three sinks:

1. **stderr** — gated by `log=py+llm` kwarg; formatted via `fmt(event)`.
2. **`events.json`** — appended in-memory, flushed at episode end.
3. **`AgentPolicy._infos`** on the owning agent's wrapper — per-step,
   populated just before returning the action. Mettagrid persists
   this as `policyInfos` in the replay, so every replay carries our
   events even outside scenarios.

Free-form `log.log("py", "...")` calls are removed. Everything is
structured.

### Instrumentation points

- `CvCPolicyImpl.step_with_state` — `action`, `role_change`, `heartbeat`.
- `GameState.process_obs` / `CargoCapTracker` — `cap_discovered`.
- `_preferred_miner_extractor` / role action dispatch — `target`.
- `LLMWorker._dispatch_tool` — `llm_tool_call`.
- `LLMWorker._tool_patch` — `patch_applied`.

### Sink config

| Mode                                         | stderr | events.json | policyInfos |
| -------------------------------------------- | :----: | :---------: | :---------: |
| default (`softmax cogames play`)             |   off  |     off     |      on     |
| `--policy-args log=py+llm`                   |   on   |     off     |      on     |
| `--policy-args record_dir=runs/manual-...`   |   off  |      on     |      on     |
| scenario runs (set both)                     |   off  |      on     |      on     |
| `cgp play --record`                          |   off  |      on     |      on     |

## 3. Scenario runner (library + `cgp` CLI)

New package `src/cvc_policy/scenarios/`:

```
scenarios/
├── __init__.py          # registry + @scenario decorator
├── harness.py           # run_scenario(scenario) -> Run
├── assertions.py        # reusable assertion helpers
├── _run.py              # Run — typed view over a run folder
└── cases/
    ├── smoke.py
    ├── exploration_small.py
    ├── mining_discovers_cap.py
    ├── mining_trip_efficiency.py
    └── empty_extractor_skipped.py
```

### Scenario dataclass

```python
@dataclass
class Scenario:
    name: str
    tier: int                          # 0 smoke, 1 behavior, 2 integrated, 3 scale
    mission: str
    variants: tuple[str, ...] = ()
    cogs: int = 1
    steps: int = 500
    seed: int = 42
    policy_kwargs: dict[str, Any] = field(default_factory=dict)
    mission_overrides: dict[str, Any] = field(default_factory=dict)
    variant_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    setup: Callable[[Env], None] | None = None
    assertions: list[Callable[[Run], AssertResult]] = field(default_factory=list)
```

### Harness

1. Build env via library: `CvCGame()` + `mission.with_variants(...)`.
2. Apply `mission_overrides` via `.model_copy(update=...)` on the mission pydantic model.
3. Apply `variant_overrides` per variant via same.
4. Run scenario `setup(env)` hook (cell-level tweaks, e.g. `drain_extractor`, `grant_gear`).
5. Instantiate `CvCPolicy` with `record_dir=runs/<run_id>/` kwarg.
6. Run `Simulation.rollout(steps)`.
7. Build `Run(run_dir)` and evaluate assertions; write `result.json`.

### `cgp` CLI (top-level console script `cgp = cvc_policy.cli:app`)

```
cgp scenario list                              # registered scenarios + tier
cgp scenario run <name> [--steps N] [--seed S] [--no-assert]
cgp scenario run-all [--tier 0|1|2]            # exit nonzero on fail
cgp view <run_id>                              # regenerate + open report.html
cgp runs                                       # list runs, most recent first
cgp play -m MISSION [-v VARIANT]... [-c N] [-s STEPS]
         [--override KEY=VALUE]...             # mission-field override
         [--variant-override VARIANT.KEY=VALUE]...
         [--record | --no-record]
         [--policy-args KEY=VALUE]...
cgp test-cov                                   # run pytest --cov
```

Installed via `uv tool install -e cogamer-policy-cvc/` or ad-hoc `uv run cgp ...`.

## 4. Initial scenarios (Tier 0 + Tier 1)

### S0 `smoke_machina1_runs` (tier 0)
- `machina_1`, 8 cogs, 200 steps, no setup.
- Assertions: no crash; ≥1 `action` event per agent.

### S1 `exploration_small` (tier 1)
- `tutorial.aligner` + `endless`, 1 cog, 300 steps.
- Emits `world_model_summary` at final step.
- Assertion: `known_cells / reachable_cells ≥ 0.30`.

### S2 `mining_discovers_cap` (tier 1)
- Same base, 60 steps.
- Setup: pre-grant miner gear; spawn adjacent to a full `carbon_extractor`.
- Assertion: exactly one `cap_discovered` with `gear_sig=("miner",)` and `cap=40`, by step ≤ 55.

### S3 `mining_trip_efficiency` (tier 1)
- Extends S2 to 400 steps.
- Assertion: after first `cap_discovered`, each subsequent mining trip
  contains exactly `cap / extract_amount = 4` bumps (no plateau waste).
  Helper: `run.mining_trips(agent)` segments `action` events by target.

### S4 `empty_extractor_skipped` (tier 1)
- Setup: pre-drain a nearby extractor; place a full one farther.
- Assertion: no `target` event ever points to the drained position;
  first chosen target is the farther full one.

Tiers 2 and 3 are deferred (listed in §7).

## 5. HTML viewer (`cgp view`)

`src/cvc_policy/viewer/` — `render.py` + Jinja2 template `report.html.j2`.

### Output
Single self-contained HTML file; embedded CSS; inline events as
`<script type="application/json" id="events">...</script>`; ~150 LOC
vanilla JS for scrubbing and filtering. Zero runtime deps beyond
jinja2.

### Layout

```
┌─ header ─ scenario name, pass/fail badge, duration, cogs, seed, failed-assertion list
├─ left column ─ per-agent timeline rows (up to 8)
│   each row: horizontal strip step 0..N, colored ticks per event type
│   click a tick → jump that step across panels
├─ center ─ replay card
│   thumbnail + "Open in mettascope" button → shells to
│   `softmax cogames replay runs/<id>/replay.json.z`
├─ right column ─ tabbed log view
│   tabs: All | Py | LLM | Team
│   rendered via `fmt(event)`; current step highlighted
└─ bottom ─ step slider (0..max_step), play/pause, speed toggle
```

### Filtering
- Per-agent show/hide.
- Per-type show/hide (collapse noisy `heartbeat`, `llm_tool_call`).
- Text search across payloads + rationales.

### Failure view
When `result.status == "failed"`, the header's failed assertions are
clickable → jump slider to `failed_at_step` (assertion metadata).

## 6. Unit-test coverage audit + gate

- Add `pytest-cov` + `hypothesis` to `dev` dep group.
- `cgp test-cov` shortcut: `pytest --cov=cvc_policy --cov-report=term-missing --cov-report=xml`.

### Phase 1 — audit (half day)
Identify modules under 85% coverage. Known-thin targets:
`cvc_policy/agent/main.py`, `coglet_policy.py`, `navigation.py`,
`cvc_policy/game_state.py`, `cvc_policy/llm_worker.py`,
`cvc_policy/cogamer_policy.py`, new `cvc_policy/recorder.py`.
Per uncovered line: add a targeted test, or mark `# pragma: no cover`
with a one-line justification for pure glue / `__repr__`.

### Phase 2 — CI gate
`.github/workflows/ci.yml` runs `pytest --cov=cvc_policy --cov-fail-under=85`.
Fails build on backslide.

### Phase 3 — invariants (stretch)
Hypothesis property tests for pure helpers: `resource_priority`,
`deposit` behavior via cap, `scramble_target_score`,
`CargoCapTracker.observe`. Small, high bug-finding ROI.

## 7. Deferred

- **Tier 2 scenarios**: retreat under pressure, deposit-at-cap
  integration, aligner heart batching.
- **Tier 3 scale**: `exploration_medium/large`, `mining_multi_agent`.
- **Live web server viewer**: `cgp view serve runs/`. Layers on same
  event model if static HTML becomes limiting.
- **Mettascope panel**: an embedded log panel in MettaScope itself.
  Blocked on upstream plugin API; revisit once that lands.

## 7a. Batch 2 implementation decisions (2026-04-13)

Recorded here so future-us doesn't re-derive the constraints.

**Setup hook is config-level, not live-env.** `run_scenario` calls
`s.setup(env_cfg)` where `env_cfg` is the `MettaGridConfig` pydantic
model, before `run_episode_local` instantiates the live grid. The
C++ grid only exists inside `Rollout.__init__`, so there is no
reliable pre-rollout hook for live grid-object mutation. Supported
setup handles: `env_cfg.game.agents[i].inventory.initial[resource]`
(grant starting inventory), `env_cfg.game.max_steps`, map-builder
`seed` (determinism), and any other pydantic field on the config.
Live-grid mutations like "drain a specific extractor" are not
reachable from here.

**Mission registry is hard-coded.** `_resolve_mission(name, cogs)`
maps a small known set of strings to factory calls: `machina_1`,
`tutorial.aligner`, `tutorial.miner`, `tutorial.scrambler`. Unknown
names raise `KeyError`. No plugin/auto-discovery until we need
scenarios across many missions.

**S4 `empty_extractor_skipped` reframed from pre-drain to self-drain.**
The `ExtractorsVariant` config only exposes a global `initial_amount`,
so "pre-drain a nearby extractor" is not selectable at config level.
The scenario instead asserts: after the agent self-drains an
extractor during the rollout, its next `miner` target points to a
different extractor position. Same behavior under test, reachable
deterministically via seed=42 without any setup hook. A future
upstream change exposing per-extractor inventory overrides could
restore the pre-drain form.

## 8. Out of scope

- Training or RL. This is diagnostic only.
- Multi-episode aggregation / dashboards. One run == one folder ==
  one report.
- Policy performance benchmarking. Coverage + correctness first.
