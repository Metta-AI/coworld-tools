# Pretending Mode — Design Document

> **Canonical reference** for the `pretending` mode handler. All
> pretending-mode design details live here; `DESIGN.md` contains only
> a brief overview and cross-reference.
>
> **Implementation:** `modes/pretending.nim` (140 LOC)
>
> Last updated: 2026-05-05

---

## 1. Purpose and role

The `pretending` mode is the imposter's cover behavior — walking
task-to-task and faking task interactions to appear like a working
crewmate. It is:

- **The imposter's cover mode.** Used between kills to blend in. The
  `hunting` mode's `cover_mode` parameter references this mode
  (currently unused for delegation, but semantically this is what
  the imposter does when not actively killing).
- **The source of the `pretending → hunting` reflex**
  (`reflex.nim:147-176`). When a lone crewmate is in kill range with
  kill ready, the reflex fires and switches to `hunting` for the
  opportunistic kill.
- **Not a default directive.** The imposter's default is `hunting`
  (with `opportunistic: true`), not `pretending`. The LLM issues
  `pretending` when it wants explicit cover behavior without the
  risk profile of hunting's opportunistic kills.

The mode is **only legal** for an alive, non-ghost imposter
(`isLegalFor` in `modes/pretending.nim:24-25` checks role, alive,
and ghost state).

---

## 2. Mode parameters

The LLM (or default system) sets these when issuing a `pretending`
directive:

```
pretending {
  preTarget: TaskTarget           # Which station to visit (currently unused
                                  #   by decide() — reserved for LLM-directed
                                  #   station targeting)
  preLoiterTicks: int             # Total loiter duration at each station
  preMaySwapOnWitness: bool       # End loiter early if a crewmate appears
}
```

Implementation in `types.nim:251-253`:
```nim
of ModePretending:
  preTarget*: TaskTarget
  preLoiterTicks*: int
  preMaySwapOnWitness*: bool
```

**Default params** (from `modes/pretending.nim:27-33`):
- `preTarget: TaskTarget(kind: TgtNearestAny, taskIndex: -1, roomId: -1)`
- `preLoiterTicks: 96` (~4s)
- `preMaySwapOnWitness: true`

---

## 3. Decision logic overview

`decide()` evaluates each tick:

1. **Pre-check** — if not localized or no task stations exist, emit
   `noOpIntent()`.
2. **Loitering** — if currently loitering at a station:
   - Check witness-swap condition.
   - Otherwise, sub-phase dispatch: fake-hold or linger.
3. **Loiter expired** — clear state, fall through to target selection.
4. **Target selection** — pick the nearest station that's >30 px away,
   using a tick-based rotation offset.
5. **Arrival check** — if inside the station rect (8 px margin), start
   loiter with fake-hold.
6. **Navigation** — steer toward station with `DisciplineNormal`.

```
     ┌──────────┐      inside station+8px    ┌─────────────┐    timer    ┌────────┐
     │ Navigate ├───────────────────────────► │ Fake-hold A ├──────────► │ Linger │
     └────┬─────┘                             └─────────────┘            └───┬────┘
          │                                                                  │
          │  ◄── loiter timer expires OR witness swap ───────────────────────┘
          │
          ▼
   (re-select station, loop)
```

---

## 4. Station selection

Runs when `preFakeTargetIndex < 0` (no target locked).

**Algorithm** (`modes/pretending.nim:92-105`):
1. Compute a rotation offset: `(belief.tick div 100) mod tasks.len`.
   This slowly rotates the search start across the station list over
   time, preventing the imposter from always visiting the same subset.
2. Starting from the offset, iterate through all stations. Pick the
   one that:
   - Is more than 30 px away from the bot's current position.
   - Is the nearest qualifying station (minimum Manhattan distance).
3. Fallback: if no station is >30 px away, picks the station at the
   rotation offset index (degenerate case on very small maps).

Uses `passableCX/CY` (walk-mask-snapped centre) as the navigation
goal for each candidate.

---

## 5. Arrival detection

Arrival is detected when the bot is within an 8 px margin of the
station's bounding rect:

```nim
selfX >= ts.x - margin and selfX < ts.x + ts.w + margin and
selfY >= ts.y - margin and selfY < ts.y + ts.h + margin
```

The 8 px margin is more generous than `task_completing`'s arrival
check (which uses the exact server rect with no margin). This is
intentional: the imposter doesn't need to be precisely at the task
interaction point, just visually close enough to look plausible.

---

## 6. Loiter behavior

On arrival, loitering starts with two sub-phases:

### 6.1 Fake-hold sub-phase

- **Duration:** `PreFakeHoldTicks` (60 ticks, ~2.5s). Clamped to
  `params.preLoiterTicks` if the loiter is shorter.
- **Discipline:** `DisciplineTaskHold` — press A, no movement.
- **Purpose:** mimics a crewmate performing a task. The A-press does
  not actually complete a task (the server requires the player's
  assigned task stations to match; pressing A at a non-assigned
  station is silently ignored).
- **Observable effect:** to an observer (human or bot), the imposter's
  sprite faces the station and appears to be working.

### 6.2 Linger sub-phase

- **Duration:** remainder of `preLoiterTicks - PreFakeHoldTicks`
  (36 ticks by default, ~1.5s).
- **Discipline:** `noOpIntent()` — stand still, no buttons.
- **Purpose:** simulates the post-completion pause before walking to
  the next task. A crewmate doesn't instantly start moving after
  finishing a task — there's a natural pause.

### 6.3 Timing

With defaults (`preLoiterTicks: 96`, `PreFakeHoldTicks: 60`):
- Fake-hold: ticks 0–59 of loiter (~2.5s pressing A).
- Linger: ticks 60–95 of loiter (~1.5s standing still).

If `preLoiterTicks < PreFakeHoldTicks`, the entire loiter is
fake-hold (no linger phase).

---

## 7. Witness swap

When `preMaySwapOnWitness` is true and a crewmate appears during
loiter:

1. **Detection:** `belief.percep.visibleCrewmates.len > 0` while
   loitering (checked each tick during loiter).
2. **Action:** end loiter early — clear `preLoiterUntilTick`,
   `preFakeHoldUntilTick`, and `preFakeTargetIndex`.
3. **Effect:** falls through to target selection on the same tick.
   The rotation-offset logic avoids re-picking a station within 30 px
   (typically the same one), so the bot immediately walks away.

**Rationale:** if a crewmate sees the imposter at a station for a
long time without the task completing, that's suspicious. Leaving
early looks like the imposter "just finished" and is moving on.

**Once-per-loiter:** the swap sets `preWitnessSwapped = true`,
preventing re-triggering within the same loiter period. A new loiter
resets the flag.

---

## 8. Scratch state

All fields are reset on mode entry (`onEnter`). Preserved across
directive changes within the same mode (per `DESIGN.md` §5.6).

```nim
of ModePretending:
  preFakeTargetIndex*: int         # Current station index (-1 = none).
  preLoiterUntilTick*: int         # Loiter deadline (0 = not loitering).
  preEnterTick*: int               # Tick when mode was entered.
  preFakeHoldUntilTick*: int       # Fake-hold sub-phase deadline.
  preWitnessSwapped*: bool         # Whether swap fired this loiter.
```

Initial values on `onEnter`:
- `preFakeTargetIndex = -1` (no target)
- `preLoiterUntilTick = 0` (not loitering)
- `preFakeHoldUntilTick = 0`
- `preWitnessSwapped = false`
- `preEnterTick = belief.tick`

---

## 9. Tuning constants

| Constant | Value | Location | Meaning |
|---|---|---|---|
| `PreFakeHoldTicks` | 60 | `tuning.nim:52` | Fake A-press duration during loiter (~2.5s). |

The loiter duration (`preLoiterTicks: 96`) is a mode parameter, not
a tuning constant — the LLM can override it per-directive.

The arrival margin (8 px) and minimum-distance threshold (30 px) are
local constants in `modes/pretending.nim`, not exported to `tuning.nim`.

---

## 10. Reflex interactions

### 10.1 Outgoing reflexes (pretending → other modes)

| Condition | Target mode | Params issued | Reflex name |
|---|---|---|---|
| `killReady AND visibleCrewmates == 1` (lone crewmate in range) | `hunting` | `huntPreferredTarget: <color>, huntMaxWitnesses: 0, huntOpportunistic: false, huntCoverMode: pretending`, TTL 120 | `lone_crew_kill_opportunity` |

This reflex fires from any sub-phase (navigating, fake-hold, or
linger). It checks mode identity, not scratch state
(`reflex.nim:148` checks `mode == ModePretending`).

The reflex is **aggressive** — it fires without LLM approval whenever
the conditions are met. If the LLM doesn't want opportunistic kills
(e.g. during a deliberate alibi-building strategy), it should use
`alibi_building` mode instead of `pretending`.

### 10.2 Incoming reflexes (other modes → pretending)

None. The LLM issues `pretending` directives explicitly. No reflex
targets this mode.

### 10.3 Voting screen

The `voting_screen_appeared` reflex (highest priority) fires from
**any** mode including `pretending`, switching to `meeting`.

### 10.4 Cooldown

The `lone_crew_kill_opportunity` reflex is subject to
`ReflexCooldownTicks` (96 ticks, ~4s). If the kill opportunity
persists after the hunting mode's TTL expires and the bot returns
to pretending, the reflex can re-fire after the cooldown.

---

## 11. Trace events

No mode-specific trace events are emitted. The existing
`decisions.jsonl` records the discipline (`DisciplineTaskHold` vs
`DisciplineNormal` vs `DisciplineNoOp`) which is sufficient to see:
- When the bot is navigating (Normal).
- When it's fake-holding at a station (TaskHold).
- When it's lingering (NoOp).

Mode entry/exit is logged by the standard `modes.jsonl` events.

---

## 12. Action layer contract

The mode communicates with the action layer via two disciplines:

- **`DisciplineNormal`** — used during navigation. The action layer
  uses A\* pathfinding on the walk mask to reach `steerTo`.
- **`DisciplineTaskHold`** — used during the fake-hold sub-phase.
  The action layer emits `ButtonA` with no directional buttons
  (`action.nim:316-321`). The mode also sets `pressA: true`
  redundantly (the discipline is authoritative).

During linger, the mode returns `noOpIntent()` — no buttons, no
movement.

---

## 13. LLM snapshot context

The pretending mode's internal scratch state is **not** included in
LLM snapshots. The LLM sees:

- `current_mode: { "name": "pretending", "source": "llm" | "default", "ticks_active": <int> }`
- Perception data (visible crewmates — relevant for the LLM to know
  who's watching).
- Memory (per-player summaries).

The LLM can influence behavior by adjusting `preLoiterTicks` (shorter
loiters = more movement = less risk of being caught idle) or
`preMaySwapOnWitness` (false = hold position even when observed,
useful if the imposter wants to be seen "doing tasks").

---

## 14. Relationship to hunting's cover patrol

Both `pretending` and `hunting`'s cover patrol (§7 in
`HUNTING_DESIGN.md`) implement station-to-station movement with
loitering. The differences:

| Aspect | `pretending` | `hunting` cover patrol |
|---|---|---|
| Fake A-press | Yes (`DisciplineTaskHold`) | No (`noOpIntent()` during loiter) |
| Witness swap | Yes (ends loiter on crewmate appearance) | No |
| Kill-seeking | Via reflex only (opportunistic trigger) | Active (priority cascade checks kill opportunity every tick) |
| Station selection | Tick-modulo rotation, nearest >30 px | Linear rotation from current index, nearest >30 px |
| Loiter duration | 96 ticks (param) | 72 ticks (`HuntCoverLoiterTicks`) |

The `hunting` mode's `huntCoverMode` parameter exists to delegate
cover behavior to this mode in a future version — currently unused.

---

## 15. Open questions

1. **Station selection determinism.** The tick-modulo offset
   (`belief.tick div 100 mod tasks.len`) makes station choice
   somewhat predictable to an observer who knows the tick count.
   A randomized selection (using a seeded PRNG) would be less
   predictable. Low priority — human observers can't see tick counts.

2. **Witness swap re-triggering.** After a swap, the bot picks a new
   station and walks there. If another crewmate is visible during
   navigation, nothing special happens (the swap only fires during
   loiter). If the same crewmate follows and is visible when the bot
   arrives at the new station and starts loitering, the swap fires
   again immediately. This could look erratic. A cooldown on witness
   swaps (per-mode-entry or timed) could help. Low priority.

3. **preTarget parameter.** The `preTarget: TaskTarget` param exists
   but `decide()` never reads it — station selection always uses the
   built-in rotation logic. A future LLM-directed path could use
   `TgtIndex` or `TgtSpecificRoom` to send the imposter to a
   specific station for strategic cover.
