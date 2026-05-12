---
name: cogamer.improve
description: Implement one targeted CvC code change from analysis, verify improvement, submit if better
---

# Improve

Implement one targeted code change based on an analysis, verify it improves scores, and submit.

**Announce at start:** "I'm using the improve skill to implement and verify a fix from the analysis."

## Prerequisites

Run `/cogamer.analyze` first to produce `cogamer/analysis.md` with a diagnosis.

## Steps

### 1. Read Analysis

Read `cogamer/analysis.md`. Understand the weakness, root cause, and proposed fix.

### 2. Eval Baseline

```bash
softmax cogames eval -m machina_1 -p class=cvc_policy.cogamer_policy.CvCPolicy -e 10 --format json --seed 42
```

Record the average reward as the baseline.

### 3. Implement Fix

Make one focused code change as described in the analysis. Touch only the files identified. Keep the diff minimal.

Possible change surfaces:
- **Engine logic**: `src/cvc_policy/agent/main.py`, `roles.py`, `targeting.py`, `pressure.py`, `scoring.py`, `navigation.py`
- **Programs**: `src/cvc_policy/programs.py` (program table, LLM prompt, LLM response parsing)
- **Parameters**: `src/cvc_policy/agent/types.py`
- **Game state**: `src/cvc_policy/game_state.py`

### 4. Eval After Change

Run the same eval across 5 seeds:

```bash
for seed in 42 43 44 45 46; do
  softmax cogames eval -m machina_1 -p class=cvc_policy.cogamer_policy.CvCPolicy -e 5 --seed $seed --format json
done
```

### 5. Decide

- **Improved**: average reward increased -> keep the change, submit
- **Regressed**: average reward decreased -> `git checkout` the changed files, report what didn't work
- **Neutral**: no significant change -> keep if the change is clearly more correct, otherwise revert

### 6. Submit if Improved

Get the player name from `softmax cogames player list`. Submit automatically:

```bash
cogames upload -p class=cvc_policy.cogamer_policy.CvCPolicy -n <cogamer-name>
```

Do NOT ask for confirmation. Log the submission.

### 7. Update Analysis

Append the result to `cogamer/analysis.md`:

```markdown
## Result
- baseline: X
- after: Y
- verdict: improved/regressed/neutral
- submitted: yes/no
```

## Principles

- **One change per cycle.** Isolate what works.
- **Revert on regression.** No exceptions.
- **Fix root causes, not symptoms.** If the analysis says "mining is slow", don't add a band-aid — fix the actual pathfinding or scoring logic.
