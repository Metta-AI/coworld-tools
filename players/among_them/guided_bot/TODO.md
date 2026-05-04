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

## BUG: Imposter role never detected (2026-05-04, HIGH) — TENTATIVELY FIXED

`role_revealed` always reports `crewmate`, even with `--force-role
imposter`. The bot enters `task_completing` instead of
`hunting`/`pretending`. No imposter-specific behavior has ever been
observed in live play.

Observed in 5/5 live runs across 4 seeds, including 2 runs with
`--force-role imposter`.

### Root cause

**Wrong kill-button HUD coordinates.** `KillIconX` / `KillIconY`
were set to `(109, 110)` (bottom-right) but the server renders
the kill button at `(1, 115)` (bottom-left). Every other bot in
the ecosystem (modulabot, nottoodumb, evidencebot_v2, italkalot,
ivotewell, cogames-agents baseline) uses `(1, 115)`. The server
source confirms: `sim.nim:3490-3497` sets `iconX = 1`,
`iconY = ScreenHeight - SpriteSize - 1 = 115`.

The guided_bot was matching its baked kill-button sprite against
arbitrary background pixels 108 px to the right of the actual icon.
It never found the kill button on ANY frame, so the crewmate
default at `actors.nim:458` fired on the first gameplay frame and
latched permanently.

The TODO previously hypothesized two causes:
- Failure A (timing race) — not the cause.
- Failure B (sprite mismatch) — not the cause.

The actual failure is simpler: **wrong position constant**.

### Fix (2026-05-04)

Changed `perception/actors.nim:74-75` from:
```nim
KillIconX* = 109
KillIconY* = 110
```
to:
```nim
KillIconX* = 1
KillIconY* = ScreenHeight - SpriteSize - 1  ## = 115
```

This also fixes ghost-icon detection, which uses the same
`KillIconX, KillIconY` HUD slot.

### Secondary issue (not yet fixed)

The `classifyInterstitial` OCR correctly detects "IMPS" during the
role-reveal interstitial, but this `InterstitialRoleReveal`
classification is **never consumed for role inference**. The only
role-setting path is the per-frame kill-button HUD check. Adding
an OCR-based role fallback would make the system more robust, but
is not required now that the coordinates are correct.

### Reproduction

```sh
GUIDED_BOT_TRACE_DIR=/tmp/gb_imp GUIDED_BOT_TRACE_LEVEL=decisions \
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 30 --seed 100 --force-role imposter
```

Check `events.jsonl` — should now show `role_revealed: imposter`.

### Key code paths

- Kill button constants: `perception/actors.nim:74-75`
- `updateRole`: `perception/actors.nim:415-461`
- `matchesSprite`: `perception/actors.nim:284-291`
- `matchesSpriteShadowed`: `perception/actors.nim:293-317`
- Server rendering: `bitworld/among_them/sim.nim:3490-3497`
- modulabot reference: `modulabot/frame.py:52-53`

---

## BUG: Trace manifest never finalized (2026-05-04, LOW) — TENTATIVELY FIXED

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

### Fix (2026-05-04)

Three-layer fix mirroring `modulabot/policy.py:267-284`:

1. **`ffi/lib.nim`**: Added `guidedbot_destroy_policy(handle)` export
   that iterates all bots in the policy and calls `destroyBot` on
   each, then nils the slot (idempotent on repeated calls).

2. **`cogames/amongthem_policy.py`**: Added `close()` method that
   calls the new FFI export, plus a `__del__` best-effort finalizer
   for scripts that exit without calling `close()` explicitly.

3. **Graceful degradation**: The Python side discovers the destroy
   export via `getattr(..., None)` so old libraries without the
   export don't crash — they just get the old behavior (unfinalised
   manifests).
