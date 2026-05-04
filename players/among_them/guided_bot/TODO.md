# guided_bot TODO

Open bugs and tasks. Newest first.

---

## BUG: A\* empty-path noop lock (2026-05-04, HIGH) — FIXED

Bot had a `steer_to` target and `DisciplineNormal` but emitted `mask=0`
(noop) for the rest of the match. Position never changed. Observed on
2 of 4 seeds tested (50% frequency).

Example trace (seed 100, forced crewmate):
```
t=305-674: mode=task_completing, discipline=DisciplineNormal,
  steer_to=[768,103], self_x=712, self_y=105, mask=0, localized=true
```

### Root cause

`findPath` (`action.nim:60-175`) returns `@[]` when the goal cell is
impassable on the baked walk mask. The most likely trigger is
`action.nim:66`: the task station center (`taskStationWorldCenter`
computes `(ts.x + ts.w div 2, ts.y + ts.h div 2)`) falls on an
impassable walk-mask pixel.

When the path is empty, the waypoint-following block at
`action.nim:406-418` is skipped (`if state.currentPath.len > 0`),
leaving `mask` at 0.

The stuck detector (`action.nim:375-381`) never fires because it
requires `currentPath.len > 0` AND `lastEmittedMask != 0` — both
false. The progress-stall detector does fire every 48 ticks, but just
re-runs A\* with the same impassable endpoints.

### Fix (2026-05-04)

Three-layer fix:

1. **Precomputed passable task-station centres** (`data.nim`).
   `TaskStation` now carries `passableCX/passableCY`, computed at
   init time by snapping the geometric centre to the nearest walkable
   pixel via BFS on the walk mask. All three modes that steer toward
   task stations (`task_completing`, `pretending`, `hunting` cover
   patrol) now use these instead of computing the raw centre inline.
   This eliminates the trigger.

2. **Greedy-steering fallback** (`action.nim`). When `findPath`
   returns an empty path in the `DisciplineNormal` block,
   `steerButtons(self, goal)` is called as a last resort. This
   mirrors `modulabot/policies/base.py`'s fallback and prevents
   mask=0 regardless of the cause (impassable goal, unreachable
   goal, node-cap exceeded). Defense-in-depth for non-task steer
   targets (hunting last-seen, fleeing escape point) that could
   also land on impassable pixels.

3. **Stuck detector fix** (`action.nim`). Removed the
   `currentPath.len > 0` precondition. The stuck detector now fires
   whenever `lastEmittedMask` has direction bits but velocity is
   zero, covering both "path following but physically stuck" and
   "greedy fallback but hitting a wall." The greedy fallback ensures
   `lastEmittedMask` has direction bits even without a path, so the
   jiggle mechanism can break the bot free.

Also added `snapToPassable` as an exported proc in `action.nim` for
future callers.

### Reproduction

```sh
GUIDED_BOT_TRACE_DIR=/tmp/gb_stuck GUIDED_BOT_TRACE_LEVEL=decisions \
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 30 --seed 100 --force-role crewmate
```

Also reproduces with seed 7 (default role).

### Key code paths

- `findPath` empty returns: `action.nim:90-91, 96, 161, 200`
- `snapToPassable`: `action.nim:60-83`
- Precomputed passable centres: `data.nim:loadMap` (BFS snap loop)
- Greedy fallback: `action.nim` (after waypoint block)
- Stuck detector: `action.nim` (removed `currentPath.len > 0` guard)
- Modes updated: `task_completing.nim`, `pretending.nim`, `hunting.nim`

---

## BUG: Imposter role never detected (2026-05-04, HIGH)

`role_revealed` always reports `crewmate`, even with `--force-role
imposter`. The bot enters `task_completing` instead of
`hunting`/`pretending`. No imposter-specific behavior has ever been
observed in live play.

Observed in 5/5 live runs across 4 seeds, including 2 runs with
`--force-role imposter`.

### Root cause

`updateRole` (`perception/actors.nim:415-461`) has an aggressive
crewmate-default fallback at lines 456-460 that fires on the first
post-interstitial gameplay frame when `prevRole == RoleUnknown` and
neither the kill button nor ghost icon is found. **No debounce** —
a single frame is enough to latch `RoleCrewmate` permanently.

Two compounding failures:

**Failure A — Timing race.** The kill button HUD may not be rendered
on the first gameplay frame after the interstitial ends.

**Failure B — Kill button sprite mismatch.** `matchesSprite` (max 4
misses, `actors.nim:288-291`) and `matchesSpriteShadowed` (max 5
misses, `actors.nim:293-317`) both check a fixed position
`(KillIconX=109, KillIconY=110)`. If the baked `killButton` sprite
doesn't match what the server renders (position offset, palette
drift, shadow map error), every frame fails silently.

Once `RoleCrewmate` is latched, subsequent frames cannot flip it: the
else branch at line 458 only fires for `RoleUnknown`. The kill button
check at lines 451-455 would set `RoleImposter` if it matched — but
it never does.

Note: the ghost icon check has a debounce
(`GhostIconFrameThreshold=2`, line 64) but the crewmate default does
not.

### Reproduction

```sh
GUIDED_BOT_TRACE_DIR=/tmp/gb_imp GUIDED_BOT_TRACE_LEVEL=decisions \
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 30 --seed 100 --force-role imposter
```

Check `events.jsonl` — will show `role_revealed: crewmate`.

### Outstanding questions

- Is this a timing issue (Failure A) or a sprite mismatch (Failure B)?
  Need to capture the actual pixels at `(109, 110)` on the first few
  gameplay frames of an imposter match and compare against the baked
  sprite.
- Does modulabot correctly detect imposter on the same seed? If yes,
  the server flag works and the bug is guided_bot-specific.

### Key code paths

- `updateRole`: `perception/actors.nim:415-461`
- Kill button constants: `actors.nim:65, 74-75`
- `matchesSprite`: `actors.nim:284-291`
- `matchesSpriteShadowed`: `actors.nim:293-317`
- Crewmate default: `actors.nim:456-460`
- Ghost debounce: `actors.nim:431-442` (has threshold), crewmate (no threshold)
- Role latch in belief: `belief.nim:161-162`
- Default directive from role: `mode_registry.nim:96-116`

---

## BUG: Trace manifest never finalized (2026-05-04, LOW)

All trace `manifest.json` files show `"closed": false`. The
`end_tick`, `outcome`, and `role` fields are absent.

### Root cause

`closeTrace` (`trace.nim:255-285`) is called only from `destroyBot`
(`bot.nim:618-627`). `destroyBot` is never called because:

1. `ffi/lib.nim` has no `guidedbot_destroy_policy` export.
2. `AmongThemPolicy` has no `close()` method (the base class no-op
   runs instead).
3. The Nim global `GuidedBotPolicies` (`ffi/lib.nim:85`) holds
   references, and `destroyBot` is not registered as a GC finalizer.
