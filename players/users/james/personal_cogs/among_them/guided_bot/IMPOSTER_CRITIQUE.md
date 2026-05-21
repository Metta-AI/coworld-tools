# Imposter Strategy Critique — 2026-05-08

> Updated 2026-05-10. This is now a historical critique plus remaining
> imposter-strategy backlog. The voting/meeting detection failure described
> below has been fixed and live-verified; do not use this file as evidence
> that meetings are currently broken.

Live test: 8 guided_bot agents, 2 imposters, 5 minutes, seed 42, standard settings.
No LLM guidance active. Voting parse never succeeded for any bot.

Follow-up voting verification: 8 guided_bot agents, 2 imposters, 600-tick kill
cooldown, 600-tick vote timer, 16 tasks per crewmate, 90 seconds, seed 42,
`--trace-level full`. Trace root:
`guided_bot/traces/voting_mechanics_20260510_8p2i_cd600_vote600_tasks16_livetarget_full`.
Every living bot voted; the ghost did not.

---

## Results

| Metric | Bot 4 (color 4) | Bot 6 (color 6) |
|--------|------------------|------------------|
| Kills | 0 | 3 |
| Ejected? | Yes (t≈2316, ~96s) | No |
| Kill-ready windows | 1 (41s, 0 crew seen) | 4 (used 3/4) |
| Strike-to-confirm | n/a | 1 tick |
| Time in hunting | 74.5% | 94.6% |
| Time in alibi | majority | 80% |

Game timed out. The original "53/48 tasks" count was a trace-analysis error:
long runs can include post-game reset behavior, so productivity summaries must
stop at the first game-over event.

---

## Critical Bugs

### 1. Ghost detection is broken

Bot 4 was ejected at t≈2316 and spent 162 seconds as a ghost that never detected `is_ghost=True`. It kept running hunting mode (which requires alive + not ghost), had `kill_ready=False` permanently, and repeatedly fled from its own corpse (body color=4 at screen edge, triggering `body_newly_in_view_flee` every 240 ticks).

**Root cause:** `perception/actors.nim` — ghost detection relies solely on matching a ghost-icon sprite at a fixed HUD position (`KillIconX`, `KillIconY`). If the sprite match fails, `ghostIconFrames` never reaches threshold. No fallback exists.

**Fix:** If `kill_ready=False` persists for >1200 ticks (one full cooldown cycle) after a meeting/interstitial without the bot having killed, infer ghost state. Also: don't flee from bodies whose color matches `self.colorIndex`.

### 2. Voting/meeting detection never works — FIXED 2026-05-10

`parseVotingScreen` returned `valid=false` for all 8 bots across the entire meeting (~480 ticks). `PhaseVoting` was never set. The `voting_screen_appeared` reflex never fired. Meeting mode was never entered. No bot cast a vote.

**Root cause:** `bot.nim` and `perception/voting.nim` — both the interstitial-path and the fallback-probe voting parse failed. The voting screen template did not match what the server rendered.

**Fix status:** Live meeting/voting frames are now parsed, `PhaseVoting` is set,
meeting mode is entered by living bots, cursor state is refreshed every
interstitial voting frame, and vote attempts are traced. The remaining work is
chat emission and evidence-based vote strategy, not mechanical voting.

### 3. Seeking patrol collapses to nearest station

Bot 6 visited only 7 unique locations, concentrated in North/East Cafeteria (high-traffic, low-privacy). Bot 4 had a 41-second kill window and saw zero crewmates.

**Root cause:** `modes/hunting.nim` — `pickSeekingStation` score = `killSiteScore * 3 - roomTrafficScore - dist/6 - memoryThreat * 70`. The `dist/6` penalty dominates at moderate distances, making the bot pick the nearest station regardless of kill potential. Cafeteria stations cluster together, so once the bot enters Cafeteria it stays there.

**Fix:** Reduce distance penalty weight, or add a diversity bonus (penalty for revisiting the same station within N ticks). Consider a fixed patrol circuit through low-traffic rooms (Electrical → Security → Reactor → Engine → Nav) during seeking.

---

## Medium-Priority Issues

### 4. Confirmed-kill target tracking

Bot 6 killed color 5 twice (t=3995 and t=5219). Either the server allows ghost-killing (wasting a cooldown cycle) or color identification was wrong for one kill. Either way, the imposter should maintain a `killedColors` set and avoid re-targeting.

**Status:** Partially addressed in the envelope-level memory model. On `kill_confirmed`, `bot.nim` now marks the target color dead via `recordConfirmedKill`; `isCrewTarget` already rejects dead players. This avoids adding a second killed-colors store while covering the same re-targeting failure when body detection lags or misses.

### 5. Alibi phase doesn't gather intel

During the 1200-tick cooldown, the imposter sits in Cafeteria doing fake tasks. Good for alibi, terrible for learning where isolated crewmates are. When kill becomes ready, player memory is stale and it must re-seek.

**Fix:** During alibi, prefer routes that traverse multiple rooms. Track which rooms have crew vs. empty. Pre-position near a likely-isolated-target room ~100-150 ticks before cooldown expires (predict cooldown expiry from known cooldown duration).

### 6. No imposter coordination

Bot 4 and Bot 6 operated independently. No territory splitting, staggered kills, or mutual defense at meetings. Bot 4 was ejected while Bot 6 could have voted to protect it (if voting worked).

**Fix:** Deferred until vote strategy exists. Mechanical meetings are functional;
next step is partner-aware vote policy, territory splitting based on color index
parity, and avoiding the same room as partner during kills.

---

## What Works Well

- Kill execution is instant and precise (DisciplineKillStrike + 20px range)
- Post-kill escape (vent or station) succeeds every time — Bot 6 was never caught at a body
- Known-imposter filtering correctly excludes partner from witness counts and targeting
- Alibi fake-hold cadence (68 episodes, 2s each) looks convincingly crewmate-like
- The reflex system (pretending→hunting on lone crew, hunting→fleeing on new body) transitions cleanly

---

## Priority Order

1. Ghost detection fallback (critical — 162s of wasted dead-imposter compute)
2. Seeking patrol diversity (high — kills depend on finding isolated targets)
3. Killed-player tracking (medium — prevents wasted kills)
4. Alibi-phase reconnaissance (medium — faster target acquisition post-cooldown)
5. Vote strategy and imposter coordination (medium — mechanical voting works;
   strategy is pending)

---

Once the remaining imposter strategy items are promoted into TODO/design docs or
implemented, delete this file.
