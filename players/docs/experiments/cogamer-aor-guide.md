# AOR and GUIDE Prompt Experiments on Cogamer

**Author:** Lucas Schiavini
**Period:** April 6-15, 2026
**Original branch:** `lschiavini/decision-log-metrics`
**Metta port branch:** `relh/decision-log-metrics`

## Background

The original experiments were run on the now-deleted `cog-cyborg` runtime. That runtime let an LLM review telemetry,
rewrite policy code, and append decision records while a CogsGuard episode was running. Current Cogamer uses a program
table policy instead: deterministic Python handles every tick, while the LLM periodically returns strategic fields such
as `resource_bias`, `role`, and `objective`.

This port keeps the useful measurement piece from the old work and moves it to the current Agent Policies Cogamer
layout:

- LLM decision log entries now include `metrics_snapshot`.
- Benchmark helpers read `/tmp/coglet_learnings/{game_id}.json`.
- Per-objective stall metrics are reported when snapshots contain `objective`.

## Papers Tested

### AOR: Act-Observe-Rewrite

AOR works best when an agent can observe concrete failure evidence and rewrite a bounded behavior. The useful Cogamer
adaptation is not arbitrary code rewriting. It is structured diagnosis attached to LLM strategic decisions, with enough
metrics to tell whether the diagnosis helped.

### GUIDE

GUIDE-style structured reflection was useful for forcing a decision record to say what changed and why. The current
program-table API keeps that as typed JSON fields rather than prose before JSON, because Cogamer's parser consumes the
LLM response directly.

## Historical Findings

The old cog-cyborg benchmarks compared a baseline prompt against AOR/GUIDE prompt variants on `machina_1`.

| Finding | Interpretation for Cogamer |
| --- | --- |
| Diagnosis helped aligner-pressure failures. | These failures are often systematic: wrong role mix, missed junction pressure, or stale target choice. |
| Diagnosis hurt some bootstrap failures. | Bootstrap can be stochastic: nearby extractors, timing, and spawn layout can make post-hoc explanations misleading. |
| Aggregate metrics hid the split. | Per-objective stall metrics are needed; a single stalled fraction is not enough. |
| Bare prose before JSON caused occasional malformed outputs. | Structured fields should live inside JSON for the current parser. |

## Current Metrics Port

Current Cogamer learnings files contain:

- `llm_log`: every LLM strategic decision, now with `metrics_snapshot`
- `snapshots`: periodic game-state snapshots
- `agents`: per-agent episode summary

The benchmark helpers compute:

- final hearts and resource units
- peak and final friendly junctions
- LLM count, latency, and error rate
- stalled fraction and longest stall
- `stall_steps_{objective}`, `longest_stall_{objective}`, and `num_stalls_{objective}`

Run a local benchmark variant with:

```bash
python tools/benchmark/cogamer/bench_variant.py baseline --runs 3 --steps 10000 --agents 8
```

Analyze existing learnings without running episodes:

```bash
python tools/benchmark/cogamer/bench_variant.py baseline --analyze-only
```

Compare two variants:

```bash
python tools/benchmark/cogamer/bench_variant.py aor-guide --analyze-only --compare-to baseline
```

## Follow-up

The prompt changes themselves were separate from the measurement surface. This port is scoped to the metrics and
benchmarking support needed to evaluate those changes on the current Cogamer runtime.
