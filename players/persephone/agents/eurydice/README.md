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

## Current Status

The agent is active in live games: it advances the intro sequence, learns
role/team/room, parses role-summary/schedule panels, enters role-driven
objectives, selects probe targets, creates or requests whispers, and completes
some probes.

The major current bottleneck is not idle behavior; it is interaction
reliability. Live traces still show too many `initiate_timeout` failures while
trying to start or join whispers.

## LLM Readiness

`llm_context.py` provides the first stable LLM boundary:

- `build_llm_context(...)` returns a JSON-safe context packet.
- `llm_decision_schema()` returns the closed semantic action schema.
- `llm_validator.py` checks future decisions for schema validity, view
  legality, target safety, message bounds, and reveal constraints.
- `validate_and_trace_llm_decision(...)` can emit compact shadow decision
  traces when a saved-context or future runtime caller invokes it.
- No LLM provider is called yet.
- Runtime policy still uses deterministic evaluators and modes.

The intended next step is a saved-context shadow runner plus prompt templates:
generate LLM decisions from recorded contexts, validate them, and compare them
to the rule stack before allowing any live control.

## Validation

Run focused Eurydice tests:

```sh
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_eurydice_stages.py \
  tests/test_eurydice_evaluators.py \
  tests/test_eurydice_knowledge.py \
  tests/test_eurydice_llm_context.py \
  tests/test_eurydice_llm_validator.py \
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
