# Eurydice

Eurydice is the strategic Orpheus-based agent for Persephone's Escape. It uses
pixel perception, Orpheus belief state, a Eurydice knowledge layer, role
evaluators, probe modes, and a whisper FSM to play the game.

Current source truth:

- [`DESIGN.md`](DESIGN.md) describes the intended full behavior.
- [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) is the source-verified
  roadmap and current gap list.
- [`LLM_CONTROL.md`](LLM_CONTROL.md) describes the next control architecture:
  deterministic perception/mechanics with LLM-assisted social strategy.
- [`LLM_STRATEGY_MIGRATION.md`](LLM_STRATEGY_MIGRATION.md) gives the
  comprehensive plan for moving current Eurydice to LLM-led strategy while
  preserving Orpheus modes and deterministic mechanics.

## Current Status

The agent is active in live games: it advances the intro sequence, learns
role/team/room, parses role-summary/schedule panels, enters role-driven
objectives, selects probe targets, creates or requests whispers, and completes
some probes.

The major current bottleneck is not idle behavior; it is interaction
reliability. Live traces show agents selecting targets, creating/requesting
whispers, and moving through role objectives, but they still mostly produce
solo whispers. The authoritative server logs from the latest full runs show no
joined whispers and no server-confirmed role/color exchanges, so winning is
blocked before higher-level social strategy can matter.

## LLM Readiness

`llm_context.py` provides the current stable LLM boundary:

- `build_llm_context(...)` returns a JSON-safe v2 context packet with runtime
  affordances, pending entries, active offers, cooldowns, and probe failures.
- `llm_decision_schema()` returns the closed v2 semantic action schema,
  including entry grant/deny, movement destinations, and hostage payloads.
- `llm_validator.py` checks model decisions for schema validity, view
  legality, target safety, message bounds, reveal constraints, active offers,
  pending entry targets, destination bounds, hostage-grid eligibility/counts,
  false first-person identity claims, unsupported role-possession claims, and
  implied false `[role] HERE` messages.
- `llm_prompts.py`, `llm_provider.py`, and `llm_shadow.py` provide
  strategically tuned prompts, deterministic providers, an opt-in
  standard-library AWS Bedrock Haiku provider, and offline shadow evaluation.
- `llm_executor.py` and `llm_action_mode.py` map validated semantic decisions
  to registered Orpheus modes/tasks without exposing button presses.
- Runtime LLM control is optional and off by default. `--llm-control shadow`
  traces provider decisions without changing behavior; `targets` can replace
  `probe_systematic` with a validated `probe_target`; `whispers` enables the
  first mode-local whisper hook for pending-entry and first-message decisions;
  `all` enables every validated executor-backed semantic action in the current
  view, including global chat, leader-summit chat, movement/open-view actions,
  leadership seeking, and hostage selection.
- Providers are selected with `--llm-provider hold|heuristic|haiku|bedrock`.
  `hold` remains the default. The Bedrock provider resolves AWS env,
  ECS/container credentials, or local AWS CLI credentials, honors
  `EURYDICE_LLM_MODEL` / `EURYDICE_BEDROCK_MODEL`, and uses
  `EURYDICE_LLM_COOLDOWN_TICKS` so live control does not call the model every
  frame.
- Executor-backed LLM actions fail closed on view changes. The final short
  Haiku smoke trace on May 11, 2026 accepted hostage selections and reported
  `valid_views_mismatch=0` with no provider errors. It still ended in a draw,
  so the remaining gap is strategic exchange completion, not action legality.

## Validation

Run focused Eurydice tests:

```sh
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_eurydice_stages.py \
  tests/test_eurydice_evaluators.py \
  tests/test_eurydice_knowledge.py \
  tests/test_eurydice_llm_context.py \
  tests/test_eurydice_llm_validator.py \
  tests/test_eurydice_llm_shadow.py \
  tests/test_eurydice_llm_executor.py \
  tests/test_eurydice_llm_runtime.py \
  tests/test_eurydice_trace_schema.py \
  -q
```

Run the full suite before committing behavior changes:

```sh
PYTHONPATH=. .venv/bin/python -m pytest tests -q
```

Live trace summary:

```sh
.venv/bin/python scripts/analyze_eurydice_traces.py /tmp/eurydice_strategy_agents
```

When auditing exchange traces, treat `whisper_exchange_outcome` with
`server_confirmed=false` as a menu attempt, not proof that the server accepted a
role/color exchange. A true win-relevant role exchange must also appear in the
server `full.log` as `shared roles` or in Eurydice as
`server_confirmed=true`.
