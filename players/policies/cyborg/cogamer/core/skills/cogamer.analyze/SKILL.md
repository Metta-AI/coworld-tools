---
name: cogamer.analyze
description: Diagnose the biggest CvC policy weakness from eval metrics and LLM-Python trace data
---

# Analyze

Diagnose the single biggest performance weakness in the CvC policy from eval metrics and trace data.

**Announce at start:** "I'm using the analyze skill to diagnose the biggest performance weakness."

## Inputs

1. **Eval metrics** from a recent `/cogamer.evaluate` run (JSON output)
2. **LLM trace** from `/tmp/cvc-trace/*.json` (if available from a `/cogamer.play` run)
3. **Reference docs**: `docs/architecture.md` (alpha.0 comparison), `docs/strategy.md`
4. **Current code**: `src/cogamer/cvc/agent/main.py`, `programs.py`, `agent/roles.py`, `agent/targeting.py`, `agent/pressure.py`, `agent/scoring.py`

## Process

### 1. Read Eval Metrics

Parse the evaluation JSON. Identify which metrics are weakest:
- Low total reward -> resource collection or junction control problem
- High deaths -> survival/retreat logic problem
- High timeouts -> policy too slow (LLM latency or pathfinding)

### 2. Read LLM Trace

If trace files exist, analyze the LLM-Python communication:
- Are LLM prompts giving the model enough context?
- Are LLM responses being parsed and applied correctly?
- Is the LLM making good strategic calls (resource bias, role overrides)?
- Is the LLM call frequency appropriate?

### 3. Trace Root Cause

Cross-reference the weakness with the code. Read the relevant engine files. Identify the specific function, parameter, or logic that causes the gap. Compare against alpha.0 reference in `docs/architecture.md`.

### 4. Write Diagnosis

Write `cogamer/analysis.md` with:

```markdown
## Weakness
One-line summary of the performance gap.

## Evidence
Metrics and trace data that demonstrate the problem.

## Root Cause
Which code, at which line, causes this. Why.

## Proposed Fix
Specific code change to make. Which file, which function, what to change.

## Risk
What could regress if this fix is wrong.
```

## Principles

- **One weakness per analysis.** The biggest one. Fix that first.
- **Trace to code.** Don't say "mining is bad" — say "mine() in roles.py:L42 doesn't account for X".
- **Include the LLM dimension.** If the LLM prompt is wrong or the response parsing is lossy, that's a valid root cause.
