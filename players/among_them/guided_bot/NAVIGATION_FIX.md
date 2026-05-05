# Navigation Fix — Root Cause Analysis and Implementation Plan

Bug report date: 2026-05-04
Priority: HIGH
Status: Open

---

## Executive Summary

The guided bot's navigation quality is poor across four observable
symptoms: jittery/orbiting movement, missed task interaction points,
seemingly random target changes, and frequent trajectory reversal.
All four symptoms trace to a small set of interacting root causes in
the action layer (`action.nim`) and task-completing mode
(`task_completing.nim`). The A* algorithm itself is correct; the
issues are in path execution, replanning policy, and target
commitment.

---

## Symptom → Root Cause Map

| Symptom | Primary Root Cause | Secondary Causes |
|---------|-------------------|------------------|
| 1a. Jitter/orbiting | PathLookahead=4 too short; replans every 24 ticks produce path micro-shifts | Single-frame velocity dropout → false stuck detection |
| 1b. Missing task points | Path trim overshoot: bot stops 2-4px short of station | `isInsideTaskRect` 4px margin isn't enough when passable snap is at edge |
| 1c. Random nearby targets | TaskCommitTicks hysteresis documented but **not enforced** | Tier-3 selection always picks nearest → flips on 1px position change |
| 1d. Trajectory changes | No commit lock + 24-tick replans + reflexes on 48-tick cooldown | LLM directives every 120 ticks can change mode mid-navigation |

---

## Root Cause 1: Path Lookahead Too Short (4 pixels)

**Location**: `action.nim:31`

```nim
PathLookahead = 4
```

**Mechanism**: The bot picks a waypoint 4 pixels ahead on the cached
A* path and steers toward it. On a straight corridor, that waypoint
is essentially adjacent. The trim logic (`action.nim:440-446`) drops
waypoints within Manhattan distance ≤ 2, so the effective steering
window is only 2-4 pixels ahead.

**Problem**: With such a short lookahead:
- The steering angle flips rapidly at path bends (each new trimmed
  waypoint may be in a different quadrant)
- On straight paths, the direction oscillates between "on target"
  (noop) and "1px off" (full direction press), causing micro-stutter
- At corners, the bot overshoots by 1-2px (it was moving diagonally
  and the next waypoint is perpendicular), gets trimmed past the
  corner, then suddenly targets a point behind itself

**Evidence**: modulabot uses `PATH_LOOKAHEAD = 18` (4.5× larger) for
exactly this reason — smoother corner handling at the cost of slightly
wider turns.

**Why 4 was chosen**: The original design note in action.nim says
"Kept small so the waypoint stays tightly on the A* corridor through
turns. Larger values (18+) overshoot corners and cause oscillation."
This is wrong in practice — the oscillation from being TOO tight
(seeing only 4px ahead) is worse than the slight corner widening from
a 12px lookahead.

---

## Root Cause 2: Over-Aggressive Replanning (Every 24 Ticks)

**Location**: `action.nim:44`

```nim
ReplanIntervalTicks = 24
```

**Mechanism**: Every 24 ticks (~1 second), the A* path is recomputed
from the bot's current position to the current goal, regardless of
whether anything has changed.

**Problem**: The bot's position (`selfX`, `selfY`) is derived from
camera localization, which has sub-pixel jitter between frames (the
localizer accepts fits with up to 320 errors on a 128×128 frame —
the position can be ±1-2px from truth). When the A* recomputes from
a slightly different start point, the path through a corridor may
shift by 1-2 pixels laterally. Combined with the 4px lookahead, this
causes the steering target to jump sideways on every replan, producing
visible jitter.

**Evidence**: The progress-stall detector (`StallProgressTicks = 48`)
fires independently. The periodic replan is redundant with the stall
detector for all cases except "the bot is making progress along the
wrong path" — which shouldn't happen since the goal is static and A*
is deterministic for identical (start, goal) pairs.

---

## Root Cause 3: Over-Sensitive Stuck Detection (8 Frames)

**Location**: `action.nim:35`

```nim
StuckThreshold = 8
```

**Mechanism**: If velocity is zero for 8 consecutive frames while
direction buttons were emitted, jiggle fires (6 ticks of forced
perpendicular movement + path replan).

**Problem**: 8 frames at 24Hz is 333ms. Several normal scenarios
produce zero-velocity for 8+ frames:
- **Localization jitter**: The camera position updates as integers.
  If the bot moves < 1 pixel/frame (slow diagonal movement), the
  reported velocity is 0 on frames where the camera doesn't tick over
  to the next integer. A stretch of 8 such frames is common during
  diagonal movement along corridors.
- **Frame-rate variation**: If the server momentarily processes fewer
  ticks or the WebSocket batches frames, the bot can appear stationary
  for several frames.
- **Corner rounding**: At tight corners, the bot may spend several
  frames steering into the wall before the new lookahead waypoint
  clears the wall. This is normal path-following behavior, not a
  stuck condition.

When jiggle fires falsely, the bot moves perpendicular for 6 frames
(visible as orbiting/jitter), then replans. This creates a feedback
loop: false jiggle → replan from new position → slightly different
path → more jitter → more false stuck → more jiggle.

---

## Root Cause 4: Path Trim Overshoot (Missed Tasks)

**Location**: `action.nim:440-446`

```nim
while state.currentPath.len > 1:
  let first = state.currentPath[0]
  let distToFirst = heuristic(selfX, selfY, first.x, first.y)
  if distToFirst <= 2:
    state.currentPath.delete(0)
  else:
    break
```

**Mechanism**: Waypoints are dropped when the bot is within Manhattan
distance ≤ 2 of them. This means the bot never actually reaches the
final path point — it's trimmed at ≤ 2px away.

**Problem for tasks**: The Navigate→Hold transition in
`task_completing.nim:306` checks `isInsideTaskRect(selfX, selfY, ts)`
with a 4px margin. But if `passableCX/CY` is at the edge of the
station rect (common when the station center is on an impassable
pixel), the bot trims the last waypoint at 2px distance and is now
6px from the station center — potentially outside the 4px margin on
the far side.

The result: the bot arrives "near" the task, the final waypoint is
trimmed, the path is now empty, `steerButtons` points at the goal
but the bot is 2-4px off. It's not stuck (velocity may be nonzero
if oscillating), not inside the rect, and keeps micro-stepping around
the station edge.

---

## Root Cause 5: Task Commit Hysteresis Not Implemented

**Location**: `task_completing.nim:199-201`

```nim
# Hysteresis: if we have a target and the commit window hasn't
# expired, keep it even if a better one appeared. If committed
# long enough, allow re-evaluation on next Navigate entry.
```

This is a **comment only**. There is no code that actually enforces
the `TaskCommitTicks = 48` (from tuning.nim:40) hysteresis window.

**Mechanism**: On every tick where the locked target is still valid,
the bot re-enters `selectTarget` only when `targetIdx < 0` (line
191-195). But target invalidation is aggressive:
- `slot.state == TaskCompleted` → immediate unlock (line 185)
- `slot.resolvedNotMine` → immediate unlock (line 185)

More importantly, after task completion (`tcCompletedTaskIndex >= 0`),
the mode resets `tcLockedTaskIndex = -1` and immediately calls
`selectTarget` on the same tick (lines 224-229). The new target is
picked by pure nearest-distance, which can flip on each position
update.

Between tasks, the bot picks a new target every tick it moves (since
position changes, distances to candidates change, and the nearest
target flips). With tier-3 geometry fallback and many equidistant
stations, the target can oscillate between two stations on alternating
frames.

---

## Root Cause 6: Single-Frame Velocity Dropout

**Location**: `action.nim:395-396`

```nim
let velX = belief.percep.cameraX - belief.percep.lastCameraX
let velY = belief.percep.cameraY - belief.percep.lastCameraY
```

**Mechanism**: Velocity is a raw integer delta between consecutive
frame camera positions. There is no smoothing.

**Problem**: When the bot moves at sub-pixel speed on one axis (e.g.,
moving mostly horizontally with a slight vertical component), the
camera Y doesn't change every frame. On those frames, `velY = 0`. If
both axes happen to read zero on 8 consecutive frames (common during
slow diagonal movement), stuck fires.

---

## Proposed Fixes

### Fix A: Increase Path Lookahead to 12

**Change**: `action.nim:31`
```nim
PathLookahead = 12  # was 4
```

**Rationale**: 12 is a compromise between modulabot's 18 (too wide
for tight corridors) and the current 4 (too jittery). At 12px, the
bot "sees ahead" by roughly one corridor width (~12-16 game pixels
per hallway), smoothing out direction changes at corners while still
tracking the A* corridor faithfully.

**Side effects**: Slightly wider cornering (the bot will cut corners
by ~8px more). Acceptable — tighter corners just clip walls briefly
and the jiggle recovers, whereas the current jitter is persistent.

---

### Fix B: Reduce Replan Frequency to 72 Ticks

**Change**: `action.nim:44`
```nim
ReplanIntervalTicks = 72  # was 24; ~3s at 24Hz
```

**Rationale**: The periodic replan's purpose is to recover from
localizer position drift. With the stall detector at 48 ticks and
goal-change triggering immediate replans, the 72-tick periodic is a
safety net, not a primary recovery mechanism. Replanning every 3s
instead of every 1s eliminates 2/3 of the unnecessary path
recomputations that cause micro-jitter.

**Side effects**: If the localizer drifts significantly within 3s,
the bot follows a slightly wrong path for longer before correcting.
Acceptable — the stall detector catches actual stuck conditions
within 2s regardless.

---

### Fix C: Increase Stuck Threshold to 16 and Add Velocity Smoothing

**Changes**:

1. `action.nim:35`:
```nim
StuckThreshold = 16  # was 8; ~667ms at 24Hz
```

2. Add a 4-frame velocity averaging window. Replace the raw velocity
computation with a rolling average:

```nim
# In ActionState, add:
velHistory: array[4, tuple[x: int, y: int]]
velHistoryIdx: int

# In applyIntent, replace velocity computation:
state.velHistory[state.velHistoryIdx] = (velX, velY)
state.velHistoryIdx = (state.velHistoryIdx + 1) mod 4
var avgVelX, avgVelY: int
for i in 0 ..< 4:
  avgVelX += state.velHistory[i].x
  avgVelY += state.velHistory[i].y
# Stuck requires ALL 4 samples to be zero (not just average)
let isZeroVelocity = avgVelX == 0 and avgVelY == 0
```

**Rationale**: 16 frames (667ms) is more appropriate for "actually
stuck against a wall" vs "momentarily zero velocity from sub-pixel
movement". The 4-frame all-zero check eliminates false positives from
single-frame dropouts while still catching real stuck conditions
within < 1s.

---

### Fix D: Implement Task Commit Hysteresis

**Change**: `task_completing.nim`, after the target-still-valid check
(line 183-189), before `selectTarget`:

```nim
# Enforce commit hysteresis: keep the current target for at least
# TaskCommitTicks after locking, even if a nearer target appears.
if targetIdx >= 0 and
   belief.tick - scratch.tcLockTick < TaskCommitTicks:
  # Don't re-evaluate; keep current target.
  discard
elif targetIdx < 0:
  scratch.tcPhase = TpNavigate
  targetIdx = selectTarget(belief, scratch)
  if targetIdx >= 0:
    scratch.tcLockedTaskIndex = targetIdx
    scratch.tcLockTick = belief.tick
```

This replaces the current unconditional `if targetIdx < 0:
selectTarget` block. The commit window prevents target flipping for
2s after each lock.

**Rationale**: Once the bot commits to a task station, it should walk
there without re-evaluating unless the task becomes invalid (completed
or resolved-not-mine). The 48-tick (2s) window is long enough to
cross most corridors without the target distance comparison causing
oscillation.

---

### Fix E: Arrival Distance for Tasks

**Changes**:

1. `action.nim`, path-trim loop — keep at least 2 points so the
   final goal waypoint is never trimmed away:

```nim
while state.currentPath.len > 2:  # was > 1
```

2. `task_completing.nim` — remove the arrival margin entirely and use
   the server's exact task rect:

```nim
proc isInsideTaskRect(selfX, selfY: int, ts: TaskStation): bool =
  selfX >= ts.x and selfX < ts.x + ts.w and
  selfY >= ts.y and selfY < ts.y + ts.h
```

**Rationale**: The server (`sim.nim:2184-2185`) checks the player's
exact position against the task rect with zero margin. Any margin on
our side causes the bot to start holding A while still outside the
server's interaction zone, wasting 84 ticks and then looping forever.
The bot must navigate all the way into the rect before holding.

The path-trim fix ensures the final waypoint (passableCX/CY, which
is inside or at the edge of the rect) stays on the path until the
bot actually reaches it.

**Verified**: Task 2 "Fix Wires" (rect 574,269 16x16) was previously
failing indefinitely with the bot at x=569 (5px outside). After fix,
completes on first attempt.

---

### Fix F: Increase Reflex Cooldown for Non-Critical Reflexes

**Change**: `tuning.nim:20`:
```nim
ReflexCooldownTicks* = 96  # was 48; ~4s
```

**Rationale**: The body-report and body-flee reflexes fire on every
new body sighting. With 48-tick cooldown, they can interrupt
navigation every 2s. In a match with multiple bodies visible
(post-kill), this causes repeated mode switches mid-path.

4s is long enough that a single body sighting is handled without
the reflex re-firing from a slightly different camera angle of the
same body. For the voting-screen reflex (which must fire promptly),
a separate lower cooldown could be kept, but the current code uses
the same constant for all reflexes.

**Alternative**: Per-reflex cooldown values (leave voting at 48, set
body reflexes to 96). Slightly more code, better behavior.

---

## Implementation Plan

### Phase 1: Tuning Constants (Low Risk, High Impact)

Files touched: `action.nim`, `tuning.nim`

1. Change `PathLookahead` from 4 to 12
2. Change `ReplanIntervalTicks` from 24 to 72
3. Change `StuckThreshold` from 8 to 16
4. Change `ReflexCooldownTicks` from 48 to 96

These are all single-line constant changes. They can be tested
immediately with the live test suite. Expected result: smoother
corridors, fewer false jiggles, fewer reflex interrupts.

### Phase 2: Velocity Smoothing (Low Risk, Medium Impact)

Files touched: `action.nim`, `types.nim`

1. Add `velHistory` array and index to `ActionState`
2. Replace raw velocity computation with 4-frame all-zero check
3. Update `initActionState` to zero-init the history

### Phase 3: Task Commit Hysteresis (Low Risk, High Impact)

Files touched: `task_completing.nim`

1. Add the commit-window check before `selectTarget`
2. Verify that `tcLockTick` is already set on target selection (it
   is — line 197)
3. Ensure commit is bypassed on task invalidation (already handled
   by the validity check above, lines 183-189)

### Phase 4: Path Trim Fix (Low Risk, Medium Impact)

Files touched: `action.nim`, `task_completing.nim`

1. Change trim guard from `> 1` to `> 2` (keep final point)
2. Increase `isInsideTaskRect` margin from 4 to 8

### Phase 5: Validation

1. Run the existing live test suite (`live_test.py --keep-traces`)
2. Compare trace outputs:
   - Action mix should show fewer noops (currently 46-49%)
   - Task completion count should increase (currently 4 in 2000 ticks)
   - Mode transitions should be fewer and longer-lived
3. Run a full 8-bot match and observe visually via the global viewer
4. Check for regressions: imposter kills should still happen, body
   reporting should still work (just less frequently interrupted)

### Phase 6: Optional Fine-Tuning

After validation:
- If corners are still too wide with lookahead=12, try 10
- If stuck detection is too slow at 16 frames, try 12
- If commit hysteresis prevents urgent task switches, add a
  priority-override (tier-1 icon-visible overrides commit lock)
- Consider per-reflex cooldowns (voting=48, body=96)

---

## Files Modified (Complete List)

| File | Changes |
|------|---------|
| `action.nim:31` | PathLookahead 4→12 |
| `action.nim:35` | StuckThreshold 8→16 |
| `action.nim:44` | ReplanIntervalTicks 24→72 |
| `action.nim:440` | Trim guard `> 1` → `> 2` |
| `action.nim` (new) | velHistory array, 4-frame zero check |
| `types.nim` | Add velHistory/velHistoryIdx to ActionState |
| `task_completing.nim:70-75` | isInsideTaskRect: remove margin, use exact server rect |
| `task_completing.nim:191-197` | Commit hysteresis enforcement |
| `tuning.nim:20` | ReflexCooldownTicks 48→96 |

---

## Risk Assessment

All changes are parameter tuning or small logic additions:
- No new modules, no architecture changes
- A* algorithm untouched
- Mode lifecycle untouched
- LLM integration untouched
- FFI boundary untouched
- All changes are testable with the existing live_test.py suite

Worst-case regression: the bot navigates slightly wider corners and
responds to body sightings 2s slower. Both are acceptable tradeoffs
against the current severe jitter/orbiting behavior.
