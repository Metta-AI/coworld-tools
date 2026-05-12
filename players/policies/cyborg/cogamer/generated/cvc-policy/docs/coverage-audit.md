# Coverage Audit — 2026-04-13

Baseline run:

```
.venv/bin/pytest --cov=cvc_policy --cov-report=term-missing --cov-fail-under=0 -q
```

Suite: 538 passed, 7 deselected.
Aggregate: 3065 stmts, 1193 missed, 61% covered.

## Per-module table (ascending coverage)

| Module | Stmts | Missed | Covered | Notes |
| --- | ---: | ---: | ---: | --- |
| `lifelet.py`                          |   6 |   6 |   0% | Unused coglet supervision shim. Not in policy path. |
| `llm_executor.py`                     |  42 |  42 |   0% | Unused coglet supervision shim. Not in policy path. |
| `runtime.py`                          | 179 | 179 |   0% | Unused coglet supervision shim (CogletRuntime). Not in policy path. |
| `setup_policy.py`                     |   3 |   3 |   0% | Top-level subprocess bootstrap script; runs on import. |
| `ticklet.py`                          |   4 |   4 |   0% | Unused coglet supervision shim. Not in policy path. |
| `trace.py`                            |   5 |   5 |   0% | Unused coglet supervision shim. Not in policy path. |
| `agent/targeting.py`                  | 210 | 177 |  16% | Core policy surface. Needs tests. |
| `agent/roles.py`                      |  83 |  69 |  17% | Core policy surface. Needs tests. |
| `agent/pressure.py`                   |  78 |  58 |  26% | Core policy surface. Needs tests. |
| `agent/junctions.py`                  |  66 |  48 |  27% | Core policy surface. Needs tests. |
| `coglet.py`                           |  91 |  64 |  30% | Coglet supervision tree (reached only via runtime). |
| `channel.py`                          |  84 |  54 |  36% | Coglet message-bus scaffolding. |
| `agent/navigation.py`                 | 111 |  69 |  38% | Core policy surface. Needs tests. |
| `game_state.py`                       | 164 |  93 |  43% | Core policy surface (mostly property accessors). Needs tests. |
| `agent/main.py`                       | 123 |  64 |  48% | Core policy surface (CvcEngine pipeline). Needs tests. |
| `agent/coglet_policy.py`              |  47 |  24 |  49% | Bridge to cogames Policy base class. Needs tests. |
| `programs.py`                         | 153 |  72 |  53% | Program table — many stub bodies. Needs tests. |
| `proglet.py`                          |  37 |  13 |  65% | Coglet proglet base — minimal behaviour. |
| `handle.py`                           |  31 |   8 |  74% | Coglet handle stubs. |
| `llm_worker.py`                       | 116 |  27 |  77% | Background Anthropic thread; hot path covered, network+exec paths not. |
| `scenarios/harness.py`                |  90 |  17 |  81% | Real-env harness; tail branches untested. |
| `scenarios/assertions.py`             |  89 |  14 |  84% | Error-path branches. |
| `cli.py`                              | 141 |  23 |  84% | Typer commands; thin command plumbing. |
| `agent/world_model.py`                |  69 |   9 |  87% | |
| `agent/decisions.py`                  |  81 |  10 |  88% | |
| `scenarios/cases/empty_extractor_skipped.py` | 9 | 1 | 89% | Assertion branch not exercised in smoke. |
| `scenarios/cases/mining_discovers_cap.py`    | 9 | 1 | 89% | Assertion branch not exercised in smoke. |
| `scenarios/cases/mining_trip_efficiency.py`  | 9 | 1 | 89% | Assertion branch not exercised in smoke. |
| `overrides.py`                        |  43 |   3 |  93% | |
| `cogamer_policy.py`                   | 200 |  29 |  86% | |
| `scenarios/__init__.py`               |  33 |   1 |  97% | |
| `scenarios/_run.py`                   |  67 |   2 |  97% | |
| `agent/tick_context.py`               |  50 |   1 |  98% | |
| `agent/pathfinding.py`                |  70 |   1 |  99% | |
| `agent/resources.py`                  | 103 |   1 |  99% | |
| `agent/budgets.py`                    |  68 |   0 | 100% | |
| `agent/cargo_cap.py`                  |  20 |   0 | 100% | |
| `agent/geometry.py`                   |  38 |   0 | 100% | |
| `agent/scoring.py`                    |  72 |   0 | 100% | |
| `agent/types.py`                      |  31 |   0 | 100% | |
| `recorder.py`                         |  59 |   0 | 100% | |
| `viewer/render.py`                    |  59 |   0 | 100% | |

## Under-85% modules: plan

### Unused coglet supervision scaffolding

Modules: `runtime.py`, `lifelet.py`, `ticklet.py`, `trace.py`, `llm_executor.py`, `coglet.py`, `channel.py`, `handle.py`, `proglet.py`, `setup_policy.py`.

These are a coglet supervision-tree framework left over from earlier iterations
and never imported from the `CvCPolicy` runtime path. Nothing in the policy
actually spawns a `CogletRuntime`; `cogamer_policy.py` uses only
`proglet.Program` as a duck-type hint.

- `setup_policy.py` is a subprocess install bootstrap script.
- The others are interdependent scaffolding (runtime → coglet → channel/handle;
  runtime → lifelet/ticklet/trace; llm_executor → proglet).

Rather than write tests for unreachable glue, these modules are added to
`[tool.coverage.run] omit` in `pyproject.toml`. The audit row still records
them so the decision is visible.

### Core policy modules — test targets

Ranked by impact:

- **`agent/targeting.py` (16%)**  — target selection/scoring helpers. Uncovered: `find_nearest_*`, `pick_extractor_target`, `best_scramble_target`, retreat scoring, blocker helpers. Most are pure functions over `WorldModel` and `GameState` — unit-testable by constructing minimal fake contexts.

- **`agent/roles.py` (17%)** — role action generators (miner step, aligner step, scrambler step). Uncovered: all role dispatch bodies. Testable via synthetic `TickContext`.

- **`agent/pressure.py` (26%)** — role-budget allocator and retreat thresholds. Pure logic over team summaries.

- **`agent/junctions.py` (27%)** — junction memory updates. Pure dict-bashing.

- **`agent/navigation.py` (38%)** — path following, unstick logic. Pure functions plus state mutations.

- **`agent/main.py` (48%)** — CvcEngine pipeline (heal → retreat → …). End-to-end step testable via the engine.

- **`agent/coglet_policy.py` (49%)** — bridges cogames policy base class. Small; test the bridge methods.

- **`programs.py` (53%)** — program table lookups. Exercise each executor shim.

- **`game_state.py` (43%)** — mostly property getters over obs tensors. Unit-testable via synthetic obs.

- **`llm_worker.py` (77%)**  — background thread; network path untestable cheaply. Raise via unit tests of the message-assembly helpers. Network-call inner loop marked `# pragma: no cover` (hits real anthropic API).

### Budget

Given module count and gate at 85% line coverage overall, we tackle the
biggest wins:

1. `agent/targeting.py` — largest untested surface (177 missed lines).
2. `agent/roles.py` + `agent/main.py` — the role dispatch end-to-end.
3. `agent/pressure.py`, `agent/junctions.py`, `agent/navigation.py`.
4. `game_state.py` property accessors.
5. `programs.py` stub bodies.

After those, remaining gap should be <15% overall and gate-ready.
