# guided_bot TODO

Open bugs and tasks. Newest first.

---

## BUG: Localization drops on kill animation (2026-05-04, MEDIUM)

After the imposter's kill A-press lands (server accepts the kill),
the localizer loses lock on the very next frame (t+1). The bot
emits `noOpIntent()` for 15+ frames because `decide()` early-returns
on `not localized`. This prevents:

1. **Kill confirmation** — the `huntStrikeTick` confirmation block
   never runs, so `kill_confirmed` is never emitted even though the
   kill succeeded server-side.
2. **Post-kill fleeing** — the fleeing reflex can't fire without
   body detection, which requires localization.

### Root cause (hypothesis)

The kill animation renders the victim's death sprite + blood effect
at/near the player position. These extra pixels break the camera-fit
scoring in `localize.nim` (too many non-map pixels fail the
patch-hash comparison, pushing the error count above the localizer's
acceptance threshold).

The actor-exclusion ignore mask should in theory cover the kill
animation, but it may not account for:
- The death sprite being larger than a normal crewmate sprite
- Blood splatter pixels outside the sprite bounding box
- The momentary rendering of both the dying player + the imposter
  overlapping

### Possible fixes

- **Widen the ignore mask around self during the kill window.**
  After pressing A in DisciplineKillStrike, expand the player-centre
  ignore radius for ~12 frames to cover the death animation.
- **Carry localization through short drops.** If the localizer was
  locked on the previous frame and the camera didn't move (velocity
  = 0 during kill animation), assume the previous lock is still
  valid for up to N frames.
- **Accept the miss.** Kill confirmation is informational — the
  bot's behavior is correct regardless (it should flee/resume patrol
  anyway). A simpler fix is to unconditionally enter the
  post-kill-flee state after pressing A in range, without waiting
  for visual confirmation.

### Reproduction

```sh
GUIDED_BOT_TRACE_DIR=/tmp/gb_kill GUIDED_BOT_TRACE_LEVEL=decisions \
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 90 --seed 100 --force-role imposter \
    --policy-kwarg imposter_cooldown_ticks=48
```

Or use the live integration test:
```sh
PYTHONPATH=among_them .venv/bin/python \
    among_them/guided_bot/test/live_test.py --scenario imposter --keep-traces
```

Check `decisions.jsonl` around `kill_attempted` events: `localized`
will be `false` on the frame after A=true.

### Key code paths

- Early return on `not localized`: `modes/hunting.nim:140`
- Kill confirmation block: `modes/hunting.nim:148-173`
- Localizer scoring: `perception/localize.nim`
- Actor ignore mask: `bot.nim:304-316`

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

## BUG: Navigation quality — jitter, orbiting, missed tasks, random redirects (2026-05-04, HIGH)

Observed in live play: walking is jittery and prone to orbiting,
agents miss task interaction points, trajectory changes frequently
for no visible reason, and agents sometimes move to seemingly random
nearby points.

See `NAVIGATION_FIX.md` for full root cause analysis and fix plan.

### Sub-issues

- **1a. Jittery walking / orbiting / random stops-starts.**
  Root causes: PathLookahead=4 too small, ReplanIntervalTicks=24 too
  aggressive, StuckThreshold=8 too sensitive, no velocity smoothing.
- **1b. Missing task interaction points.** — FIXED
  Root cause: `isInsideTaskRect` used a margin that triggered the
  Hold phase while the bot was still outside the server's exact task
  rect. Fix: use the server's exact rect (no margin) and keep the
  final path waypoint so the bot navigates all the way in.
- **1c. Random movement to nearby points.**
  Root cause: TaskCommitTicks hysteresis is documented but never
  enforced in task_completing.nim.
- **1d. Frequent trajectory changes without reason.**
  Root cause: combination of 24-tick replans, missing commit lock,
  and reflex interrupts with 48-tick cooldown.

### Key code paths

- A* + path following + stuck/jiggle: `action.nim:30-465`
- Task target selection + commit: `task_completing.nim:81-201`
- Reflex cooldowns: `reflex.nim`, `tuning.nim:20`
- Tuning constants: `tuning.nim`, `action.nim:30-47`

---

## BUG: Ghost crewmates idle in cafeteria instead of completing tasks (2026-05-04, MEDIUM)

Ghost crewmates sit motionless in the cafeteria after death. They
should continue completing objectives (ghosts can go through walls).

### Root cause (hypothesis)

The code correctly assigns ghosts `ModeTaskCompleting` (both as
default in `mode_registry.nim:102` and as a hard override in
`bot.nim:231-232`). Ghost navigation uses straight-line paths
(`action.nim:381-382`). The ghost task mode is legal
(`task_completing.nim:33`).

The probable cause: localization is lost on death/respawn. During the
death interstitial, `localizer.reseedCameraAtHome` resets camera
position. After respawn as a ghost, the localizer may fail to
re-acquire because:
- Ghost sprites are semi-transparent / visually different
- The death-respawn teleports the camera to cafeteria, invalidating
  the previous lock
- The ghost's screen appearance may not match the reference map tiles

Without `belief.percep.localized == true`, `task_completing.decide()`
returns `noOpIntent()` on line 173 and the ghost never moves.

### Possible fixes

1. **Skip localization requirement for ghosts.** Since ghosts use
   straight-line paths (no walk mask), they only need the task station
   world coordinates (static data) and some notion of their current
   position. If ghosts always respawn at a known location (cafeteria
   centre), seed their position from that and update via velocity.
2. **Force re-localize on ghost transition.** Detect the
   `isGhost` transition and run an aggressive localization pass
   (lower error threshold, wider search window).
3. **Use DisciplineWander for ghosts until localized.** Instead of
   noOpIntent, wander randomly until the localizer locks.

### Key code paths

- Ghost override: `bot.nim:231-232`
- Ghost straight-line path: `action.nim:381-382`
- Task decide early-return: `task_completing.nim:173`
- Localizer reseed: `perception/localize.nim` (reseedCameraAtHome)
- Ghost detection: `belief.nim` (isGhost, alive fields)

---

## FEATURE: Meeting chat emission not implemented (2026-05-04, MEDIUM)

Agents don't chat during meetings. The LLM can generate
`MeetingActSpeak` with text, and the infrastructure queues it through
to the meeting mode, but actual emission to the game server is
explicitly stubbed.

### Current state

- `meeting.nim:185-193`: MeetingActSpeak sets `intent.chat` but notes
  "Chat emission is a stub (deferred). Put text on intent anyway so
  it's ready when the FFI pipeline is wired."
- `action.nim:471-476`: `emitChat` is a hard no-op (`discard; false`).
- FFI layer (`ffi/lib.nim`): only returns button-mask action indices.
  No mechanism to emit text to the server.
- The game server accepts chat via a separate WebSocket text message
  (not button presses). The current architecture only sends button
  masks through the FFI boundary.

### What's needed

1. **New FFI export** — e.g., `guidedbot_get_chat(handle, agentId)`
   that returns pending chat text (or empty string).
2. **Python wrapper** — after `step_batch`, poll each agent for
   pending chat and send it via `ws.send(json.dumps({"type":"chat",
   "text": ...}))`.
3. **Rate limiting** — `MeetingChatLineGapTicks = 12` is already
   defined in `tuning.nim` but unused.

### Without ANTHROPIC_API_KEY

When no API key is set, the guidance worker never starts. No meeting
actions are generated. The bot falls back to auto-vote-skip after
`MeetingAutoVoteDelayTicks = 360` (15 seconds). No chat occurs
regardless of whether emission is wired.

### Key code paths

- Chat stub: `meeting.nim:185-193`
- emitChat no-op: `action.nim:471-476`
- FFI boundary: `ffi/lib.nim:114-154`
- Python wrapper: `cogames/amongthem_policy.py:172-191`
- Rate limit constant: `tuning.nim:24`

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
