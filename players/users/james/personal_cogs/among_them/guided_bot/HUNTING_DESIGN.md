# Hunting Mode — Design Document

> **Canonical reference** for the `hunting` mode handler. All hunting-mode
> design details live here; `DESIGN.md` contains only a brief overview and
> cross-reference.
>
> **Implementation:** `modes/hunting.nim`
>
> Last updated: 2026-05-12

---

## 1. Purpose and role

The `hunting` mode is the imposter's kill-seeking behavior. It is:

- **The imposter's default directive** (`DESIGN.md` §9.1). When no LLM
  directive is active, an alive imposter runs `hunting` with
  `opportunistic: true, max_witnesses: 0, cover_mode: pretending`.
- **The target of the `pretending → hunting` reflex** (`reflex.nim`).
  When an alive imposter in `pretending` mode sees exactly one crewmate
  with kill ready, the reflex fires and switches to `hunting` with that
  crewmate as the preferred target.
- **Interruptible by the `hunting → fleeing` reflex.** If a body
  appears in view while hunting (edge-triggered), the mode switches to
  `fleeing` to put distance between the imposter and the corpse.

The mode is **only legal** for an alive, non-ghost imposter
(`isLegalFor` in `modes/hunting.nim:35-36` checks role, alive, and
ghost state; the broader validation system in `DESIGN.md` §8.4
additionally enforces phase-appropriateness — no hunting during voting).

---

## 2. Mode parameters

The LLM (or reflex/default system) sets these when issuing a `hunting`
directive:

```text
hunting {
  preferred_target: color_index | -1   # -1 = no specific target
  max_witnesses: int                   # refuse kill if > N non-target crewmates visible
  opportunistic: bool                  # if no preferred target, take any isolated crew
  cover_mode: "pretending" | "idle"    # pretending = task-station cover patrol;
                                       # idle = suppress cover movement
}
```

Implementation in `types.nim:254-258`:
```nim
of ModeHunting:
  huntPreferredTarget*: int     ## -1 = opportunistic.
  huntMaxWitnesses*: int
  huntOpportunistic*: bool
  huntCoverMode*: ModeName      ## ModePretending or ModeIdle.
```

**Default params** (from `modes/hunting.nim:38-44`):
- `huntPreferredTarget: -1` (no specific target)
- `huntMaxWitnesses: 0` (only kill with zero witnesses)
- `huntOpportunistic: true` (take any isolated crewmate)
- `huntCoverMode: ModePretending`

---

## 3. Decision logic overview

`decide()` evaluates a priority cascade each tick:

1. **Kill confirmation** — if a strike was recently sent, wait for
   confirmation signals (body + cooldown reset) before doing anything
   else.
2. **Preferred target pursuit** — if a preferred target is set, visible,
   kill is ready, and witness count is acceptable, close with
   `DisciplineKillStrike`.
3. **Opportunistic kill** — if `opportunistic` is true, kill is ready,
   and exactly one crewmate is visible (zero witnesses beyond the
   target), close with `DisciplineKillStrike`.
4. **Target memory** — if a target was recently visible (within
   `HuntMemoryTicks`), steer toward their last-known position with
   `DisciplineNormal`.
5. **Cover behavior** — if `cover_mode: pretending`, patrol between
   task stations and loiter briefly at each to encounter isolated
   crewmates. If `cover_mode: idle`, emit `noOpIntent()` instead of
   selecting a cover station.

Steps 2–3 also record the strike state when the bot enters kill range,
starting the confirmation timer.

The mode emits `noOpIntent()` when not localized (no camera lock), when
loitering at a cover station, or when `cover_mode: idle` reaches the
cover phase.

---

## 4. Target acquisition

### 4.0 Imposter-aware filtering

Before any target selection, the mode filters `visibleCrewmates` to
exclude known fellow imposters (`belief.self.knownImposterColors`).
This filtered list (`crewmatesOnly`) is used for both witness counting
and target selection. Known imposter colors are detected from the
role-reveal interstitial during the pre-game phase (see `bot.nim`
role-reveal scan), and can also be inferred after repeated failed
close-range strikes where the kill button remains ready and no body
appears.

Consequences:
- Fellow imposters are never targeted.
- Fellow imposters don't count as witnesses (seeing your partner
  near the target doesn't prevent a kill).
- `witnessCount` reflects only actual crewmates visible.

Known-imposter evidence is additive. The bot never removes colours from
`knownImposterColors` during a match.

### 4.1 Preferred target path

When `huntPreferredTarget >= 0` and `killReady` is true, the mode
scans the filtered crewmate list for a matching `colorIndex`. If
found:

- Witness check: `witnessCount - 1 <= huntMaxWitnesses` (subtracts the
  target from the visible crewmate count).
- Computes world position via `visibleCrewmateWorldX/Y`.
- Updates scratch: `huntTargetColor`, `huntLastSightingTick`,
  `huntLastSeenX/Y`.
- If distance ≤ `HuntKillStrikeRange` and no strike already in flight,
  records strike state (§6).
- Returns `DisciplineKillStrike` intent aimed at the target.

### 4.2 Opportunistic path

When `huntOpportunistic` is true, `killReady` is true, and
`witnessCount == 1` (exactly one visible crewmate = the target, zero
others):

- Takes the sole visible crewmate as the target.
- Same world-position computation, scratch update, strike-state
  recording, and `DisciplineKillStrike` return as the preferred path.

**Witness semantics:** `witnessCount == 1` means the only visible
crewmate IS the target, so `other witnesses = 0`. This matches
`huntMaxWitnesses: 0` in the default directive.

---

## 5. Target memory

When a target was being pursued but leaves the screen:

- If `belief.tick - huntLastSightingTick <= HuntMemoryTicks` (48 ticks,
  ~2s): the mode steers toward `huntLastSeenX/Y` using
  `DisciplineNormal` (not kill-strike — can't kill what you can't see).
- After the memory window expires: clears `huntTargetColor` and
  `huntStrikeTick`, falls through to cover patrol.

This gives the imposter ~2 seconds of pursuit after losing visual
contact — enough to follow a target around a corner or through a
doorway.

---

## 6. Kill flow

### 6.1 Strike initiation

When the bot is within `HuntKillStrikeRange` (20 px) of a target and
no strike is already in flight (`huntStrikeTick < 0`), it records:

- `huntStrikeTick = belief.tick`
- `huntStrikeTargetX/Y` = target's world position at strike time
- `huntPreStrikeBodyCount` = current `visibleBodies.len`
- `huntPreStrikeKillReady = true`

The actual A button press happens in the **action layer**: the
`DisciplineKillStrike` discipline steers toward the target and ORs
`ButtonA` when `dist <= KillStrikeRange` (action.nim:323-332). The
hunting mode doesn't press A directly — it emits the intent and lets
the action layer handle the button.

### 6.2 Confirmation

On subsequent ticks after a strike (while `huntStrikeTick >= 0`):

- If `belief.tick - huntStrikeTick <= HuntKillConfirmTicks`:
  - **Body check:** Is there a new body within `HuntKillConfirmRadius`
    (30 px) of the strike target's position? Uses
    `bodyNearTarget()` which checks if `visibleBodies.len >
    preStrikeCount` and any body's world position is within radius.
  - **Cooldown check:** Did `killReady` go from true to false?
    (`huntPreStrikeKillReady and not belief.percep.killReady`)
  - **Confirmed** when the cooldown resets: sets `huntKillConfirmed =
    true` (for trace), clears strike and target state, and enters the
    post-kill alibi phase. `bot.nim` consumes the confirmation to mark
    the target colour dead in memory so later seeking does not re-target
    the same victim if body detection lags or misses. A body near the
    strike point also sends the bot into post-kill behavior, even if the
    cooldown edge was missed.
  - **Waiting:** If not yet confirmed, returns `DisciplineKillStrike`
    aimed at the strike target position (stays close in case kill
    didn't land).
- If the strike commit window expires with `killReady` still lit and no
  body near the target: **failed kill**. The mode records the target
  colour in scratch; `bot.nim` increments that colour's failed-kill
  evidence counter and, after the configured threshold, adds it to
  `knownImposterColors`.

### 6.3 KillStrikeRange

Two related constants:

- **`KillStrikeRange = 20`** in `action.nim:38` — the action layer's
  threshold for pressing ButtonA during `DisciplineKillStrike`. This
  matches the server's `KillRange` (20 px in `sim.nim`).
- **`HuntKillStrikeRange* = 20`** in `tuning.nim:59` — used by the
  hunting mode to detect "we just entered kill range" and start the
  confirmation timer.

Both are 20 px. The separation exists because the action layer's
constant is local/non-exported (action-layer concern) while the hunting
mode needs to independently detect the range threshold for its
confirmation logic.

### 6.4 Why body and cooldown are paired

Using body-appearance and cooldown-reset avoids false positives:

- A crewmate walking off-screen would fool a naive "visible crewmate
  count decreased" check.
- A body appearing at the target's position is specific evidence.
- `killReady` going false corroborates (the server resets cooldown on
  successful kill, changing the HUD kill-button sprite).

---

## 7. Cover behavior

When no kill target is available and no memory pursuit is active, the
mode follows `params.huntCoverMode`:

- `ModePretending` (default): patrol between task stations.
- `ModeIdle`: clear any cover target and emit `noOpIntent()`.

### 7.1 Station selection (`pickCoverStation`)

Runs only when `huntCoverMode == ModePretending`.

Picks a station that is:
- Not the current station (`idx != currentIdx`).
- Far enough to be worth walking to (`distance > 30 px`).
- The nearest qualifying station (starting search from
  `(currentIdx + 1) mod tasks.len` for rotation).
- Fallback: if all stations are too close, picks the farthest one.

Uses precomputed `passableCX/passableCY` (the station's geometric
centre snapped to the nearest walkable pixel) as the navigation target,
ensuring navigation receives a reachable goal.

### 7.2 Navigation

Steers toward the cover station via `DisciplineNormal`
(waypoint-backed pathfinding through the action layer).

### 7.3 Arrival and loiter

Arrival is detected when the bot is within an 8-pixel margin of the
station's bounding box (`isAtStation`). On arrival:

- Sets `huntCoverLoiterUntilTick = belief.tick + HuntCoverLoiterTicks`
  (72 ticks, ~3s).
- Returns `noOpIntent()` (stands still).

### 7.4 Loiter expiry

When the loiter deadline passes:
- Clears `huntCoverTargetIndex` and `huntCoverLoiterUntilTick`.
- Next tick: picks a new station (§7.1) and navigates.

### 7.5 Interruptibility

The patrol is interruptible at any tick. If a kill opportunity arises
(preferred target visible, or opportunistic conditions met), the
priority cascade (§3) will take the kill path before reaching the
cover logic. The loiter timer continues running during pursuit — if
the pursuit fails and the bot returns to cover, it may immediately
pick a new station rather than loitering at the old one.

---

## 8. Scratch state

All fields are reset on mode entry (`onEnter`). Preserved across
directive changes within the same mode (per `DESIGN.md` §5.6).

```nim
of ModeHunting:
  huntTargetColor*: int              ## Color of pursuit target (-1 = none).
  huntLastSightingTick*: int         ## Tick target was last seen.
  huntEnterTick*: int                ## Tick mode was entered.
  huntLastSeenX*: int                ## World X of last sighting.
  huntLastSeenY*: int                ## World Y of last sighting.
  huntCoverTargetIndex*: int         ## Station index for cover patrol (-1 = none).
  huntCoverLoiterUntilTick*: int     ## Loiter deadline at cover station.
  huntStrikeTick*: int               ## Tick when kill-strike was initiated (-1 = none).
  huntStrikeTargetX*: int            ## World X of target at strike time.
  huntStrikeTargetY*: int            ## World Y of target at strike time.
  huntPreStrikeBodyCount*: int       ## Visible body count before strike.
  huntPreStrikeKillReady*: bool      ## killReady state before strike.
  huntKillConfirmed*: bool           ## Set true on kill confirmation (consumed by trace).
```

Initial values on `onEnter`:
- `huntTargetColor = params.huntPreferredTarget` (seeds from directive)
- `huntCoverTargetIndex = -1` (no station selected yet)
- `huntStrikeTick = -1` (no strike in flight)
- `huntKillConfirmed = false`
- All position/tick fields = 0

---

## 9. Tuning constants

All live in `tuning.nim:54-59`:

| Constant | Value | Meaning |
|---|---|---|
| `HuntCoverLoiterTicks` | 72 | Loiter at each cover station ~3s before moving on. |
| `HuntMemoryTicks` | 48 | Pursue last-known position for ~2s after losing visual. |
| `HuntKillConfirmTicks` | 12 | Window (~0.5s) to observe kill confirmation signals. |
| `HuntKillConfirmRadius` | 30 | World-pixel radius for matching a new body to the strike target position. |
| `HuntKillStrikeRange` | 20 | World-pixel distance for entering kill range (matches server `KillRange`). |

Action-layer constant (not in `tuning.nim`, local to `action.nim:38`):

| Constant | Value | Meaning |
|---|---|---|
| `KillStrikeRange` | 20 | Threshold for the action layer to press A during `DisciplineKillStrike`. |

---

## 10. Reflex interactions

### 10.1 Incoming reflexes (other modes → hunting)

| Source mode | Condition | Params issued | Reflex name |
|---|---|---|---|
| `pretending` | `killReady AND visibleCrewmates == 1` | `preferred_target: <color>, max_witnesses: 0, opportunistic: false, cover_mode: pretending` | `lone_crew_kill_opportunity` |

This reflex fires without LLM approval. It routes the kill opportunity
into `hunting.decide()`, which can still decline (e.g. target moved out
of range by the time decide runs). The reflex TTL is 120 ticks (~5s);
after that the directive expires and the default imposter directive
(also hunting, but opportunistic) takes over.

**Watchpoint:** If this reflex causes bad kills the LLM would have
vetoed (e.g. during `alibi_building`), consider gating it on an
LLM-set `permit_opportunistic_kill` field in `pretending.params`
or demoting it entirely.

### 10.2 Outgoing reflexes (hunting → other modes)

| Condition | Target mode | Params issued | Reflex name |
|---|---|---|---|
| `body_newly_in_view` (edge-triggered, body count increased) | `fleeing` | `away_from: <body_position>, min_distance: 48, duration_ticks: 240` | `body_newly_in_view_flee` |

The imposter flees from newly-seen bodies rather than lingering near
corpses. Does not check whether the imposter made the kill (a future
refinement could skip this for self-kills by checking timing against
a recent `kill_confirmed` event).

### 10.3 Cooldown

All reflexes are subject to `ReflexCooldownTicks` (96 ticks, ~4s)
per-reflex. The LLM can overrule a reflex-driven mode switch during
this window without the reflex re-firing.

---

## 11. Trace events

Emitted by `bot.nim:588-605` when the mode is `ModeHunting` and
tracing is enabled.

### 11.1 `kill_attempted`

Emitted on the tick `huntStrikeTick` is first set (bot enters kill
range and the confirmation timer begins).

```json
{ "t": <tick>, "kind": "kill_attempted",
  "target_color": <int>,
  "distance": <int>,
  "witnesses": <int> }
```

- `distance`: Manhattan distance from self to strike target at the
  moment of the attempt.
- `witnesses`: `visibleCrewmates.len - 1` (excludes the target).

### 11.2 `kill_confirmed`

Emitted when `huntKillConfirmed` is set true by the mode's
confirmation logic.

```json
{ "t": <tick>, "kind": "kill_confirmed",
  "target_color": <int>,
  "marked_dead": <bool> }
```

The flag is consumed (reset to false) immediately after the target is
marked dead in memory and the trace event is emitted.

---

## 12. Default directive (imposter)

When no LLM directive is active (startup, TTL expiry, LLM failure),
the imposter's default directive is:

```text
hunting {
  preferred_target: -1,
  max_witnesses: 0,
  opportunistic: true,
  cover_mode: "pretending"
}
```

This makes the imposter patrol task stations and take any clean kill
opportunity (zero witnesses) that presents itself. The LLM can
override with a more targeted or cautious hunting directive, or switch
to a different mode entirely.

---

## 13. Action layer contract

The hunting mode communicates with the action layer via two disciplines:

- **`DisciplineKillStrike`** — used when pursuing a visible target or
  waiting for kill confirmation. The action layer steers toward
  `steerTo` and ORs `ButtonA` when within `KillStrikeRange` (20 px).
  No waypoint routing — direct line steering.
- **`DisciplineNormal`** — used during target memory pursuit and cover
  patrol navigation. The action layer uses the waypoint graph and
  baked edge paths to reach `steerTo`.

The mode never sets `pressA` directly. Button presses are the action
layer's responsibility based on the discipline hint.

---

## 14. LLM snapshot context

Hunting exposes a compact mode summary in LLM snapshots:

- `current_mode.name/source/ticks_active`.
- `current_mode.params`, including preferred target, witness limit,
  opportunistic flag, and cover mode.
- `current_mode.summary`, including phase, reason, active/preferred
  target, last sighting, cover target/index/name/room, cover loiter
  remaining, strike state, and kill-confirmation state.
- Perception data (visible crewmates, bodies, kill cooldown).
- Memory (per-player summaries, body events).

The LLM uses this to distinguish "I am closing on a target", "I am
patrolling cover", "I am idling because cover_mode is idle", and "I am
waiting for kill confirmation" without reading raw mode scratch.

---

## 15. Open questions

1. **Self-kill fleeing.** `reflex.nim` now remembers known body world
   positions and suppresses repeated fleeing from the same corpse,
   including bodies observed during hunting strike/post-kill handling.
   First-time fleeing from an ambiguous corpse can still be acceptable
   cover behavior. If traces show post-kill time loss, tune hunting's
   post-kill plan before weakening the general body reflex.

2. **Kill confirmation trace richness.** The `kill_confirmed` trace
   event currently emits `target_color`, `strike_position`, and whether
   belief memory marked the target dead. Adding
   `ticks_since_strike` and `body_distance` would aid offline analysis.
   Low priority.
