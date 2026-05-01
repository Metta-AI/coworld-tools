# Phase 2 Handoff Report

> Written 2026-05-01 after completing phase 1 (perception pipeline).
> Audience: the coding agent picking up phase 2 (per-mode strategy +
> action layer). Everything in this file is context that isn't captured
> in the existing docs (DESIGN.md, README.md, MISSION.md) or is
> scattered across files and easy to miss.

---

## What exists now

The guided_bot has a complete perception pipeline (phases 0–1.6) that
runs every frame and populates the `Belief` state. Every decision
still returns no-op (action layer is a stub). The bot compiles as both
a CLI binary and a shared library for cogames FFI.

### Files you'll touch most in phase 2

```
bot.nim              — pipeline orchestration; you'll add the action step
action.nim           — stub; this is where A*, momentum, jiggle, task-hold go
mode_registry.nim    — mode lookup + default directive; add real mode handlers
modes/
  task_completing.nim  — crewmate/ghost default; first mode to implement
  pretending.nim       — imposter cover mode
  hunting.nim          — imposter kill mode
  idle.nim             — current fallback (returns DisciplineNoOp)
belief.nim           — mergePercept / mergeActorPercept / etc.
types.nim            — ActionIntent, ModeScratch, Belief sub-records
```

### Files you'll read but probably not change

```
perception.nim                — orchestrator, re-exports all sub-modules
perception/data.nim           — referenceData (map, sprites, font)
perception/geometry.nim       — coord math, room lookups, A* heuristic
perception/localize.nim       — camera localization (read for selfX/selfY)
perception/actors.nim         — actor scan results
perception/tasks.nim          — task-icon + radar-dot results
perception/ocr.nim            — text matching (voting needs it)
perception/voting.nim         — voting-screen parser
constants.nim                 — button masks, screen dims
```

---

## The pipeline ordering (bot.nim:decideNextMask)

```
1.  perceive(frame)           → interstitial + ignore mask
2.  updateBelief(percept)     → merge interstitial into belief, set phase
2a. localize                  → camera X/Y, selfX/selfY (gameplay only)
2b. actor scan                → crewmates/bodies/ghosts, role, self-colour
    stamp actor exclusions    → ignore mask refined
2c. merge actors into belief
2d. task/radar scan           → task icons, radar dots
    stamp task-icon exclusions
2e. merge tasks into belief
2f. interstitial classification (OCR) + voting parse (interstitial only)
    merge voting into belief
3.  reconcileDirective        → ghost override, legality check
4.  decide                    → mode registry → ActionIntent
5.  applyIntent               → button mask (currently always 0)
```

**Phase 2 work lives in steps 4 and 5.** Step 3 already works (ghost
override forces `task_completing`, illegality falls back to default).
You need to make `decide` return real `ActionIntent` values and make
`applyIntent` turn them into button masks.

---

## What the belief state looks like on real frames

From the fixture test results:

| Frame | Camera | Localized | Crewmates | Bodies | Ghosts | Role | Self-colour | Task icons | Radar dots |
|---|---|---|---|---|---|---|---|---|---|
| gameplay_131 | — | no (cold start) | ? | 0 | 0 | Crewmate | — | 0 | 0 |
| gameplay_150 | (504,54) | yes | 2 | 0 | 0 | Crewmate | not detected | 0 | 0 |
| gameplay_200 | (504,54) | yes | 2 | 0 | 0 | Crewmate | not detected | 0 | 0 |
| gameplay_274 | (504,54) | yes | 2 | 0 | 0 | Crewmate | not detected | 0 | 0 |

**Self-colour is not detected on these fixtures.** The scalar
`matchesCrewmate` at the player anchor doesn't fire. This is a known
gap — the player may be in a walking frame that doesn't match the
standing sprite tightly enough. For phase 2, assume `colorIndex = -1`
is possible and handle it gracefully (the voting parser's self-marker
detection also depends on `colorIndex`).

**Task icons are 0 on all fixtures.** These frames are from early
gameplay near spawn — the player isn't near their assigned tasks. In a
real game, task icons appear when the player is near a task station
they're assigned to.

**Radar dots are 0 on these fixtures.** In a real game, yellow dots
appear on the screen edge pointing toward assigned tasks that are
off-screen.

---

## Key types for phase 2

### ActionIntent (types.nim)

```nim
ActionIntent = object
  steerTo: Point       # World coordinates of the destination
  steerValid: bool     # False = no destination (hold position)
  pressA: bool         # Task interact / report / vote confirm
  pressB: bool         # Cancel / back
  cursor: CursorDir    # CursorLeft / CursorRight / CursorNone
  chat: string         # Non-empty = send chat (meetings only)
  discipline: ActionDiscipline
    # DisciplineNoOp      — do nothing
    # DisciplineNormal    — A* steering toward steerTo
    # DisciplineTaskHold  — hold A only, no movement
    # DisciplineKillStrike — direct line, press A on contact
    # DisciplineReport    — direct line, press A in report range
```

**Modes produce ActionIntent. The action layer translates it to button
masks.** Modes never touch button bits directly (DESIGN.md §6).

### ActionState (types.nim)

```nim
ActionState = object
  currentPath: seq[Point]  # A* path (world coords)
  currentGoal: Point
  currentGoalValid: bool
  lastEmittedMask: uint8
  lastVelocityX, lastVelocityY: int
  stuckFrames: int
  jiggleTicks: int
  taskHoldTicks: int
```

This is the persistent state the action layer owns. All fields are
declared but none are populated yet.

### ModeScratch (types.nim)

Each mode has its own scratch slot, keyed by `ModeName`. Reset on mode
switch, preserved across directive changes within the same mode.
Currently all scratch fields are declared but unused.

---

## What A* needs

`perception/geometry.nim` already has:
- `heuristic(ax, ay, bx, by)` — Manhattan distance
- `roomNameAt(map, x, y)` — linear scan over rooms
- `visibleCrewmateWorldX/Y(cameraX, screenX)` — screen→world for actors

`perception/data.nim` has:
- `referenceData.map.walkMask` — `seq[uint8]`, `1` = walkable, `0` = blocked,
  `MapWidth * MapHeight` entries, row-major
- `referenceData.map.tasks` — `seq[TaskStation]` with world-space rects

The walk mask is the A* passability grid. It's 952×534 at full resolution.
modulabot's A* (`modulabot/path.py`) runs on this directly. For ghosts,
the walk mask is ignored (ghosts can pass through walls — DESIGN.md §5.7).

**modulabot's path.py** is a good reference for the A* implementation:
- Standard A* with 4-directional movement
- Short paths 1–2 ms, typical task paths 10–30 ms, cross-map ~90 ms
- Path is recomputed only when the goal changes or the current path is
  invalidated (stuck detection)

---

## Movement and the button mask

The BitWorld game expects directional inputs via the button mask:

```nim
ButtonUp     = 0b0000_0001  # Move up
ButtonDown   = 0b0000_0010  # Move down
ButtonLeft   = 0b0000_0100  # Move left
ButtonRight  = 0b0000_1000  # Move right
ButtonSelect = 0b0001_0000  # (unused in Among Them)
ButtonA      = 0b0010_0000  # Interact / report / vote
ButtonB      = 0b0100_0000  # Cancel
```

Movement works by setting direction bits. The game moves the player
one tile per tick in the pressed direction. Diagonal movement is
possible (set two direction bits). Momentum/jiggle handling is the
action layer's job — the game doesn't do smoothing.

**Task completion**: the player holds A while standing on the task
station. The game server handles the hold timer; the bot just needs to
keep pressing A. modulabot uses a `task_hold` discipline where no
movement is emitted, only A.

**Kill**: imposter presses A when adjacent to a target crewmate. The
kill-button HUD icon being "lit" (`percep.killReady`) means the
cooldown is done and a kill is possible.

**Report**: crewmate presses A when adjacent to a dead body. This
triggers a meeting.

---

## Stuck detection and jiggle

modulabot's approach (from `how_to_make_a_bot.md`):
- Track `lastVelocityX/Y` = difference between consecutive `selfX/Y`
- If velocity is 0 for N consecutive frames while movement is intended,
  the bot is stuck
- Jiggle: emit a perpendicular direction for a few ticks, then retry
  the original path
- Recompute A* path after jiggle if still stuck

This lives in the action layer, not in modes.

---

## Default directives (DESIGN.md §9.1)

These are what the bot uses when no LLM directive is present:

- **Crewmate, alive** → `task_completing { target: nearest_mandatory, abandon_on_nearby_body: true }`
- **Imposter, alive** → `hunting { preferred_target: none, max_witnesses: 1, opportunistic: true, cover_mode: "pretending" }`
- **Ghost** → `task_completing { target: nearest_mandatory, abandon_on_nearby_body: false }`
- **Voting phase** → `meeting { want_to_speak_first: false }`

`mode_registry.nim:defaultDirectiveFor` already returns these.

---

## What `task_completing` needs to do (first mode to implement)

1. **Pick a target task.** From `belief.percep.visibleTaskIcons` (phase
   1.4 raw output) + `belief.percep.radarDots`, figure out which tasks
   are assigned to us. The raw scan output is just `(x, y)` screen
   anchors — you need to map them back to task stations via the camera
   offset and the task-coord list in `referenceData.map.tasks`. See
   modulabot's `_populate_tasks_from_camera` in `pixel_pipeline.py`
   for the mapping logic (reported in the phase 1.4 research task).

2. **Navigate to the target.** Emit `ActionIntent(steerTo: taskWorldPos,
   steerValid: true, discipline: DisciplineNormal)`. The action layer
   turns this into A* path following + button mask.

3. **Hold A to complete.** When `selfX/Y` is inside the task rect and
   the task icon is visible, switch to `ActionIntent(discipline:
   DisciplineTaskHold, pressA: true)`.

4. **Abandon on body.** If `abandon_on_nearby_body` is true and
   `belief.percep.visibleBodies.len > 0`, a reflex should fire
   switching to `reporting` mode. (Reflexes are evaluated in
   `updateBelief` — phase 2 wires them in.)

---

## What the voting/meeting mode needs to do

`belief.self.phase == PhaseVoting` when a voting screen is detected.
The `VotingParse` (from `perception/voting.nim`) provides:

- `cursor` — current cursor position (slot index)
- `selfSlot` — our slot
- `slots[i].colorIndex`, `slots[i].alive`
- `choices[i]` — who each player voted for (from vote dots)
- `chatLines` — OCR'd chat with speaker attribution

The meeting mode needs to:
1. Move the cursor to a target (emit `CursorLeft` / `CursorRight`)
2. Press A to vote
3. (Phase 3) Emit chat via the LLM

For phase 2's fallback-only mode, the simplest meeting behavior is:
- Move cursor to SKIP (= `playerCount`)
- Press A to confirm
- This satisfies the "always cast a vote" requirement in DESIGN.md §9.2

---

## Build and test commands

```sh
# All tests (run from repo root):
for test in smoke perception_test data_test localize_test actors_test tasks_test ocr_voting_test; do
  nim c -r -d:release --threads:on --mm:orc \
    --path:among_them/guided_bot \
    "among_them/guided_bot/test/${test}.nim"
done

# Library build:
nim c -d:release --opt:speed --app:lib -d:guidedBotLibrary \
  --threads:on --mm:orc \
  -o:among_them/guided_bot/libguidedbot.dylib \
  among_them/guided_bot/guided_bot.nim

# CLI binary:
nim c -d:release --threads:on --mm:orc \
  -o:among_them/guided_bot/guided_bot \
  among_them/guided_bot/guided_bot.nim
```

Note: `--path:among_them/guided_bot` is needed for test compilation
because tests import `../bot` etc. relative to their directory.

---

## Gotchas discovered during phase 1

1. **Forward declaration ordering in Nim.** Procs must be defined before
   use. I hit this with `isPlayerBodyColor` in `actors.nim` — it was
   defined after `matchesCrewmate` which called it. Move helpers above
   their callers.

2. **Symbol collisions from re-exports.** `RadarTaskColor` was defined
   in both `ignore.nim` and `tasks.nim`, causing ambiguous-identifier
   errors when both were re-exported via `perception.nim`. Fix: define
   in one place, import in the other.

3. **`from "../../path" as alias import nil` pattern.** This is the
   canonical way to import shared kernels without namespace pollution.
   Use `alias.symbol` for qualified access. The kernels define their
   own `ScreenWidth` etc. that would collide with ours otherwise.

4. **Unused import warnings.** Nim warns on unused imports. Several
   modules import `frame` but don't use it directly (they use it via
   `data` or `ignore`). These are cosmetic — the warnings don't affect
   correctness. Clean them up if you touch the files.

5. **`openArray[uint8]` can't be captured in closures.** The localize
   spiral uses a `template` instead of a closure for the per-cell
   scoring step because Nim refuses to capture `openArray` parameters
   in closures. Use templates when you need to inline code that
   touches `openArray` arguments.

6. **Interstitial banner search order matters.** `findText("IMPS")`
   matches inside `"IMPS WIN"`. The banner array is sorted longest-first
   to avoid this. If you add new banners, maintain that ordering.

7. **The `percept` in `decideNextMask` is `var`.** It starts as the
   output of `perceive()` (interstitial + ignore mask) and is mutated
   in-place as actor scan, task scan, and voting parse results are
   added. This avoids copying the ignore mask (16 KB).

8. **`classifyInterstitial` costs ~12 ms** because `findText` sweeps
   the full 128×128 frame for each banner string. This only runs on
   interstitial frames (not every frame), so it's acceptable. If it
   becomes a bottleneck, restrict the Y search range to the known
   banner region (roughly rows 40–80 on the 128-pixel screen).

9. **Self-colour detection is unreliable.** `updateSelfColor` uses a
   scalar `matchesCrewmate` check at the player's known screen anchor.
   It often fails on walking frames. `belief.self.colorIndex` may stay
   at `-1` for many frames. The voting parser's self-marker detection
   depends on `colorIndex`, so it may miss our slot on frames where
   colour isn't detected. Consider carrying the last known colour
   forward in a future fix.

10. **The voting parser is strict.** It requires each slot's detected
    colour to exactly match the slot index. This means it rejects
    frames where sprite occlusion or animation prevents a clean colour
    read. This is intentional (matching modulabot's validator) but means
    `VotingParse.valid` will be false on some voting frames. The
    pipeline falls back to banner OCR classification in that case.

---

## Shared kernel dependency map

```
among_them/common/perception_kernels/
  sprite_match.nim  ← localize.nim (1.2), actors.nim (1.3)
  localize.nim      ← localize.nim (1.2)
  actors.nim        ← tasks.nim (1.4)
  ocr.nim           ← ocr.nim (1.5)
```

All four kernel files are consumed. If a kernel signature changes,
guided_bot's compile will fail immediately (qualified imports +
static asserts).

---

## Recommended phase 2 implementation order

1. **`action.nim` — A\* pathfinding + button mask.** Get the bot
   physically moving. Implement `applyIntent` to handle
   `DisciplineNormal` (A\* + direction buttons) and
   `DisciplineTaskHold` (just press A). Add stuck detection and jiggle.

2. **`modes/task_completing.nim` — crewmate default.** Pick a task,
   navigate to it, hold A. This is enough to pass the cogames
   validation gate (non-no-op actions within 10 ticks).

3. **`modes/meeting.nim` — vote skip fallback.** Move cursor to SKIP,
   press A. Satisfies the "always cast a vote" requirement.

4. **Reflex wiring.** Wire the four starter reflexes from DESIGN.md
   §5.8 into `updateBelief`. body_newly_in_view → reporting,
   voting_screen_appeared → meeting, etc.

5. **`modes/hunting.nim` + `modes/pretending.nim` — imposter.** Once
   crewmate works, add the imposter behavior. The default directive
   already selects `hunting`.

6. **Fallback-only playability test (DESIGN.md §9.2).** Run a full
   match with LLM disabled. Must play every phase, cast votes, complete
   at least one task.

---

## Files to read first

In order:
1. This file
2. `DESIGN.md` §4 (inner loop), §5 (modes), §6 (action intent), §9 (fallback)
3. `types.nim` — ActionIntent, ActionState, ModeScratch
4. `bot.nim` — the pipeline you're extending
5. `mode_registry.nim` — how modes are dispatched
6. `action.nim` — the stub you're filling in
7. `modes/idle.nim` — the simplest mode handler (template for new modes)
8. `perception/geometry.nim` — coord helpers you'll use for A*
9. `modulabot/path.py` (outside this repo, at `among_them/modulabot/path.py`) — A* reference implementation
