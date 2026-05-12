# guided_bot TODO

Organized by category, then by feature/mode. Priority in brackets.

---

## New Features

### Meeting LLM formatting [LOW]

Meeting chat and vote plumbing is implemented and live-validated with
Bedrock in full 8-agent runs. LLM-directed votes are now hard-guarded
only for legality, while symbolic evidence is exposed through
`meeting.evidence_ledger`. Without an available LLM provider, the
guidance worker does not start; the bot uses evidence/alibi fallback
strategy after `MeetingAutoVoteDelayTicks=360`.

**Current state:**
- `modes/meeting.nim`: consumes `speak`, `vote`, `confirm_vote`, `unvote`, `wait`
- `action.nim`: queues sanitized chat in `ActionState.pendingChat`
- `ffi/lib.nim`: exports `guidedbot_take_chat`
- `cogames/amongthem_policy.py`: exposes `bitworld_chat_messages(agent_ids)`
- `snapshot.nim`: meeting context includes a structured evidence ledger,
  memory evidence, vote dots, chat, selectable players, and alibi witnesses
- `llm.nim`: Bedrock provider is wired and smoke-tested; direct Anthropic
  remains a fallback

**Needed:**
1. Reduce raw Markdown code fences in otherwise valid LLM JSON responses.
   The parser tolerates fences, so this is operationally low risk.
2. Continue tuning chat wording as more evidence-rich, multi-meeting
   traces accumulate. The current prompt requires <=55 character
   living-player opening lines and the action layer caps outbound chat
   at 60 characters; next pass should improve variation and responses
   to real accusations.

**Key code:** `modes/meeting.nim`, `action.nim`, `ffi/lib.nim`,
`cogames/amongthem_policy.py`, `tuning.nim`

---

## Improvements

### Hunting mode design [MEDIUM] (2026-05-05)

Collected from HUNTING_DESIGN.md. Address behavior quality + human-likeness.

#### 1. Reduce `HuntKillStrikeRange` below `KillStrikeRange`

Both currently 20px — confirmation timer starts same tick as A-press. No window
where action layer pressed A but confirmation hasn't started.

**Fix:** Reduce `HuntKillStrikeRange` to ~18px. Action layer presses A at 20px,
hunting starts confirmation on next tick when distance closes further.

**Key code:** `tuning.nim` `HuntKillStrikeRange`,
`action.nim` `KillStrikeRange`, `modes/hunting.nim` `decide`

#### 2. Use kill cooldown as primary kill-detection signal

Current confirmation requires BOTH body-appearance AND cooldown-reset
(`modes/hunting.nim` `decide`). Body detection fragile: body spawns overlapping player
sprite, ignore mask may occlude, actor scanner struggles w/ kill-animation pixels.

Kill cooldown timer (`killReady→false`) is authoritative — server resets on
successful kill, renders shadowed kill button (easier to parse).

**Proposal:** `killReady→false` as PRIMARY signal; demote/drop body-appearance.

**Key code:** `modes/hunting.nim` `decide` / `bodyNearTarget`,
`perception/actors.nim`

#### 3. Cover patrol: random-not-in-current-room station selection

`pickCoverStation` picks nearest station beyond 30px —
keeps imposter in same area, reducing target diversity.

**Fix:** Select random station NOT in current room (or beyond larger distance
threshold). Ensures map coverage + encounters w/ isolated crewmates.

**Key code:** `modes/hunting.nim` `pickCoverStation`

#### 4. Station arrival: inside task rect, not 8px margin around it

`isAtStation` uses 8px margin around task bbox — bot
considers itself "arrived" while still outside actual task rect.

**Fix:** Require being inside task rect (no margin / negative margin).

**Key code:** `modes/hunting.nim` `isAtStation`

#### 5. Remove kill fleeing — switch to pretending immediately

`hunting→fleeing` reflex on body-newly-in-view is problematic (see self-body
flee loop bug). Skilled humans walk to nearby task + fake it for alibi.

**Fix:** Remove flee transition from hunting. After kill (or failed confirm
window), immediately switch to pretending mode. Also resolves self-body flee
loop for hunting case.

**Key code:** `reflex.nim` `body_newly_in_view_flee` branch,
`modes/hunting.nim` kill-confirmation branch in `decide`

## Bugs (Open)

### Post-kill pursuit — bot chases new targets after kill [HIGH]

After kill lands, bot continues `DisciplineKillStrike` 60+ ticks — first toward
corpse during failed confirm window, then toward new crewmate on fallthrough.
Should immediately disengage → cover/flee.

**Evidence (2 runs, seed 100):**
- Run 1, kill t=251: DisciplineKillStrike until t=310 (59 ticks post-kill).
  Steer shifts from corpse (587,103) to new crewmate (623→713,106) at t=264.
- Run 2, kill t=427: body-flee reflex fires t=429 (2 ticks later) — accidentally
  correct behavior via wrong mechanism.

**Root cause:** Kill confirmation (`modes/hunting.nim`) requires both
`gotBody` + `cooldownReset`. Both fail within 12-frame window:
1. Body spawns ≤20px from player, ignore mask may occlude, kill animation confuses scanner
2. `killReady` perception lag: 2-3 frames to detect shadowed→unlit transition
3. `HuntKillConfirmTicks=12` too short for simultaneous arrival of both signals

On window expiry, `huntStrikeTick` resets, falls through to
target-search, new crewmate satisfies opportunistic-kill → new pursuit begins.

**Compound interaction:** kill → failed confirm → re-pursuit → body enters view
→ flee 240t → return → re-trigger. Known-body de-dupe now suppresses repeated
same-body flee episodes; the remaining risk is unnecessary pursuit or delayed
post-kill alibi before the body is remembered.

**Fix plan:** After `huntStrikeTick` set, ALWAYS transition to flee/cover on
window expiry regardless of outcome:
1. Add `huntPostKillFlee: bool` to `ModeScratch`
2. Set flag on window expiry or confirm success
3. In `bot.nim`, check flag after `decide()` — force mode switch to fleeing
   (72 ticks, away from strike pos)
4. Known-body de-dupe is implemented in `reflex.nim`; if this bug reappears
   without a visible body, consider also recording strike positions as body
   hints.

Alt: Return special `DisciplinePostKillFlee` ActionIntent from `hunting.decide()`
for `bot.nim` to intercept.

**Key code:** `modes/hunting.nim`, `action.nim`, `tuning.nim`, `bot.nim`

---

### Localization drops on kill animation [MEDIUM]

After kill A-press lands, localizer loses lock on t+1. Bot emits `noOpIntent()`
15+ frames (early-returns on `not localized`). Prevents kill confirmation +
post-kill fleeing.

**Root cause (hypothesis):** Kill animation renders death sprite + blood at/near
player pos. Extra pixels break camera-fit scoring in `localize.nim` (too many
non-map pixels exceed acceptance threshold). Actor-exclusion ignore mask may not
account for oversized death sprite, blood splatter outside bbox, or
dying+imposter overlap.

**Possible fixes:**
- Widen ignore mask around self during kill window (~12 frames post A-press)
- Carry localization through short drops (if previous frame locked + velocity=0,
  assume valid for N frames)
- Accept the miss — unconditionally enter post-kill-flee after A-press in range
  without waiting for visual confirmation

**Reproduction:**
```sh
GUIDED_BOT_TRACE_DIR=/tmp/gb_kill GUIDED_BOT_TRACE_LEVEL=decisions \
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 90 --seed 100 --force-role imposter \
    --imposter-cooldown-ticks 48
```

**Key code:** `modes/hunting.nim`, `perception/localize.nim`, `bot.nim`

---

### Ghost crewmates idle in cafeteria instead of completing tasks [MEDIUM]

Ghosts sit motionless after death. Should continue objectives (ghosts traverse
walls). Code correctly assigns `ModeTaskCompleting` and uses straight-line paths.

**Root cause (hypothesis):** Localization lost on death/respawn.
`localizer.reseedCameraAtHome` resets camera pos; ghost may fail to re-acquire
(semi-transparent sprites, teleport invalidates lock, appearance mismatch).
Without localization, `task_completing.decide()` returns `noOpIntent()`.

**Possible fixes:**
1. Skip localization requirement for ghosts — seed pos from cafeteria centre,
   update via velocity (straight-line paths don't need walk mask)
2. Force re-localize on ghost transition (lower threshold, wider search)
3. Use `DisciplineWander` for ghosts until localized

**Key code:** `bot.nim`, `action.nim`, `modes/task_completing.nim`,
`perception/localize.nim` (reseedCameraAtHome), `belief.nim`

---

### Task trace count needs first-game cutoff [LOW]

In live tests, `task_completed` events can exceed the expected first-game task
count if the trace is counted across the whole `play_match.py --duration`
window. The server can show game-over, reset to lobby/new-game state, and keep
feeding the same policy instances inside the same traced run.

**Evidence (8-player, 2-impostor, seed 42, 180s):**
- Raw full-run `task_completed` trace count: 51.
- Count before each bot's first `game_over` event: 47.
- Four completions occurred after game-over and are not first-game productivity.

The 47/48 pre-game-over count is expected for a crew task win: the final
server-side task can complete and immediately move the game to game-over before
the bot observes enough post-hold gameplay frames to log its local
`task_completed` confirmation.

**Rule:** productivity summaries must stop at the first `game_over` symbol/event
per bot, and `task_completed` should be treated as bot-local evidence rather
than the authoritative server task counter.

**Key code:** `modes/task_completing.nim` (task start/complete detection),
`perception/tasks.nim`, `trace.nim` (event emission)

---

### Meeting LLM vote quality [LOW]

The no-LLM meeting fallback now uses role-aware evidence/alibi strategy:
crewmates require suspicion evidence before voting a player, imposters avoid
self/known teammates and blend into existing accusations when possible.

**Current evidence:** voting mechanics are now proven end-to-end in the
2026-05-10 full-trace live run
`guided_bot/traces/voting_mechanics_20260510_8p2i_cd600_vote600_tasks16_livetarget_full`.
Living bots reached intentional targets and emitted `vote_attempted`; ghost bots
did not vote.

**Next step:** continue prompt-tuning against evidence-rich traces and compare
LLM-directed meeting choices against the role-aware no-LLM fallback.

**Key code:** `modes/meeting.nim`, `snapshot.nim`, `prompts.nim`

---

### No pretending/cover behavior in imposter games [LOW]

Across 2 full imposter games (~2000 ticks, seed 100), zero ticks in pretending
mode. Bot moves exclusively toward crewmates — looks predatory.

**Cause:** Cover patrol only triggers when no visible target + memory expired +
reached station + loitered. With test's 48-tick kill cooldown, `killReady`
almost always true, bot always finds target before cover kicks in. At realistic
cooldowns (1200 ticks), ~1000 ticks between kills should allow cover. Needs
verification at realistic settings.

**Improvement ideas:**
- Force pretending N ticks after successful kill (alibi at nearby station)
- Add "cover cooldown" after kill — avoid chasing even if killReady=true
- Make cover patrol PRIMARY behavior, kill as interrupt on opportunity

---

## Fixed (historical)

### Mode-param consumption and LLM mode summaries — FIXED 2026-05-12

Gameplay mode params are now consumed by the mode handlers instead of merely
being parsed/traced: `task_completing` honors directed task targets,
`pretending` honors directed fake-task targets, `hunting` honors idle cover
mode, `alibi_building` filters fake-task choices by requested room, and
`tcAbandonOnNearbyBody` gates the body-report reflex. Each mode also exports a
`summarizeForLlm` hook, and `current_mode.summary` is included in LLM snapshots.

**Key code:** `mode_registry.nim`, `snapshot.nim`, `modes/*.nim`,
`test/mode_params_snapshot_test.nim`

### Self-body flee loop — FIXED 2026-05-11

`body_newly_in_view_flee` used to fire repeatedly on the same body when it
left and re-entered the viewport after `ReflexCooldownTicks`, wasting imposter
time fleeing known corpses.

**Fix:**
1. `ReflexState` now remembers body world positions that already caused a
   flee, de-duplicated within 30 px Manhattan distance.
2. Bodies seen while `hunting` is already in strike/post-kill handling are
   remembered without firing the flee reflex, covering own-kill corpses.
3. Known body positions clear across meetings, game-over, and round resets.
4. `test/reflex_test.nim` pins repeated-known-body suppression and far-new-body
   firing.

**Key code:** `reflex.nim`, `test/reflex_test.nim`

### Seed-100 "meeting" interval was game-over, not voting — FIXED 2026-05-10

The long black interval previously labeled as a meeting on seed 100 was a
`CREW WINS` game-over summary. The voting parser was correctly rejecting it
because there is no SKIP button or vote grid. The remaining bug was that
game-over classification missed the server's 7px `CREW WINS` title, leaving
the bot in generic interstitial/noop until gameplay reset.

**Fix:**
1. Added a live `CREW WINS` fixture from seed 100.
2. Added game-over summary layout detection in `perception/ocr.nim`.
3. `bot.nim` maps `InterstitialGameOver` to `PhaseGameOver`.
4. `trace.nim` logs `interstitial_kind` in `perception.jsonl`.

**Verified:** Seed 100, 4-player/1-imposter, 180s live match now records
`phase=game_over`, `interstitial_kind=game_over`, and `game_over` events for
all four bots. Real voting fixtures still parse as voting with `selfSlot=7`.

**Key code:** `perception/ocr.nim`, `bot.nim`, `trace.nim`,
`test/ocr_voting_test.nim`, `test/voting_diag_test.nim`

### Imposter role never detected [HIGH] — FIXED 2026-05-04

`role_revealed` always reports crewmate even w/ `--force-role imposter`.

**Root causes:**
1. Wrong kill-button HUD coords: was (109,110), actual (1,115) per server
   HUD rendering
2. No OCR-based role inference: interstitial OCR detected "IMPS"/"CREWMATE"
   but never used to set role

**Fix (2-layer):**
1. Corrected coords: `KillIconX=1`, `KillIconY=115` (`perception/actors.nim`)
2. OCR role inference during interstitials: split `InterstitialRoleReveal` into
   crewmate/imposter variants, set `belief.self.role` immediately during
   classification (mirrors italkalot/nottoodumb `rememberRoleReveal`)

**Verified:** Seed 100 (imposter) + Seed 7 (crewmate) both correct.

**Note:** `--force-role imposter` unreliable in local harness (race condition w/
filler bots). Known imposter seeds: 50, 100.

**Key code:** `perception/actors.nim`, `bot.nim`, `types.nim`,
`perception/ocr.nim`

---

### Trace manifest never finalized [LOW] — FIXED 2026-05-04

All `manifest.json` show `"closed": false`. `closeTrace` only called from
`destroyBot`, which was never invoked (no FFI export, no `close()` method).

**Fix (3-layer):**
1. `ffi/lib.nim`: added `guidedbot_destroy_policy(handle)` export
2. `cogames/amongthem_policy.py`: added `close()` + `__del__` finalizer
3. Graceful degradation via `getattr(..., None)` for old libraries

**Key code:** `trace.nim`, `bot.nim`, `ffi/lib.nim`,
`cogames/amongthem_policy.py`
