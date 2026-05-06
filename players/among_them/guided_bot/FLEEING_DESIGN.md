# Fleeing Mode — Design Document

> **Canonical reference** for the `fleeing` mode handler. All fleeing-
> mode design details live here; `DESIGN.md` contains only a brief
> overview and cross-reference.
>
> **Implementation:** `modes/fleeing.nim` (144 LOC)
>
> Last updated: 2026-05-05

---

## 1. Purpose and role

The `fleeing` mode is the imposter's body-avoidance behavior. It is:

- **The target of the `hunting → fleeing` reflex**
  (`reflex.nim:119-145`). When a body appears in view while hunting
  (edge-triggered: body count increased), the reflex fires and
  switches to `fleeing` to put distance between the imposter and the
  corpse.
- **Time-limited and self-terminating.** The mode runs for
  `fleeDurationTicks` (default 240, ~10s) or until `fleeMinDistance`
  (default 48 px) is reached, then transitions to cover navigation.
- **Not a default directive.** No role uses `fleeing` as its default.
  The mode is only entered via the body-seen reflex or a future LLM
  directive.

The mode is **only legal** for an alive, non-ghost imposter
(`isLegalFor` in `modes/fleeing.nim:20-21` checks role, alive, and
ghost state).

---

## 2. Mode parameters

The reflex (or LLM) sets these when issuing a `fleeing` directive:

```
fleeing {
  fleeAwayFrom: Point       # World-space position to flee from (the body).
  fleeMinDistance: int       # Minimum distance before flee is satisfied.
  fleeDurationTicks: int     # Maximum flee duration (timer-based exit).
}
```

Implementation in `types.nim:259-262`:
```nim
of ModeFleeing:
  fleeAwayFrom*: Point
  fleeMinDistance*: int
  fleeDurationTicks*: int
```

**Default params** (from `modes/fleeing.nim:23-28`):
- `fleeAwayFrom: Point(x: 0, y: 0)` — meaningless sentinel.
- `fleeMinDistance: 48` (world pixels).
- `fleeDurationTicks: 240` (~10s).

**Reflex-provided params** (from `reflex.nim:131-136`):
- `fleeAwayFrom`: body world position (screen coords + camera offset).
- `fleeMinDistance: 48`.
- `fleeDurationTicks: 240`.
- Directive TTL: 240 (matches duration — expires when flee completes).

---

## 3. Decision logic overview

`decide()` evaluates each tick:

1. **Not localized** — emit `noOpIntent()`.
2. **Flee complete** — if timer expired OR distance sufficient,
   transition to post-flee cover behavior.
3. **Active fleeing** — compute a flee target (away from body), snap
   to passable terrain, steer via `DisciplineNormal`.

```
     ┌──────────────┐     timer expired or distance met     ┌───────────────┐
     │ Active flee  ├─────────────────────────────────────► │ Cover transit │
     └──────────────┘                                       └───────────────┘
```

Both phases use `DisciplineNormal` (A\*-backed pathfinding). The mode
never stands idle except when not localized.

---

## 4. Active flee phase

### 4.1 Flee target computation

The mode computes a point away from the body:

```
fleeX = selfX + (selfX - bodyX) * 2
fleeY = selfY + (selfY - bodyY) * 2
```

This projects the bot's current position through itself, doubling the
vector from body to self. The result is a point roughly 2x the
current distance from the body, on the opposite side from the bot.

**Coincident fallback:** if `dx == 0 and dy == 0` (bot is directly on
the body), picks an arbitrary direction: `selfX + 60, selfY`.

### 4.2 Map clamping

The flee target is clamped to valid map coordinates:
- `fleeX` clamped to `[0, MapWidth - 2]`.
- `fleeY` clamped to `[0, MapHeight - 2]`.

### 4.3 Passability snap

After clamping, the target is snapped to the nearest walkable pixel
using `snapToPassable(walkMask, fleeX, fleeY)` from
`perception/geometry.nim`. This ensures A\* receives a valid goal.

If `snapToPassable` returns `found = false` (no walkable pixel within
its search radius — unlikely on skeld2), the raw clamped coordinates
are used. The action layer's greedy-steering fallback handles
impassable goals with wall-collision jiggle.

### 4.4 Flee completion conditions

The flee is satisfied when EITHER:
- `belief.tick >= scratch.fleeUntilTick` (timer expired).
- `dist >= params.fleeMinDistance` (distance from body ≥ 48 px).

Both are checked every tick. The first satisfied condition triggers
the transition to cover behavior.

---

## 5. Post-flee cover behavior

Once the flee condition is satisfied, the mode doesn't stop or stand
idle. Instead it navigates to a nearby task station to look like a
crewmate walking between tasks.

### 5.1 Station selection (`pickCoverStation`)

`pickCoverStation` (`modes/fleeing.nim:41-82`) selects a station that:

1. **Is far from the body:** station's passable centre must be ≥ 24 px
   from `fleeAwayFrom` (don't walk back toward the corpse).
2. **Is in the "away" hemisphere:** the dot product
   `(station - self) · (self - body) >= 0` must be non-negative. This
   ensures the station is in the general direction away from the body.
3. **Is the nearest qualifying station** (minimum Manhattan distance
   from the bot).

**Fallback:** if no station satisfies both constraints (all stations
are near the body or in the wrong hemisphere), picks the globally
nearest station to self regardless of direction.

### 5.2 One-shot selection

The cover station is picked exactly once (`fleeCoverSet` flag). After
selection, `fleeCoverTargetX/Y` are stored and the bot navigates
there for the remainder of the directive's TTL.

### 5.3 Cover navigation

Steers toward the selected station via `DisciplineNormal` (A\*-backed
pathfinding). The bot continues walking until:
- The directive TTL expires (240 ticks from reflex issuance), OR
- The LLM issues a new directive, OR
- A higher-priority reflex fires (e.g. `voting_screen_appeared`).

At that point `reconcileDirective` switches to the default imposter
directive (`hunting` with `opportunistic: true`).

---

## 6. Scratch state

All fields are reset on mode entry (`onEnter`). Preserved across
directive changes within the same mode (per `DESIGN.md` §5.6).

```nim
of ModeFleeing:
  fleeUntilTick*: int         # Flee deadline (entry tick + fleeDurationTicks).
  fleeCoverTargetX*: int      # Post-flee cover station world X.
  fleeCoverTargetY*: int      # Post-flee cover station world Y.
  fleeCoverSet*: bool         # Whether cover target has been picked.
```

Initial values on `onEnter`:
- `fleeUntilTick = belief.tick + params.fleeDurationTicks`
- `fleeCoverTargetX = 0`
- `fleeCoverTargetY = 0`
- `fleeCoverSet = false`

---

## 7. Tuning constants

The fleeing mode has no dedicated tuning constants in `tuning.nim`.
All behavior parameters come from the mode params (set by the reflex):

| Parameter | Default value | Set by | Meaning |
|---|---|---|---|
| `fleeDurationTicks` | 240 | Reflex | Max flee duration (~10s). |
| `fleeMinDistance` | 48 | Reflex | Distance threshold (world px). |

Local constants in `modes/fleeing.nim`:
- Cover station minimum distance from body: 24 px (in `pickCoverStation`).
- Coincident-position arbitrary offset: 60 px (flee target fallback).

---

## 8. Reflex interactions

### 8.1 Incoming reflexes (other modes → fleeing)

| Source mode | Condition | Params issued | Reflex name |
|---|---|---|---|
| `hunting` | `body_newly_in_view` (body count increased) AND imposter, alive | `fleeAwayFrom: <body_world_pos>, fleeMinDistance: 48, fleeDurationTicks: 240`, TTL 240 | `body_newly_in_view_flee` |

This reflex fires without LLM approval (`reflex.nim:119-145`). The
body's world position is computed from `visibleBodies[0]` screen
coords + camera offset.

**Note:** the reflex fires on ANY new body, including one the imposter
just created. Fleeing after a self-kill is actually reasonable behavior
(don't linger at the scene). See §10 open question 1.

The reflex only fires from `hunting` — if the imposter is in
`pretending`, `alibi_building`, or another mode, body appearances
don't trigger fleeing.

### 8.2 Outgoing reflexes (fleeing → other modes)

None. The mode is exited by:
- Directive TTL expiry (240 ticks) → `checkDirectiveTtl` →
  `defaultDirectiveFor` → `hunting`.
- LLM issuing a new directive.
- `voting_screen_appeared` reflex (highest priority, fires from any
  mode).

### 8.3 Cooldown

The body-flee reflex is subject to `ReflexCooldownTicks` (96 ticks,
~4s). If the imposter returns to `hunting` and immediately sees
another body, the reflex won't re-fire until the cooldown expires.

---

## 9. Trace events

No mode-specific trace events are emitted. The standard trace captures:

- Mode entry/exit via `modes.jsonl` (includes duration).
- `decisions.jsonl` records the steer target and discipline each tick,
  showing the flee trajectory and the transition from active fleeing
  to cover navigation.

The `body_seen` event in `bot.nim:451-458` fires on the same frame
that triggers the reflex, providing the body position in the trace.

---

## 10. Action layer contract

The mode communicates with the action layer via a single discipline:

- **`DisciplineNormal`** — used for both active fleeing and post-flee
  cover navigation. The action layer uses A\* pathfinding on the walk
  mask to reach `steerTo`.

The mode never sets `pressA` or `pressB`. No buttons are pressed
during fleeing — the bot only moves.

When not localized, the mode returns `noOpIntent()` and the action
layer emits no buttons.

---

## 11. LLM snapshot context

The fleeing mode's internal scratch state is **not** included in LLM
snapshots. The LLM sees:

- `current_mode: { "name": "fleeing", "source": "reflex", "ticks_active": <int> }`
- Perception data (visible bodies — relevant context for why the bot
  is fleeing).
- Memory (per-player summaries).

The LLM can override the fleeing mode with a new directive if it
decides the situation doesn't warrant fleeing (e.g. the body is one
the imposter deliberately positioned to frame someone). This override
happens via the normal guidance channel.

---

## 12. Open questions

1. **Self-kill fleeing.** The `hunting → fleeing` reflex fires on any
   new body, including ones the imposter just created. A refinement
   could suppress the reflex for ~12 ticks after a `kill_confirmed`
   event (check timing in hunting scratch). Low priority — fleeing
   after a kill is reasonable (don't linger at the scene).

2. **Flee target quality.** The projection `self + 2*(self - body)` is
   naive — it doesn't account for the map layout. If the bot is in a
   dead-end room, it may flee toward a wall and waste time with
   `snapToPassable` jitter before A\* finds a viable path. A smarter
   approach would flee toward the nearest room exit. Low priority —
   the snap + A\* combination handles most cases.

3. **Cover station arrival.** The mode doesn't detect arrival at the
   cover station. If the bot reaches the station before the directive
   TTL expires, it will continue emitting `DisciplineNormal` aimed at
   a point it's already at. The action layer handles this gracefully
   (no movement when at goal), but the bot visibly idles. A loiter
   phase (like pretending or hunting cover) could make this look more
   natural.
