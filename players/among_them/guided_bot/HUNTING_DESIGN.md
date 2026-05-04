# Phase 6.4 — `hunting` Mode Design

> **Scope:** Fix the hunting mode's cover behavior, add short-term
> target memory, and widen the kill-strike range to match the server.
>
> **Parent doc:** `DESIGN.md` §5.4, §5.8, §9.1.
>
> Last updated: 2026-05-04

---

## 1. What exists today

### 1.1 Mode handler (`modes/hunting.nim`, 121 LOC)

The imposter default mode. Three paths in `decide()`:

1. **Preferred target visible + kill ready:** steer via
   `DisciplineKillStrike`, which presses A within 16 px.
2. **Opportunistic (default):** if `killReady` and exactly 1
   visible crewmate (`witnessCount == 1`), close and strike.
3. **Cover behavior:** walk to the nearest task station via
   `DisciplineNormal`. Stand there.

### 1.2 Scratch state

- `hunTargetColor`: color of the current pursuit target.
- `hunLastSightingTick`: tick when the target was last seen
  (set but never read).
- `hunEnterTick`: tick when mode was entered.

### 1.3 Action layer (`action.nim:320-329`)

`DisciplineKillStrike` steers toward the target and ORs `ButtonA`
every tick while `dist <= KillStrikeRange (16)`. The server's actual
kill range is 20 px (`sim.nim:KillRange`). The bot presses A at 16 px
which is inside the server range — kills land, but the bot must close
to 16 px when it could strike at 20 px.

### 1.4 Problems

1. **Cover never rotates.** The imposter walks to the nearest station
   and stands there indefinitely (no loiter timer, no station
   rotation, no fake A-press). Visually indistinguishable from AFK.
   In a match with all guided_bots, imposters are extremely passive
   — they stand at one station and wait for crewmates to walk past.

2. **No target memory.** `hunLastSightingTick` is set but never read.
   When the pursuit target walks off screen, the mode instantly drops
   to cover. No "last seen at position X, go check" behavior. This
   wastes kill opportunities where the target was visible 1 second
   ago and is probably still nearby.

3. **No kill confirmation.** After pressing A, the mode doesn't check
   whether the kill succeeded (visible crewmate count decreased, or
   a body appeared). If the target moved out of range between the
   intent and the button press, the kill misses silently.

4. **KillStrikeRange conservative.** 16 px vs server's 20 px. The
   bot closes 4 px more than necessary, giving the target more time
   to walk away.

---

## 2. Design

### 2.1 Cover rotation (station-to-station patrol)

Replace the static "walk to nearest station" cover with a patrol
loop that mirrors pretending's station rotation:

1. Pick a task station (not too close, not the last one visited).
2. Navigate there via `DisciplineNormal` (using the station's
   precomputed passable centre `passableCX/CY` as the steer target,
   so A\* never receives an impassable goal).
3. On arrival, loiter for `HuntCoverLoiterTicks` (72, ~3s).
4. After loiter, pick a new station and repeat.

This keeps the imposter moving around the map, increasing the
chance of encountering an isolated crewmate. The patrol is
interruptible — any tick where a kill opportunity arises, the
mode switches from cover to pursuit.

During loiter, the imposter stands still (no A-press — that's
`pretending`'s job in 6.5). The loiter creates natural pauses
that look like the imposter is deciding where to go next.

### 2.2 Target memory

When a crewmate is seen, record their last-known world position
and the tick. When the crewmate leaves the screen:

- If `tick - hunLastSightingTick <= HuntMemoryTicks` (48, ~2s):
  continue steering toward `hunLastSeenX/Y` (the last-known
  position). The target is probably still nearby.
- After the memory window expires: drop to cover.

This gives the imposter 2 seconds of pursuit after losing visual
contact — enough to follow a target around a corner.

### 2.3 Kill confirmation

After emitting `DisciplineKillStrike` and entering kill range:

- Track `hunStrikeTick` — the tick when A was first pressed in
  range. Also snapshot `hunPreStrikeBodyCount` (visible body count)
  and `hunPreStrikeKillReady` (should be true).
- On subsequent ticks, check two signals:
  - **Body appeared near target.** A new entry in
    `belief.percep.visibleBodies` whose world position is within
    `HuntKillConfirmRadius` (30 px) of the strike target's
    last-known position. The server replaces the crewmate sprite
    with a body sprite on kill, so a body appearing where the
    target was standing is strong positive evidence.
  - **Kill cooldown reset.** `belief.percep.killReady` went from
    true to false. The server resets the imposter's cooldown on a
    successful kill, which changes the HUD kill-button sprite from
    lit to shadowed.
- **Confirmed** when both signals fire within
  `HuntKillConfirmTicks` (12, ~0.5s) of the strike: log a trace
  event, drop to cover, wait out cooldown.
- **Missed** if the confirm window expires without both signals:
  the kill didn't land (target moved, server rejected). Drop to
  cover. Don't waste more time — the cooldown may or may not have
  reset depending on whether A even registered as a fresh press.

Using body-appearance + cooldown-reset together avoids false
positives from crewmates simply walking off-screen (which would
fool a naive "visible crewmate count decreased" check). A body at
the target's position is specific; cooldown going false is
corroborating.

### 2.4 KillStrikeRange bump

Change `KillStrikeRange` from 16 to 20 in `action.nim` to match
the server's `KillRange`. The bot can press A 4 px earlier, giving
targets less time to escape.

### 2.5 Witness check relaxation

The current opportunistic check requires `witnessCount == 1` (exactly
one visible crewmate). This is correct per DESIGN.md (`max_witnesses:
0` in the default directive). However, `witnessCount` counts all
visible crewmates — including the target. The check should be
`witnessCount - 1 <= hunMaxWitnesses` (exclude the target from the
witness count). The current code already does this for the preferred-
target path but not for the opportunistic path.

Actually, re-reading the code: the opportunistic path checks
`witnessCount == 1`, meaning the only visible crewmate IS the target.
That's `0 other witnesses`, which matches `hunMaxWitnesses: 0`. This
is correct. No change needed.

---

## 3. Scratch state changes

```nim
of ModeHunting:
  hunTargetColor: int             ## (exists) Color of pursuit target.
  hunLastSightingTick: int        ## (exists) Tick target was last seen.
  hunEnterTick: int               ## (exists) Tick mode was entered.
  hunLastSeenX: int               ## (new) World X of last sighting.
  hunLastSeenY: int               ## (new) World Y of last sighting.
  hunCoverTargetIndex: int        ## (new) Station index for cover patrol.
  hunCoverLoiterUntilTick: int    ## (new) Loiter deadline at station.
  hunStrikeTick: int              ## (new) Tick when kill-strike A was first pressed.
  hunStrikeTargetX: int           ## (new) World X of target at strike time.
  hunStrikeTargetY: int           ## (new) World Y of target at strike time.
  hunPreStrikeBodyCount: int      ## (new) Visible body count before strike.
  hunPreStrikeKillReady: bool     ## (new) killReady state before strike.
```

---

## 4. Tuning constants

| Constant | Value | Rationale |
|---|---|---|
| `HuntCoverLoiterTicks` | 72 | Loiter at each cover station ~3s before moving. Short enough to keep patrolling. |
| `HuntMemoryTicks` | 48 | Pursue last-known position for ~2s after losing visual contact. |
| `HuntKillConfirmTicks` | 12 | Check for kill success within ~0.5s of striking. |
| `HuntKillConfirmRadius` | 30 | World-pixel radius for matching a new body to the strike target position. |

`KillStrikeRange` in `action.nim` changes from 16 to 20 (not a tuning.nim constant — it's local to the action layer).

---

## 5. Trace events

### 5.1 `kill_attempted`

Emitted when the bot first presses A in kill-strike range.

```json
{ "t": <tick>, "kind": "kill_attempted",
  "target_color": <int>,
  "distance": <int>,
  "witnesses": <int> }
```

### 5.2 `kill_confirmed`

Emitted when a new body appears near the strike target AND killReady
goes false within the confirm window.

```json
{ "t": <tick>, "kind": "kill_confirmed",
  "target_color": <int>,
  "ticks_since_strike": <int>,
  "body_distance": <int> }
```

---

## 6. Files changed

| File | Change |
|---|---|
| `types.nim` | Expand `ModeScratch.ModeHunting` with 8 new fields |
| `tuning.nim` | Add 4 constants |
| `action.nim` | `KillStrikeRange` 16 → 20 |
| `modes/hunting.nim` | Rewrite cover behavior (patrol loop), add target memory, add kill confirmation. Update `onEnter`. |
| `bot.nim` | Emit `kill_attempted` and `kill_confirmed` trace events |
| `DESIGN.md` | Add trace event schemas to §11.2 |
| `IMPL_PLAN.md` | Mark 6.4 done |
| `README.md` | Update phase table |

---

## 7. Implementation plan

### Step 1 — Type + tuning + KillStrikeRange
- Add 5 scratch fields to `types.nim`.
- Add 3 tuning constants.
- Bump `KillStrikeRange` to 20 in `action.nim`.
- Verify: compile, existing tests pass.

### Step 2 — Rewrite hunting.decide()
- Cover patrol: station selection, navigation, loiter timer.
- Target memory: record last-seen position, pursue for
  `HuntMemoryTicks` after losing visual.
- Kill confirmation: track strike tick, check crewmate count.
- Update `onEnter` for new scratch fields.
- Verify: compile, all tests pass.

### Step 3 — Trace events in bot.nim
- Emit `kill_attempted` on strike-range entry.
- Emit `kill_confirmed` on crewmate count decrease.
- Verify: compile, all tests pass.

### Step 4 — Doc updates + live game validation
- Update DESIGN.md, IMPL_PLAN.md, README.md.
- Run all test suites + library build.
- 180s 8-bot match — verify imposters patrol, attempt kills, and
  (if a kill lands) that meetings are triggered by crewmates
  seeing bodies.
