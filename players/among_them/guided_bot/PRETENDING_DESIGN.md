# Phase 6.5 — `pretending` Mode Design

> **Scope:** Add fake A-press during loiter and witness-swap behavior
> to eliminate the behavioral tell where imposters stand idle at
> stations without interacting.
>
> **Parent doc:** `DESIGN.md` §5.3, §5.4, §5.8.
>
> **Related:** `HUNTING_DESIGN.md` §2.1 (cover patrol mirrors this
> mode's station-rotation logic).
>
> Last updated: 2026-05-04

---

## 1. What exists today

### 1.1 Mode handler (`modes/pretending.nim`)

The imposter cover mode. Before the fix, three states in `decide()`:

1. **Loitering:** If `preLoiterUntilTick` is set and not expired,
   return `noOpIntent()` — stand still, do nothing.
2. **Target selection:** Tick-modulo offset rotation through stations,
   picking one that's not too close (>30 px).
3. **Navigation:** `DisciplineNormal` to the target's passable centre.
   On arrival (inside task rect + 8 px margin), set loiter timer.

### 1.2 Scratch state

- `preFakeTargetIndex: int` — current station being visited.
- `preLoiterUntilTick: int` — tick when loiter ends.
- `preEnterTick: int` — tick when mode was entered.

### 1.3 Problems

1. **Never presses A during loiter.** A crewmate at a task station
   would be visibly holding A (the task-hold animation shows the
   player sprite facing the station and slightly bobbing). The
   imposter just stands there — distinguishable by any observer or
   replay analysis.

2. **`preMaySwapOnWitness` is dead code.** The param exists in
   `ModeParams` and `defaultParamsFor` sets it to `true`, but
   `decide()` never reads it. If a new crewmate appears while the
   imposter is loitering, the imposter doesn't react.

---

## 2. Design

### 2.1 Fake A-press during loiter

Split loiter into two sub-phases:

| Sub-phase | Duration | Behavior |
|-----------|----------|----------|
| **Fake-hold** | `PreFakeHoldTicks` (60) | `DisciplineTaskHold` — press A, no movement. Mimics a crewmate performing the task. |
| **Linger** | remainder of `preLoiterTicks - PreFakeHoldTicks` (36 by default) | `noOpIntent()` — stand still, simulating the post-completion pause before walking to the next task. |

The fake-hold phase emits the same `DisciplineTaskHold` discipline
a real crewmate uses. To an observer (human or bot), the imposter
looks like it's doing the task. The shorter linger phase after looks
like the crewmate deciding where to go next.

If `preLoiterTicks < PreFakeHoldTicks`, clamp fake-hold to the full
loiter duration (no linger phase). This handles LLM-issued params
with very short loiter times.

The A-press will not actually complete a task — the server requires
the player's assigned task stations to match. Pressing A at a
non-assigned station is harmless (server silently ignores it).

### 2.2 Witness swap

When `preMaySwapOnWitness` is true and a new crewmate appears
during loiter:

1. Detect the appearance: `belief.percep.visibleCrewmates.len > 0`
   while loitering (checked each tick during loiter).
2. End the loiter early: clear `preLoiterUntilTick`,
   `preFakeHoldUntilTick`, and `preFakeTargetIndex`.
3. Fall through to target selection on the same tick — the bot
   immediately picks a new station (the rotation logic avoids
   stations within 30 px, so it won't re-pick the current one).

Rationale: if a crewmate sees the imposter at the same station
for a long time without the task completing, that's suspicious.
Leaving early looks like the imposter "just finished" and is
moving on.

The swap only fires once per loiter period (clearing the loiter
timer prevents re-triggering). There's no cooldown beyond this —
if the imposter picks a new station and immediately sees another
crewmate, it just navigates normally (it's in the Navigate sub-phase,
not loitering).

### 2.3 No other changes

- Target selection logic stays the same (tick-modulo offset rotation).
- Navigation uses `DisciplineNormal` to passable centres (already
  correct post-6.4).
- The reflex `pretending → hunting` (lone crew, kill ready) continues
  to fire from any sub-phase — it checks mode identity, not scratch
  state.

---

## 3. Scratch state changes

```nim
of ModePretending:
  preFakeTargetIndex: int          ## (exists) Current station.
  preLoiterUntilTick: int          ## (exists) Loiter deadline.
  preEnterTick: int                ## (exists) Mode entry tick.
  preFakeHoldUntilTick: int        ## (new) Fake-hold sub-phase deadline.
  preWitnessSwapped: bool          ## (new) Whether swap fired this loiter.
```

---

## 4. Tuning constants

| Constant | Value | Rationale |
|----------|-------|-----------|
| `PreFakeHoldTicks` | 60 | ~2.5s of A-press. Real task holds are 72–84 ticks; slightly shorter to avoid over-committing. |

This is the only new constant. `preLoiterTicks` already exists as a
param (default 96). The fake-hold consumes the first 60 ticks of the
96-tick loiter; the remaining 36 ticks are the linger phase.

---

## 5. Revised `decide()` logic (pseudocode)

```
proc decide(belief, params, scratch):
  if not localized or tasks.len == 0:
    return noOpIntent()

  # --- Loitering (fake-hold + linger) ---
  if scratch.preLoiterUntilTick > 0 and belief.tick < scratch.preLoiterUntilTick:

    # Witness swap check.
    if params.preMaySwapOnWitness and
       not scratch.preWitnessSwapped and
       belief.percep.visibleCrewmates.len > 0:
      scratch.preWitnessSwapped = true
      scratch.preFakeTargetIndex = -1
      scratch.preLoiterUntilTick = 0
      scratch.preFakeHoldUntilTick = 0
      # Fall through to target selection below.
    else:
      # Sub-phase: fake-hold or linger?
      if belief.tick < scratch.preFakeHoldUntilTick:
        return ActionIntent(discipline: DisciplineTaskHold, pressA: true, ...)
      else:
        return noOpIntent()

  # --- Loiter expired → pick new target ---
  if scratch.preLoiterUntilTick > 0:
    scratch.preFakeTargetIndex = -1
    scratch.preLoiterUntilTick = 0
    scratch.preFakeHoldUntilTick = 0
    scratch.preWitnessSwapped = false

  # --- Target selection (unchanged) ---
  ...

  # --- Arrival check ---
  if isInsideTaskRect(...):
    scratch.preLoiterUntilTick = belief.tick + params.preLoiterTicks
    scratch.preFakeHoldUntilTick = belief.tick + min(PreFakeHoldTicks, params.preLoiterTicks)
    scratch.preWitnessSwapped = false
    # Start fake-hold immediately on arrival.
    return ActionIntent(discipline: DisciplineTaskHold, pressA: true, ...)

  # --- Navigation (unchanged) ---
  return ActionIntent(steerTo: goal, discipline: DisciplineNormal, ...)
```

---

## 6. Trace events

No new trace events. The existing `decisions.jsonl` records the
discipline (`DisciplineTaskHold` vs `DisciplineNoOp`) which is
sufficient to see fake-hold behavior in traces. If we later want
finer-grained analysis, a `fake_task_started` / `fake_task_ended`
pair could be added — but it's not load-bearing.

---

## 7. Files changed

| File | Change |
|------|--------|
| `types.nim` | Add `preFakeHoldUntilTick: int` and `preWitnessSwapped: bool` to `ModeScratch.ModePretending` |
| `tuning.nim` | Add `PreFakeHoldTicks = 60` |
| `modes/pretending.nim` | Rewrite loiter block with fake-hold sub-phase + witness swap |
| `IMPL_PLAN.md` | Mark 6.5 done |
| `README.md` | Update phase table |

---

## 8. Implementation plan

### Step 1 — Type + tuning
- Add 2 scratch fields to `types.nim`.
- Add `PreFakeHoldTicks` to `tuning.nim`.
- Verify: compile, existing tests pass.

### Step 2 — Rewrite loiter logic
- Split loiter into fake-hold and linger sub-phases.
- Add witness-swap check.
- Set `preFakeHoldUntilTick` on arrival.
- Update `onEnter` to initialize new fields.
- Verify: compile, all tests pass.

### Step 3 — Doc updates
- Update IMPL_PLAN.md, README.md.
- Run fallback_test to ensure non-NOOP behavior preserved.

### Step 4 — Live validation
- Run `--seed 100 --force-role imposter --duration 60` with tracing.
- Confirm `decisions.jsonl` shows `DisciplineTaskHold` during
  pretending loiter phases.
- Verify witness swap fires when a crewmate appears nearby (check
  mode transitions in `modes.jsonl` — should see station changes
  mid-loiter on seeds where crewmates pass by).
