# Audit & Instrumentation Tools

Reference for all gameplay auditing, profiling, and instrumentation systems.

## Quick Start

Run the feature audit (best single command for "what mechanics fire?"):

```bash
TV_AUDIT_STEPS=3000 TV_AUDIT_SEED=42 \
  nim c -r -d:release --path:src scripts/feature_audit.nim
```

Run with compile-time audit dashboards (combinable):

```bash
nim c -r -d:release \
  -d:actionAudit -d:combatAudit -d:econAudit -d:techAudit \
  --path:src scripts/feature_audit.nim
```

## Compile-Time Audit Flags

All audit systems are zero-cost when disabled. Enable via `-d:flag`. All output to stdout.

| Flag | File | What It Tracks | Key Env Vars |
|------|------|----------------|--------------|
| `-d:actionAudit` | `action_audit.nim` | Per-team action verb distribution (11 verbs) | `TV_ACTION_AUDIT_INTERVAL=100` |
| `-d:combatAudit` | `combat_audit.nim` | Damage/kills/healing/conversions/siege by team | `TV_COMBAT_REPORT_INTERVAL=100`, `TV_COMBAT_VERBOSE=false` |
| `-d:econAudit` | `econ_audit.nim` | Resource flows from 11 sources, stocks, rates | `TV_ECON_VERBOSE=false`, `TV_ECON_DETAILED=false` |
| `-d:techAudit` | `tech_audit.nim` | Research events, costs, upgrade application | (interval hardcoded 100) |
| `-d:tumorAudit` | `tumor_audit.nim` | Tumor spawn/branch/damage/spread velocity | `TV_TUMOR_REPORT_INTERVAL=100` |
| `-d:eventLog` | `event_log.nim` | Human-readable event timeline (11 categories) | `TV_EVENT_FILTER=` (comma-sep), `TV_EVENT_SUMMARY=false` |
| `-d:settlerMetrics` | `settler_metrics.nim` | Settlement expansion, villager distribution | `TV_SETTLER_METRICS_INTERVAL=10` |
| `-d:aiAudit` | `ai_audit.nim` | AI decision branches, role distribution | `TV_AI_LOG=0` (0=off, 1=summary, 2=verbose) |

### Event Log Categories

Filter with `TV_EVENT_FILTER=combat,death,research` (empty = all):

`spawn`, `death`, `buildstart`, `builddone`, `builddestroy`, `gather`, `deposit`, `combat`, `conversion`, `research`, `trade`

### Audit Manager

`audit_manager.nim` orchestrates all audits:
- `initAllAudits()` at startup
- `flushAllAudits(env, step)` end of each step
- `resetAllAudits()` on game reset
- Integration point: `step.nim` ~line 2282

## Scripts

| Script | Purpose | Command |
|--------|---------|---------|
| `scripts/feature_audit.nim` | 8-section feature coverage report | `TV_AUDIT_STEPS=3000 nim c -r -d:release --path:src scripts/feature_audit.nim` |
| `scripts/benchmark_steps.nim` | Performance profiling with regression detection | `make benchmark` |

## Per-Agent Stats

Defined in `types.nim` (Stats object, line ~703). Tracks 11 action counters per agent:

```
actionInvalid, actionNoop, actionMove, actionAttack, actionUse,
actionSwap, actionPlant, actionPut, actionBuild, actionPlantResource,
actionOrient, actionSetRallyPoint
```

- Incremented at 73 locations in `step.nim`
- Currently only read by `replay_writer.nim` (for action success flag)
- **Gap**: No end-of-episode summary printer exists

## Replay System

- `replay_writer.nim`: Per-agent per-step capture (position, action, success, reward)
- `replay_analyzer.nim`: Extracts per-team strategy summaries from `.json.z` replays
- Enable: `TV_REPLAY_DIR=./replays`
- **Gap**: Replays don't capture tech research, market trades, unit classes, or building kinds

## Known Gaps

| Gap | Impact |
|-----|--------|
| No per-agent stats summary at episode end | Can't see individual agent contributions |
| No garrison tracking in audits | Don't know if garrison mechanic fires |
| No victory condition progress tracking | Can't see relic/wonder/KOTH countdown progress |
| No spatial info in any audit | Can't answer "where did X happen?" |
| Replay missing tech/market/unit-class data | Training fitness can't reward tech progression |
| Event log requires recompile to enable | Can't toggle at runtime |
