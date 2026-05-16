# Idle Mode — Design Document

> **Canonical reference** for the `idle` mode handler. All idle-mode
> design details live here; `DESIGN.md` contains only a brief overview
> and cross-reference.
>
> **Implementation:** `modes/idle.nim`
>
> Last updated: 2026-05-12

---

## 1. Purpose and role

The `idle` mode is the bot's startup behavior — the bootstrap that
runs before the role is known. It is:

- **The initial mode for all bots.** `initBot` constructs scratch
  with `ModeScratch(mode: ModeIdle)` (`bot.nim:69`). The bot starts
  in idle on the very first frame.
- **The startup movement bootstrap.** Idle emits non-zero movement masks from
  frame 1, before localization or role detection. That keeps the bot active
  while Coworld validation and gameplay are still establishing context.
- **Transient by design.** Once the role is detected (crewmate or
  imposter), `reconcileDirective` (`bot.nim:241-247`) detects the
  stale idle default and immediately switches to `task_completing`
  (crewmate/ghost) or `hunting` (imposter). Idle typically runs for
  only 5–30 frames.
- **The fallback for unknown/dead states.** `defaultDirectiveFor`
  returns `ModeIdle` when the bot is dead (not ghost) or the role is
  still unknown (`mode_registry.nim:104, 107`).

The mode is **always legal** — `isLegalFor` returns `true`
unconditionally (`modes/idle.nim:17-19`). Any role, any phase.

---

## 2. Mode parameters

```text
idle {
  idleLingerAt: Point     # Optional localized linger point.
  idleLingerValid: bool   # Whether idleLingerAt is meaningful.
  idleNearGroup: bool     # Prefer moving toward visible players.
}
```

Implementation in `types.nim:234-237`:
```nim
of ModeIdle:
  idleLingerAt*: Point
  idleLingerValid*: bool
  idleNearGroup*: bool
```

**Default params** (from `modes/idle.nim:22-26`):
- `idleLingerValid: false` (no linger point)
- `idleNearGroup: true`

When localized, `decide()` consumes these params: `idleNearGroup` steers
toward the first visible crewmate, and `idleLingerValid` steers toward
`idleLingerAt` when no group target is selected. Before localization,
the mode still uses tick-based wandering because world-space targets are
not yet meaningful.

---

## 3. Decision logic overview

`decide()` has three paths:

1. **Interstitial** — during voting screens, role reveals, or
   game-over: emit `noOpIntent()`. No useful movement is possible.
2. **Localized** — steer toward a visible crewmate when `idleNearGroup`
   is true and one is visible; otherwise steer to `idleLingerAt` when
   valid; otherwise steer toward map centre (`MapWidth/2, MapHeight/2`).
3. **Not localized** — cycle through cardinal directions (up, right,
   down, left) every `IdleWanderPeriod` (36) ticks, with
   `DisciplineWander` and `steerValid: false`.

---

## 4. Pre-localization wander

Before the localizer locks, the bot can't use waypoint routing or
world-space steering. The idle mode works around this by emitting raw
directional buttons.

**Direction cycling:** `(elapsed div IdleWanderPeriod) mod 4` produces
a phase 0–3, mapping to Up, Right, Down, Left. The bot changes
direction every 36 ticks (~1.5s).

**Encoding:** the direction phase is encoded in `steerTo.x` with
`steerValid: false`. The action layer's `DisciplineWander` handler
(`action.nim:298-305`) reads this and emits the corresponding button.

**Purpose:** movement generates fresh map pixels for the localizer's
patch-search algorithm. Without movement, the localizer may see only
a static crop that doesn't match uniquely to the map, preventing a
lock.

---

## 5. Post-localization wander

Once `belief.percep.localized` is true, the mode steers toward the
map centre (`MapWidth div 2, MapHeight div 2`) with `steerValid: true`
and `DisciplineWander`.

**Purpose:** moving toward the centre:
- Provides the localizer with diverse map pixels (strengthens lock).
- Moves the bot away from spawn edges toward the gameplay area.
- Ensures continued non-zero button masks for the validation gate.

**Action layer behavior:** when `steerValid` is true,
`DisciplineWander` uses `steerButtons` to compute direction toward
the goal (`action.nim:292-297`). This is simple directional steering
(no waypoint route) — adequate for the few frames before the
role transition fires.

---

## 6. Scratch state

Minimal — only tracks the entry tick for direction-phase computation.

```nim
of ModeIdle:
  idleEnterTick*: int    # Tick when idle mode was entered.
```

Initial value on `onEnter`:
- `idleEnterTick = belief.tick`

---

## 7. Tuning constants

| Constant | Value | Location | Meaning |
|---|---|---|---|
| `IdleWanderPeriod` | 36 | `tuning.nim:43` | Ticks per direction change (~1.5s). |

Map centre is derived from `MapWidth` and `MapHeight` (constants in
`constants.nim`), not from tuning.

---

## 8. Reflex interactions

### 8.1 Incoming reflexes (other modes → idle)

None. Idle is entered via:
- Bot initialization (`initBot`).
- `defaultDirectiveFor` when role is unknown or bot is dead (not
  ghost).

### 8.2 Outgoing transitions (idle → other modes)

| Condition | Target mode | Mechanism |
|---|---|---|
| Role detected as crewmate | `task_completing` | `reconcileDirective` stale-default re-evaluation (`bot.nim:241-247`) |
| Role detected as imposter | `hunting` | Same mechanism |
| Voting screen appears | `meeting` | `voting_screen_appeared` reflex (fires from any mode) |

The idle→role transition is the primary exit path. It fires the tick
after `belief.self.role` changes from `RoleUnknown`, without waiting
for the LLM.

---

## 9. Action layer contract

The mode uses a single discipline:

- **`DisciplineWander`** — raw directional movement without
  localization or waypoint routing (`action.nim` `DisciplineWander`
  branch).
  - When `steerValid: true`: emits direction buttons toward `steerTo`
    using `steerButtons`.
  - When `steerValid: false`: reads `steerTo.x` as a direction phase
    (0=Up, 1=Right, 2=Down, 3=Left) and emits the corresponding
    button.

This discipline exists specifically for idle mode. No other mode
uses it.

---

## 10. LLM snapshot context

Idle exposes a compact mode summary in LLM snapshots:

- `current_mode.name/source/ticks_active`.
- `current_mode.params`, including linger point and near-group flag.
- `current_mode.summary`, including localization/interstitial status,
  linger validity, near-group flag, and ticks in mode.

---

## 11. Open questions

1. **Post-localization discipline choice.** Once localized, the mode
   could use `DisciplineNormal` (waypoint-backed) instead of
   `DisciplineWander` for more reliable navigation. However, idle
   only runs for a few frames post-localization before the role
   transition fires, so the quality difference is negligible.

3. **Dead-bot behavior.** When a bot is dead (not ghost), it enters
   idle. The mode emits movement buttons, but dead bots can't move.
   This is harmless (server ignores input from dead players) but the
   mode could detect `not belief.self.alive` and emit `noOpIntent()`
   to be explicit. Low priority — the state is transient.
