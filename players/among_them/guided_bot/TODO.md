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

## BUG: Imposter role never detected (2026-05-04, HIGH) — FIXED

`role_revealed` always reports `crewmate`, even with `--force-role
imposter`. The bot enters `task_completing` instead of
`hunting`/`pretending`. No imposter-specific behavior has ever been
observed in live play.

### Root cause

Two compounding errors:

1. **Wrong kill-button HUD coordinates.** `KillIconX` / `KillIconY`
   were `(109, 110)` (bottom-right) but the server renders the kill
   button at `(1, 115)` (bottom-left). The server source confirms:
   `sim.nim:3395-3407` sets `iconX = 1`,
   `iconY = ScreenHeight - SpriteSize - 1 = 115`. Every other bot
   in the ecosystem uses `(1, 115)`.

2. **No OCR-based role inference.** The `classifyInterstitial` OCR
   correctly detected "IMPS" / "CREWMATE" text during the
   role-reveal interstitial, but this result was stored in
   `belief.percep.interstitialKind` and **never used to set the
   role**. The italkalot and nottoodumb reference bots both have a
   `rememberRoleReveal` function that reads the banner text during
   the interstitial and sets the role *before* the first gameplay
   frame — eliminating any dependence on the kill button being
   rendered on frame 1.

   Without this, even with correct coordinates, the kill button
   isn't always rendered on the very first gameplay frame (server
   rendering timing), causing the crewmate default to latch on
   some seeds.

### Fix (2026-05-04)

Two-layer fix:

1. **Correct HUD coordinates** (`perception/actors.nim:74-77`):
   ```nim
   KillIconX* = 1
   KillIconY* = ScreenHeight - SpriteSize - 1  ## = 115
   ```
   This also fixes ghost-icon detection (same HUD slot).

2. **OCR-based role inference during interstitials** (`bot.nim`
   and `types.nim` / `perception/ocr.nim`):
   - Split `InterstitialRoleReveal` into two enum variants:
     `InterstitialRoleRevealCrewmate` and
     `InterstitialRoleRevealImposter`.
   - During interstitial classification, when the banner text is
     identified, set `belief.self.role` immediately — mirroring
     italkalot/nottoodumb's `rememberRoleReveal` pattern.
   - The role is now known before the first gameplay frame arrives,
     so the crewmate fallback in `updateRole` never fires from
     `RoleUnknown`.

### Verification (2026-05-04)

Live-verified with tracing:
- **Seed 100** (imposter): `events.jsonl` shows
  `{"kind": "role_revealed", "role": "imposter"}` at tick 139.
  `modes.jsonl` shows `idle` → `hunting` (correct imposter
  behavior).
- **Seed 7** (crewmate per server): `events.jsonl` shows
  `{"kind": "role_revealed", "role": "crewmate"}` at tick 142.
  Visual frame capture of the role-reveal interstitial confirms
  "CREWMATE" text on screen.

Both detection paths confirmed working:
- Kill-button sprite match at `(1, 115)` detects imposter on
  gameplay frames.
- Interstitial OCR detects "IMPS" during the role-reveal and
  sets the role before gameplay begins.

### Note on `--force-role`

`--force-role imposter` is **not reliable** in the local test
harness. Despite the flag, some seeds result in the bot being
assigned crewmate. This is a race condition in the harness (filler
bots may claim slot 0 before the policy bot's first game tick is
processed), not a detection bug.

**Known working imposter seeds**: 50, 100.
**Known crewmate-despite-flag seeds**: 1, 7, 42, 99, 200.

To test imposter behavior, use a known-good seed:
```sh
GUIDED_BOT_TRACE_DIR=/tmp/gb_imp GUIDED_BOT_TRACE_LEVEL=decisions \
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 20 --seed 100 --force-role imposter
```

### Key code paths

- Kill button constants: `perception/actors.nim:74-77`
- `updateRole` (HUD check): `perception/actors.nim:415-461`
- OCR role inference: `bot.nim` (interstitial classification block)
- InterstitialKind enum: `types.nim:38-50`
- Banner table: `perception/ocr.nim:262-268`
- Server rendering: `bitworld/among_them/sim.nim:3395-3407`
- Reference bots: `italkalot.nim:1536-1558`,
  `nottoodumb.nim:1465-1485` (`rememberRoleReveal`)

---

## BUG: Trace manifest never finalized (2026-05-04, LOW) — FIXED

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
