# Common Mistakes

Failure patterns that recur across all games. The evolution agent updates this document.

## Structural Failures

### 1. Oscillation
**Symptom**: Agent switches between two strategies every few ticks, accomplishing neither.
**Root cause**: Two competing heuristics of similar priority with no hysteresis.
**Fix**: Add minimum commitment time (N ticks in a role before switching allowed).

### 2. Tunnel Vision
**Symptom**: Agent pursues one goal obsessively while the game state changes around it.
**Root cause**: Brain doesn't re-evaluate goals when new information arrives.
**Fix**: Add periodic goal validity checks; let the LLM interrupt with strategic shifts.

### 3. Analysis Paralysis
**Symptom**: LLM consultations produce contradictory or vague directives; agent drifts.
**Root cause**: Narrator context is too noisy or the system prompt lacks clear guidance.
**Fix**: Simplify the context. Front-load the most important state. Give the LLM a
concrete decision to make, not an open-ended analysis.

### 4. Premature Surrender
**Symptom**: LLM declares game lost when the agent is behind but could still recover.
**Root cause**: Surrender detection fires too easily; LLM doesn't understand comeback mechanics.
**Fix**: Raise MIN_SURRENDER_TICK. Add comeback examples to the system prompt.

### 5. Opening Lock-In
**Symptom**: Agent uses the same opening every game regardless of map/seed.
**Root cause**: Scripted opener doesn't adapt to initial observations.
**Fix**: Add early branching conditions: "IF starting resources include X THEN opener A ELSE opener B".

## Resource Failures

### 6. Missing Resources
**Symptom**: Agent never acquires a key resource and can't progress.
**Root cause**: Resource is not in immediate view; exploration doesn't target it.
**Fix**: After N ticks, if any required resource is at 0, force exploration in unexplored directions.

### 7. Hoarding
**Symptom**: Agent has plenty of resources but never spends them.
**Root cause**: Spending conditions are too conservative.
**Fix**: Add time-pressure spending rules: "IF past tick 200 AND resources > threshold THEN deploy".

### 8. Wrong Priority
**Symptom**: Agent gathers abundant resources while scarce ones go uncollected.
**Root cause**: Gatherer targets closest resource, not most-needed.
**Fix**: Score targets by scarcity, not proximity.

## Timing Failures

### 9. Too Slow to Transition
**Symptom**: Agent stays in opening strategy into the mid-game.
**Root cause**: Transition triggers are too conservative.
**Fix**: Add tick-based deadlines as fallback triggers for role transitions.

### 10. Endgame Collapse
**Symptom**: Agent plays well early but score stagnates or declines late.
**Root cause**: Late-game requires different strategy; agent continues mid-game behavior.
**Fix**: Add explicit endgame detection (clock-based or score-based) with strategy overrides.

---

*This file is updated automatically by the evolution agent as new failure patterns are discovered.*
