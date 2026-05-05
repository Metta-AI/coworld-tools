# Phase 6.6 — `fleeing` Mode Design

> **Scope:** Fix two issues in the fleeing mode: (1) the bot stands
> idle after the flee timer expires instead of resuming useful
> behavior, and (2) the flee target can land on impassable terrain,
> causing A* to fail.
>
> **Parent doc:** `DESIGN.md` §5.4, §5.8.
>
> Last updated: 2026-05-04

---

## 1. What exists today

### 1.1 Mode handler (`modes/fleeing.nim`)

The imposter flee mode. Target of the `hunting → fleeing` reflex
when a body is seen (DESIGN.md §5.8, reflex 2). Before the fix,
three paths in `decide()`:

1. **Not localized:** return `noOpIntent()`.
2. **Flee complete** (timer expired OR distance sufficient): return
   `noOpIntent()` — stand still. Wait for directive reconciliation
   to notice the TTL expired and revert to the default hunting
   directive.
3. **Fleeing:** compute a flee target by projecting away from the
   body, clamp to map bounds, steer via `DisciplineNormal`.

### 1.2 Scratch state

- `fleeUntilTick: int` — deadline (entry tick + `fleeDurationTicks`).

### 1.3 Problems

1. **Post-flee idle.** When the flee timer expires, `decide()` returns
   `noOpIntent()`. The bot stands still until `reconcileDirective`
   notices the directive TTL expired (up to `DirectiveDefaultTtlTicks`
   = 360 ticks / ~15s) or the guidance loop issues a new directive.
   In practice the reflex sets a TTL of 240 ticks which matches the
   flee duration, so the TTL expires on roughly the same tick — but
   there's a 1-tick race where the bot visibly pauses.

   Worse: if the LLM had issued the fleeing directive with a longer
   TTL (e.g. `ttlTicks: 480`), the bot would stand idle for
   `480 - 240 = 240` ticks after fleeing completes.

2. **Flee target in walls.** The projection `(selfX + dx*2, selfY + dy*2)`
   is clamped to map bounds but not to passable terrain. If the
   resulting point lands on a wall pixel, A* returns an empty path.
   The greedy fallback (from the noop-lock fix) partially covers this
   — it steers straight toward the impassable point and jiggle handles
   wall collisions — but the movement is erratic and wastes time.
   `snapToPassable` (available in `action.nim`) would give A* a valid
   goal.

---

## 2. Design

### 2.1 Post-flee cover transition

When the flee timer expires or the minimum distance is reached,
instead of returning `noOpIntent()`, switch to cover behavior:
pick a nearby task station and navigate to it. This:

- Eliminates the idle gap (the bot is always moving).
- Makes the imposter look like a crewmate walking between tasks.
- Naturally flows into the default hunting directive's cover patrol
  once reconciliation kicks in.

Implementation: when the flee condition is satisfied, pick the
nearest task station (using `passableCX/CY`) that is in the
opposite direction from the body (to avoid walking back toward it)
and steer there. If no station is far enough away, fall back to
any station. Use `DisciplineNormal`.

The mode doesn't switch itself — it remains in `ModeFleeing` and
emits a navigating intent. The directive TTL or the next LLM
response handles the mode switch. The difference from today is that
the bot is visibly walking (not idle) during this tail period.

### 2.2 Flee target passability

Before feeding the flee target to the action layer, snap it to
passable terrain using `snapToPassable(walkMask, fleeX, fleeY)`.
This gives A* a valid goal from the start, eliminating the
greedy-fallback jitter.

If `snapToPassable` returns `found = false` (no passable pixel
within radius 32 — unlikely on skeld2), fall back to the current
behavior (raw coordinates, let greedy handle it).

### 2.3 Flee direction improvement (minor)

The current projection is `self + 2*(self - body)`. When the bot is
directly on top of the body (`dx == 0, dy == 0`), it picks an
arbitrary direction (self + 60, self). This is fine as a fallback
but could be improved by using the bot's last movement direction
if available. Deferred — the coincident-position case is rare
(bodies are placed where players die, and the imposter walks away
from the kill).

---

## 3. Scratch state changes

```nim
of ModeFleeing:
  fleeUntilTick: int               ## (exists) Flee deadline tick.
  fleeCoverTargetX: int            ## (new) Post-flee cover station world X.
  fleeCoverTargetY: int            ## (new) Post-flee cover station world Y.
  fleeCoverSet: bool               ## (new) Whether cover target has been picked.
```

---

## 4. Tuning constants

No new tuning constants. The mode uses existing values:

- `fleeMinDistance` and `fleeDurationTicks` from `ModeParams`
  (default 48 and 240 respectively).
- Station data from `referenceData.map.tasks` (existing).

---

## 5. Revised `decide()` logic (pseudocode)

```
proc decide(belief, params, scratch):
  if not localized:
    return noOpIntent()

  let dist = heuristic(selfX, selfY, params.fleeAwayFrom.x, params.fleeAwayFrom.y)

  # --- Flee complete → cover behavior ---
  if belief.tick >= scratch.fleeUntilTick or dist >= params.fleeMinDistance:
    # Pick a cover station (once).
    if not scratch.fleeCoverSet:
      scratch.fleeCoverSet = true
      let (cx, cy) = pickCoverStation(selfX, selfY, params.fleeAwayFrom)
      scratch.fleeCoverTargetX = cx
      scratch.fleeCoverTargetY = cy
    return ActionIntent(
      steerTo: Point(x: scratch.fleeCoverTargetX, y: scratch.fleeCoverTargetY),
      steerValid: true,
      discipline: DisciplineNormal, ...)

  # --- Active fleeing ---
  var fleeX = selfX + (selfX - params.fleeAwayFrom.x) * 2
  var fleeY = selfY + (selfY - params.fleeAwayFrom.y) * 2
  if dx == 0 and dy == 0:
    fleeX = selfX + 60; fleeY = selfY

  # Clamp to map bounds.
  fleeX = clamp(fleeX, 0, MapWidth - 2)
  fleeY = clamp(fleeY, 0, MapHeight - 2)

  # Snap to passable terrain.
  let (found, px, py) = snapToPassable(walkMask, fleeX, fleeY)
  if found:
    fleeX = px; fleeY = py

  return ActionIntent(
    steerTo: Point(x: fleeX, y: fleeY),
    steerValid: true,
    discipline: DisciplineNormal, ...)
```

### 5.1 `pickCoverStation` helper

Picks the nearest task station whose passable centre is:
1. At least 24 px away from the body.
2. In the "away" hemisphere: `dot(station - self, self - body) >= 0`.

Falls back to the globally nearest station if no station satisfies
both constraints.

---

## 6. Trace events

No new trace events. The existing `decisions.jsonl` captures the
discipline and steer target, which shows the transition from active
fleeing to cover navigation. The `modes.jsonl` `mode_exited` event
records the total fleeing duration.

---

## 7. Files changed

| File | Change |
|------|--------|
| `types.nim` | Add `fleeCoverTargetX`, `fleeCoverTargetY`, `fleeCoverSet` to `ModeScratch.ModeFleeing` |
| `modes/fleeing.nim` | Add post-flee cover behavior, add `snapToPassable` call on flee target, add `pickCoverStation` helper |
| `IMPL_PLAN.md` | Mark 6.6 done |
| `README.md` | Update phase table |

---

## 8. Implementation plan

### Step 1 — Type changes
- Add 3 scratch fields to `types.nim`.
- Verify: compile, existing tests pass.

### Step 2 — Rewrite decide()
- Add `pickCoverStation` helper proc.
- Replace post-flee `noOpIntent()` with cover navigation.
- Add `snapToPassable` call in the active-flee path.
- Import `action` for `snapToPassable` and `referenceData` access.
- Update `onEnter` to initialize new fields.
- Verify: compile, all tests pass.

### Step 3 — Doc updates
- Update IMPL_PLAN.md, README.md.
- Run fallback_test to ensure non-NOOP behavior preserved.

### Step 4 — Live validation
- Run `--seed 100 --force-role imposter --duration 90` with tracing
  and `imposter_cooldown_ticks=48`.
- After a kill triggers fleeing, confirm `decisions.jsonl` shows
  continued navigation (non-zero mask) after the flee timer expires.
- Confirm the flee target coordinates differ from the raw projection
  on seeds where the projection hits a wall.
