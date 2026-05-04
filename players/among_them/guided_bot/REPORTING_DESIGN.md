# Phase 6.2 — `reporting` Mode Design

> **Scope:** Fix the reporting mode's failure paths: add a give-up
> timeout, body-visibility check, and approach-retry logic. Wire
> trace events for report attempts.
>
> **Parent doc:** `DESIGN.md` §5.4 (mode enumeration), §5.8 (reflex 1:
> body → reporting), §6 (action intent / `DisciplineReport`).
>
> Last updated: 2026-05-01

---

## 1. What exists today

### 1.1 Mode handler (`modes/reporting.nim`, 52 LOC)

The mode is minimal:
- `isLegalFor`: crewmate, alive, not ghost.
- `onEnter`: records `repEnterTick` in scratch.
- `decide`: if localized, emit `ActionIntent` with
  `steerTo = params.repBodyLocation`, `discipline = DisciplineReport`.
  Otherwise no-op.
- No lifecycle, no state machine, no checks.

### 1.2 Action layer (`action.nim:331-340`)

`DisciplineReport` steers toward the target and ORs in `ButtonA`
every tick while Manhattan distance ≤ `ReportRange = 20` px. This
is correct — the server uses ButtonA (`input.attack`) for reports
and requires a fresh-press edge (first tick in range provides this).

### 1.3 Reflex trigger (`reflex.nim:91-117`)

Reflex 1 fires when a new body appears while in `ModeTaskCompleting`
(crewmate, alive, not ghost). It creates a reporting directive with:
- `repBodyLocation`: world-space position of the body (computed from
  screen coords + camera offset at the moment the body was seen).
- `ttlTicks: 480` (~20 s timeout).

### 1.4 Success path (already working)

Report succeeds → server starts meeting → voting screen appears →
reflex 4 (`voting_screen_appeared`) fires → mode switches to
`meeting`. The reporting mode doesn't need to detect success because
the reflex system handles it automatically.

### 1.5 Problems

1. **No body-visibility check.** The mode steers at a stale
   `repBodyLocation` forever. If the body despawns (another player
   reported it, or the server cleaned it up), the bot walks to
   where the body *was* and presses A at empty space until the
   directive TTL expires (up to 480 ticks / 20 s).

2. **No approach timeout.** If A\* can't find a path to the body
   (body is in an unreachable location, or the walk mask is wrong),
   the bot navigates fruitlessly until TTL. (Partially mitigated by
   the greedy-steering fallback in `action.nim` — the bot will at
   least move toward the body in a straight line instead of freezing.
   See DESIGN.md §6.3.)

3. **No in-range timeout.** If the bot reaches report range and
   presses A but nothing happens (e.g. the body was just barely
   outside the server's actual report radius, or there's a race
   condition), the mode keeps pressing A indefinitely.

4. **No trace events.** DESIGN.md §11.2 defines `body_reported`
   but it's never emitted. There's no way to see in traces whether
   reports were attempted, succeeded, or timed out.

---

## 2. Design

The fix adds a lightweight state machine to `decide()` with three
checks that cause the mode to give up and return to the default:

### 2.1 Body-visibility check

Every tick, check whether `belief.percep.visibleBodies` contains a
body near `repBodyLocation`. "Near" means within
`ReportBodyMatchRadius = 30` world pixels — generous enough to
handle camera jitter and sprite-centre vs. anchor offsets.

If the body is still visible: continue navigating / pressing A.

If the body is NOT visible for `ReportBodyMissFrames = 36`
consecutive frames (~1.5 s): give up. The body likely despawned.
Switch back to the default directive.

The miss counter resets to 0 whenever a matching body is seen. This
debounces single-frame detection failures (body sprite flicker
between animation poses, partial occlusion).

### 2.2 Approach timeout

If the bot has been in reporting mode for more than
`ReportApproachTimeoutTicks = 240` (~10 s) and has not yet entered
report range (never had `dist <= ReportRange`): give up. The path
is likely unreachable.

The timeout is tracked via `repEnterTick` (already in scratch) and
a new `repReachedRange` bool flag in scratch.

### 2.3 In-range timeout

Once the bot enters report range and starts pressing A, track how
long it stays in range without a meeting starting. If
`ReportInRangeTimeoutTicks = 72` (~3 s) elapse with the bot
in range and `belief.self.phase` is still `PhaseGameplay` (no
meeting started): give up. The report didn't register.

3 seconds is generous — the server processes the report on the fresh-
press edge, and the meeting transition should happen within a few
ticks. 72 ticks provides ample debounce.

### 2.4 Give-up behavior

When any of the three checks triggers, the mode doesn't switch
itself — it signals via a scratch field (`repGaveUp = true`), and
`bot.nim` detects this after `decide()` and performs a mode switch
to the default directive. This parallels the `tcCompletedTaskIndex`
pattern from 6.1: the mode signals, the pipeline acts.

Alternatively, since reporting has a TTL (480 ticks) set by the
reflex, the mode can simply return `noOpIntent()` and let the TTL
expire naturally. But active give-up is faster and more traceable.

**Decision: the mode returns `noOpIntent()` on give-up, and
`bot.nim` detects the transition and switches to the default
directive.** This is simpler than adding a new signal field — the
mode already returns `noOpIntent()` when not localized, so
extending that pattern to "gave up" is natural. The bot pipeline
already runs `reconcileDirective` which checks `isLegalFor` — but
reporting stays legal for alive crewmates even when the body is
gone, so we need the mode itself to stop requesting movement.

Actually, the simplest approach: **the mode itself calls
`defaultDirectiveFor` or returns a sentinel.** But modes don't have
access to the mode registry. The cleanest pattern consistent with
the existing architecture:

**The mode returns `noOpIntent()` when it gives up, and relies on
the directive TTL (480 ticks) to eventually expire and switch to
the default.** The give-up checks prevent the bot from walking
fruitlessly — it stands still instead. The TTL is the backstop
that actually performs the mode switch. The 480-tick TTL minus the
time already spent means the bot idles for at most a few seconds
after giving up.

**No, better approach:** Add a `repGaveUp` bool to scratch. In
`bot.nim`, after `decide()`, if `modeScratch.mode == ModeReporting`
and `modeScratch.repGaveUp`, force a switch to the default
directive immediately. This is cleaner and avoids the idle wait.

### 2.5 Summary of changes

The mode gains:
- **Body-miss counter** (`repBodyMissCount`): incremented when no
  matching body is visible, reset when a match is found.
- **Reached-range flag** (`repReachedRange`): set when the bot
  first enters `ReportRange`.
- **In-range timer** (`repInRangeTicks`): counts ticks spent in
  report range without a meeting starting.
- **Gave-up flag** (`repGaveUp`): set when any give-up check
  fires. `bot.nim` reads this after `decide()`.

---

## 3. Trace events

### 3.1 `report_attempted`

Emitted once when the bot first enters report range (A-press
starts). Logged in `bot.nim` by detecting the `repReachedRange`
transition from false to true.

```json
{ "t": <tick>, "kind": "report_attempted",
  "body_x": <int>, "body_y": <int>,
  "self_x": <int>, "self_y": <int>,
  "distance": <int> }
```

### 3.2 `report_gave_up`

Emitted when the mode gives up.

```json
{ "t": <tick>, "kind": "report_gave_up",
  "reason": "body_gone" | "approach_timeout" | "in_range_timeout",
  "ticks_in_mode": <int>,
  "reached_range": <bool> }
```

---

## 4. Tuning constants

| Constant | Value | Rationale |
|---|---|---|
| `ReportBodyMatchRadius` | 30 | World-pixel radius for matching a visible body to the target location. Generous for camera jitter + sprite anchor offset. |
| `ReportBodyMissFrames` | 36 | Consecutive frames without a matching body before giving up (~1.5 s). Debounces flicker. |
| `ReportApproachTimeoutTicks` | 240 | Give up navigating after 10 s without reaching range. |
| `ReportInRangeTimeoutTicks` | 72 | Give up pressing A after 3 s in range without a meeting starting. |

---

## 5. Scratch state changes

```nim
of ModeReporting:
  repEnterTick: int              ## (exists) Tick when mode was entered.
  repBodyMissCount: int          ## (new) Consecutive frames without body match.
  repReachedRange: bool          ## (new) True once dist <= ReportRange.
  repInRangeTicks: int           ## (new) Ticks spent in range without meeting.
  repGaveUp: bool                ## (new) Set when any give-up check fires.
  repGaveUpReason: string        ## (new) "body_gone" / "approach_timeout" / "in_range_timeout".
```

---

## 6. Files changed

| File | Change |
|---|---|
| `types.nim` | Expand `ModeScratch.ModeReporting` with 5 new fields |
| `tuning.nim` | Add 4 new constants (§4) |
| `modes/reporting.nim` | Rewrite `decide()` with body-visibility check, approach timeout, in-range timeout, gave-up flag. Update `onEnter`. |
| `bot.nim` | After `decide()`, check `repGaveUp` and force default directive. Emit trace events. |
| `DESIGN.md` | Add `report_attempted` and `report_gave_up` to §11.2 |
| `IMPL_PLAN.md` | Mark 6.2 done |
| `README.md` | Update phase table |

---

## 7. Implementation plan

### Step 1 — Type + tuning foundations
- Add new scratch fields to `types.nim`.
- Add 4 tuning constants to `tuning.nim`.
- Verify: compile, existing tests pass.

### Step 2 — Rewrite `reporting.decide()`
- Add body-visibility check with miss counter.
- Add approach timeout check.
- Add in-range timeout check.
- Set `repGaveUp` + `repGaveUpReason` on any give-up.
- When gave up, return `noOpIntent()`.
- Update `onEnter` for new scratch fields.
- Verify: compile, existing tests pass.

### Step 3 — Wire give-up + trace events in `bot.nim`
- After `decide()`, check `repGaveUp` and switch to default.
- Emit `report_attempted` on `repReachedRange` transition.
- Emit `report_gave_up` on give-up.
- Verify: compile, all tests pass.

### Step 4 — Doc updates
- DESIGN.md §11.2: add two new trace event schemas.
- IMPL_PLAN.md: mark 6.2 done.
- README.md: update phase table.

### Step 5 — Full test pass + live game validation
- Run all 8 Nim test suites + Python action table test.
- Library build.
- 30 s live local match with tracing.
- Read traces to confirm: report_attempted event fires when bot
  reaches a body, and give-up fires if the body despawns or
  the TTL expires.
