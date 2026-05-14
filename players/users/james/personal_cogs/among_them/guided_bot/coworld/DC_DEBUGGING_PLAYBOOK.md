# Bot Disconnect Debugging Playbook

Working notes from the 2026-05-14 session investigating why guided_bot
disconnects from hosted Coworld Among Them games well before the game ends.
This is a starting point for a fresh session — read it cold, don't assume
prior context.

## 0. 2026-05-14 resolution update

The early-disconnect failure reproduced locally against the refreshed
canonical `among_them` Coworld package (`among_them:0.1.20`,
`cow_4e26463b-a768-4db3-9aa9-2af8f3e009e7`) with 8 guided_bot player
containers. The wrapper diagnostics in `policy_player.py` showed every
player closing at ~40 seconds / tick ~892 with:

```text
class=ConnectionClosedError code=1006 sent_code=1011 sent_reason='keepalive ping timeout'
```

That means the Python `websockets` client closed the connection after its
own protocol-level keepalive ping timed out. The game server was still
streaming binary frames, and the bot was still sending actions.

`guided_bot/coworld/policy_player.py` now disables client keepalive pings
with `ping_interval=None` for Coworld websocket connections and logs close
diagnostics that include close codes, last frame/action, counters, and
recv/send timing. A follow-up local Coworld play run using the fixed image
`jamesboggs-guided-bot-coworld-wsfix-20260514-144036:latest` reached
tick 2740+ for all 8 bots and ended by the configured time limit, not by the
old 40-second keepalive failure.

The older server-kick / no-op fallback hypothesis below is still useful
context for gameplay and hosted-league analysis, but it is no longer the
best explanation for the local Coworld websocket close reproduced in this
session.

---

## 1. The actual problem (as of 2026-05-14)

In the Among Them Daily league, our guided_bot consistently disconnects
from games long before they end. Concrete example from
`ereq_034c9c4a-8c69-4631-8d42-b657892afb74`:

| bot | last frame | how the run ended |
|---|---:|---|
| slot 0 (other policy)  | 4841 | normal game end, saw `EOF` after final frame |
| slot 1 (`truecrew`)    | ~4800 | saw voting → end normally |
| **slot 4 (our bot)**   | **880** | WS closed, perceived `game_over` |
| slot 5 (Python `player.py`) | ~50 | crashed with `keepalive ping timeout` |

So the game ran ~4842 server frames, and our bot was kicked at frame 880
(~18 % of the way through). The bot's avatar visibly vanishes from the
replay around that moment; that's what "the agent disappears" in the
replay actually corresponds to.

We confirmed the bot *itself* doesn't crash — it logs decisions every
frame up to 880, then the WebSocket closes from the server side.

---

## 2. What we've ruled in

These are findings we're confident about. Don't re-investigate from
scratch unless you have a reason.

### 2.1 Bedrock credentials are not reaching the container

Every snapshot the bot sends to its LLM controller fails:
```
[trace:guidance] {"kind":"llm_call_failed","reason":"no_key",
  "detail":"AWS Bedrock credentials unavailable:
            container credentials env not set;
            aws CLI not found"}
```

`llm.nim:318-336` resolves AWS credentials in this order:

1. Static env vars (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
   `AWS_SESSION_TOKEN`).
2. ECS task-role metadata via `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` /
   `_FULL_URI` (`llm.nim:256-300`).
3. `aws configure export-credentials` (`llm.nim:302-316`).

In the league container all three fail: no env vars, no metadata URI,
no `aws` CLI installed in the slim image. We pass
`coworld upload-policy --use-bedrock --secret-env GUIDED_BOT_BEDROCK_MODEL=…`
during upload, but evidently Coworld is *not* injecting
`AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` (or whatever it uses) into the
running container in a form the bot understands. This is probably an
issue for Softmax — either ask them which env vars / IAM mechanism the
runner uses, or extend `llm.nim`'s credential chain to honor it.

This has likely been broken for every prior submission. We only saw it
now because at the previous `events` trace level
(`guided_bot/coworld/Dockerfile:28`) the `[trace:guidance]` stream isn't
emitted, so the failure was invisible.

### 2.2 The bot's localizer has at least two failure modes

In the league episode `ereq_034c9c4a` (rich data, slot 4):

| range | `localized` | symptom |
|---|---|---|
| ticks 1–239 | **false** (bootstrap) | bot outputs 0-mask noop, doesn't move |
| tick 240 | flips → **true** | locks onto (508, 120), bot starts navigating |
| ticks 240–764 | **true** | normal-ish play, ~141 distinct positions |
| tick 765 | flips → **false** (regression) | output collapses back to 0-mask noop |
| ticks 765–880 (until WS close) | **false** | 116 identical no-op frames |

The bootstrap window is consistent across runs (lock typically lands
around tick 240–290) and looks intentional — possibly the localizer
can't run during the alibi screen.

The mid-game regression at tick 765 is the more dangerous one — it
happens when the bot has been stationary at a single task tile for a
while. Self-play could not reproduce it; see §3.4.

### 2.3 "No localization → 0-mask noop" is what makes the server kick us

From tick 765 to tick 880 the bot's decision output is *literally*
identical every tick: `mask=0, discipline=noop, press_a=False,
press_b=False, steer_to=null`. Position never changes from (459, 39).
This is 116 consecutive frames (~5–6 seconds at game rate) of
zero-input.

The same noop output happened for the first 239 ticks too, but the
server didn't kick us then — likely because every bot is near-idle
during the alibi/role-reveal phase, so the kick threshold isn't tripped
early. Once everyone else is moving and doing tasks, our 6-second
freeze becomes anomalous, and the server cuts the slot.

### 2.4 The "disappears in the replay" reframe

Our first instinct was meeting teleport. **Wrong.** The bot's
own localization data shows continuous motion with exactly one big
"jump" — the initial unlocalized → localized transition from (0,0) to
the real spawn position. No mid-game teleport in the bot's belief.

What the user actually sees in the replay is the bot freezing at
(459, 39), then the server force-removing its avatar after ~6 seconds
of zero input. From a viewer's camera that's "the bot disappears."

### 2.5 Imposter teammate, no kills, but we still won

In `ereq_034c9c4a` the *other* imposter (slot 2) got 2 kills, the
imposter team won, and we were credited with the win (`score=100`)
despite contributing nothing — we never picked a kill target
(`preferred_target: -1` from mode entry to disconnect). This explains
why league results can show "imposter win" alongside our broken
trace: we get carried.

### 2.6 The previous "end_tick = 120" was a trace-level artifact

The original investigation almost concluded "the bot disconnects at
tick 120." That was wrong:

- `trace.nim`'s manifest only updates `endTick` when a stream is
  written.
- At `events` level the only events emitted post-startup are
  `role_revealed` / `imposters_detected` / `hunting_phase_changed`,
  all at ~tick 120.
- After tick 120 nothing else triggers an event-level write, so
  `endTick` froze.

The websocket actually closed much later (~tick 880 in the league
game). `endTick` at lower trace levels is **not** a reliable proxy for
when the connection closed.

---

## 3. What we've ruled out (and why)

### 3.1 The bot is not crashing

No tracebacks, no abnormal exit codes. The container exits 0 and the
trace writer cleanly writes its closing manifest. The WS close is
initiated server-side.

### 3.2 The bot is not catastrophically slow

We initially blamed `trace_level=full` overhead. Recomputing the
wall-clock numbers properly (using slot 0's log timestamps as the real
game-start anchor — `16:31:32` — not the episode `created_at` which is
the *queue* time):

- Other bots: ~24 fps for 200 s, 4841 frames.
- Our bot: ~18.7 fps for ~47 s, 880 frames.

That's ~22 % slower, not 4× slower. Probably real but not the
disconnect cause.

### 3.3 The bot is not being voted out as imposter

Imposters can't be killed; they can be ejected via meeting. Server-side
results confirm `vote_players[4]=0, vote_skip[4]=0` — meaning *we
didn't cast a vote in any meeting and weren't the target of one
either*. The bot's perception simply never detected the meeting
(`phase: gameplay` throughout, even when `visible_players=7` strongly
suggested it was in the meeting room).

### 3.4 Self-play doesn't reproduce the bug

We tried two hosted-game configs:

| config | coworld_id | how it ended |
|---|---|---|
| hosted_play default (v0.1.11) | `cow_a7418f9b…` | game_over at ~960 ticks, no mid-game loc loss |
| **tournament canonical** (v0.1.14) | `cow_6f4966f8…` | game ended at ~770–796 across slots, also no mid-game loc loss |

In *both* runs the game ended via *our agents being kicked one by one*
(see §4 below). Self-play with 8 identical guided_bots produces a
degenerate game where no agent is robust enough to keep the alive count
up. The mid-game tick-765 localization regression we want to study has
not been reproduced locally.

---

## 4. The hosted-self-play kick chain

Worth understanding in detail because it's evidence that the same
"server kicks unresponsive players" mechanism applies in hosted games
exactly as we suspect it does in the league.

In the tournament-config self-play (`/tmp/hosted_play_tournament/`),
agents ended in this order:

| order | slot | role | end tick | saw `game_over`? |
|---:|---:|---|---:|:---:|
| 1 | 7 | imposter | 770 | yes |
| 2 | 6 | crewmate | 775 | yes |
| 3 | 5 | crewmate | 782 | yes |
| 4 | 4 | imposter | 789 | yes |
| 5 | 3 | crewmate | 792 | **NO** (last event `t=730 task_started`) |
| 6 | 1 | crewmate | 794 | **NO** (last event `t=770 task_started`) |
| 7 | 2 | crewmate | 794 | **NO** (last event `t=787 task_started`) |
| 8 | 0 | crewmate | 796 | **NO** (last event `t=793 task_started`) |

Four crewmates (0, 1, 2, 3) never saw a `game_over` screen — their
WebSockets just dropped mid-task. The other four saw the screen and
exited cleanly. The most consistent explanation: server cut slots
0/1/2/3 progressively, which dropped alive-crew to 2 (≤ imposters),
which fired `checkWinCondition` in `sim.nim:2795-2797`, which entered
GameOver phase and broadcast the game-over frame to the remaining live
slots. Then the WSes for 0/1/2/3 were torn down.

`game_over` in the bot's trace (`bot.nim:654-657`) comes from the
*perception layer* detecting a `PhaseGameOver` rendered frame.
If a bot never received that frame, it was already cut by the time
the server broadcast it.

This is the cleanest single piece of evidence that **the server kicks
silent or sluggish bots without warning, and counts them as dead for
win-condition purposes**. The same thing almost certainly happens to
us in the league after our 6-second 0-mask freeze.

---

## 5. Working hypotheses ranked by promise

### H1 — Server kicks for low-information action stream (HIGHLY LIKELY)
After localization is lost, we emit `mask=0` for ~115 consecutive
frames. The hosted server appears to detect this and cut the
connection. Same mechanism kicks the 4 crewmates in §4.

**Fix path:** when `localized=false`, output *something* non-zero —
random nav, repeat-last-mask, or even just a directional jitter. Even
if it's wrong from a gameplay standpoint, it would keep the connection
alive long enough to recover localization.

**Test:** patch the no-localization fallback in `bot.nim`'s
`decideNextMask` to emit a noisy non-zero mask, rebuild
`libguidedbot.dylib`, rerun hosted self-play. If our slots stop getting
kicked and the game proceeds to `maxTicks=10000`, we've validated the
mechanism.

### H2 — Localizer regression at tick 765 is the *trigger*, not the disconnect (LIKELY)
The bot was stable at (459, 39) for ~165 ticks before localization
flipped to `false`. Something about that prolonged static-camera
state confuses the localizer.

**Possible mechanisms:**
- Patch-hash localizer has a confidence threshold that's too eager to
  reset.
- An animation overlay (task UI, task arrows, etc.) gradually
  accumulates pixel drift the localizer can't tolerate.
- A periodic background animation (lights, eyes blinking) finally hits
  a frame the patch hasher misclassifies.

**Test:** at decisions-level trace, look at `[trace:perception]` lines
around tick 760–770 (assuming we wire perception emission, see §6.1).
We expect to see a pattern of "match score declining" or similar before
the flip.

### H3 — Bedrock credentials would help if fixed, but aren't the disconnect cause (UNLIKELY)
With LLM working locally (via `aws configure export-credentials` SSO
fallback) the bot still froze at end of game. So LLM is not what's
holding the bot up. Fix Bedrock for *better play*, not for *the
disconnect*.

### H4 — Trace I/O overhead (DOWNGRADED)
Recomputed: we're ~22 % slower than other bots, not 4× slower. Trace
volume probably isn't the dominant factor in the disconnect. Keep an
eye on it but don't optimize first.

---

## 6. Open instrumentation gaps

### 6.1 `[trace:perception]` stream is silent

Per `trace.nim`, perception logging fires at `TraceDecisions` and
above, so we should be seeing it at `full`. We aren't. Grep across the
league log (`/tmp/new_run_logs/…-policy_agent_4.txt`) and the
hosted-play log shows **zero** `[trace:perception]` lines.

Either the logging call isn't wired in for this code path, or there's
a gating condition. **Fix this first** — without perception traces,
we can't diagnose the localization regression. Likely it's a missing
call to `logPerception()` in `bot.nim`'s perception/localize step.

### 6.2 We can't see whether `mask=0` is *actually being sent*

The trace records the bot's computed action mask. We don't know
whether `policy_player.py` actually sends every computed mask over the
WebSocket. If there's a code path where the Python wrapper drops the
send (e.g., when localization fails), the server would see a stream of
"no input received" and kick us even faster than we'd predict from the
trace.

**Fix:** add a single-line log in `policy_player.py` after each
WebSocket send, ideally with the mask byte sent. Even at decisions
level that'd be ~1 small line per tick.

### 6.3 No server-side log for `ps_…` sessions

`hosted_play.py --pull-episode-logs` came back "no new episodes found"
— hosted-game (`ps_…`) sessions don't publish ereq artifacts like
commissioner-driven episodes do. `coworld hosted-game create` /
`coworld play` don't expose server-side game stdout.

`sim.nim` references `/admin`, `/control/restart`, `/control/kick`
endpoints but those are operator-facing. If we need authoritative
server-side confirmation for an experiment, the option is:

- Attach a 9th client to the spectator (global) websocket — the
  session-create response has a `global_url`. That endpoint should
  carry server-authoritative state.
- Or ask Softmax for `game.stdout.log` of a specific session.

---

## 7. Useful commands and recipes

### 7.1 Finding the right IDs

```sh
cd /Users/jamesboggs/coding/metta

# Among Them Daily league + division
LEAGUE=league_494db37d-d046-4cba-a99a-536b1439262f
DIVISION=div_334593c6-da90-4651-98c7-606573ea1474

# Latest canonical Among Them Coworld package
uv run coworld list | grep -i among_them | grep -i yes
# -> cow_6f4966f8-b169-4c9e-be67-8ffc0d9b14fe  among_them  0.1.14  yes
```

### 7.2 Pulling our last submission's episodes

```sh
POLICY=jamesboggs-guided-bot-coworld-20260514-092239:v1

# All episodes our policy participated in (last 50)
uv run coworld episodes -p "$POLICY" --limit 50 --json > /tmp/eps.json

# Server-side scores/kills/votes for one episode
uv run coworld episode-results <ereq_id> --output /tmp/r.json

# Our agent log
uv run coworld episode-logs <ereq_id> --mine --download-dir /tmp/logs

# ALL agents' logs (other policies too — different log formats per policy)
for slot in 0 1 2 3 4 5 6 7; do
  uv run coworld episode-logs <ereq_id> --agent $slot \
    --download-dir /tmp/logs
done
```

### 7.3 Inspecting a trace log

`policy_agent_N.txt` is a stderr-mode JSONL stream with `[trace:…]`
prefixes. Useful one-liners:

```sh
# Stream-kind tally (decisions / events / modes / guidance / snapshots / perception)
awk '/^\[trace:/ {print $1}' LOG | sort | uniq -c

# Last tick the bot processed
grep -oE '"t":[0-9]+' LOG | sed 's/"t"://' | sort -n | tail -1

# Localization transitions (parses every decision line)
python3 -c "
import json
prev=None
for line in open('LOG'):
    if not line.startswith('[trace:decisions]'): continue
    o = json.loads(line[len('[trace:decisions] '):])
    if o.get('localized') != prev:
        print(o['t'], 'localized', prev, '->', o.get('localized'))
        prev = o.get('localized')
"

# Distinct (mask, disc, intent) tuples — useful for spotting "stuck on noop"
python3 -c "
import json
from collections import Counter
c=Counter()
for line in open('LOG'):
    if not line.startswith('[trace:decisions]'): continue
    o = json.loads(line[len('[trace:decisions] '):])
    c[(o.get('mask'), o.get('discipline'),
       o.get('intent',{}).get('press_a'),
       bool(o.get('intent',{}).get('steer_to')),
       o.get('localized'))] += 1
for k,v in c.most_common(10): print(v,k)
"
```

### 7.4 Running a tournament-config hosted game locally

```sh
cd /Users/jamesboggs/coding/personal_cogs && source .venv/bin/activate

GUIDED_BOT_TRACE_DIR=stderr \
GUIDED_BOT_TRACE_LEVEL=full \
python among_them/guided_bot/coworld/hosted_play.py \
    --coworld cow_6f4966f8-b169-4c9e-be67-8ffc0d9b14fe \
    --variant default \
    --default-player guided_bot:local \
    --output-dir /tmp/hosted_play_<name> \
    --pull-episode-logs \
    --timeout 1200
```

**Important:** `hosted_play.py`'s baked-in default `--coworld` is the
v0.1.11 package, **not** the canonical league package. Always pass
`--coworld cow_6f4966f8-b169-4c9e-be67-8ffc0d9b14fe` explicitly. Worth
fixing in the script itself.

Even with the right config, self-play ends at ~770–800 ticks (see §4) —
*not* because the server-side game ends naturally, but because half our
agents get kicked. Don't be fooled by `end_tick ≈ 790`.

### 7.5 Building / submitting an image

```sh
cd /Users/jamesboggs/coding/personal_cogs/among_them
STAMP=$(date +%Y%m%d-%H%M%S)
IMAGE=jamesboggs-guided-bot-coworld-$STAMP
POLICY_NAME=$IMAGE

docker buildx build --platform linux/amd64 -t "$IMAGE" --load \
    -f guided_bot/coworld/Dockerfile .
docker run --rm --platform linux/amd64 "$IMAGE" /bin/guided_bot --help

cd /Users/jamesboggs/coding/metta
uv run coworld run-episode ./coworld/coworld_manifest.json "$IMAGE"  # smoke

uv run coworld upload-policy "$IMAGE" --name "$POLICY_NAME" \
    --use-bedrock \
    --secret-env GUIDED_BOT_BEDROCK_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0
uv run coworld submit "$POLICY_NAME:v1" --league "$LEAGUE"
```

Watch for the Docker 29 ECR `HEAD` 403 manifest issue. Recent uploads
(2026-05-14) succeeded first try; previous (2026-05-13) needed a
`crane` workaround.

---

## 8. Key source-file map

Read these directly when in doubt; they're the source of truth.

| File | What's in it |
|---|---|
| `guided_bot/coworld/Dockerfile` | `GUIDED_BOT_TRACE_LEVEL`, image entrypoint |
| `guided_bot/coworld/policy_player.py` | WS protocol bridge, instantiates `AmongThemPolicy(policy_env)` with NO kwargs |
| `guided_bot/coworld/hosted_play.py` | Hosted-game orchestrator — wrong default `--coworld`, see §7.4 |
| `guided_bot/cogames/amongthem_policy.py` | Python policy wrapper, kwarg-vs-env trace handling (lines 187-190) |
| `guided_bot/bot.nim` | `decideNextMask`, trace setup (line 97), `game_over` emission (lines 654-657) |
| `guided_bot/trace.nim` | Trace levels, stderr mode (line 337-348), `logFrame` skipped in stderr (lines 721-727) |
| `guided_bot/llm.nim` | AWS credential chain (lines 256-336), Bedrock SigV4 |
| `~/coding/bitworld/among_them/sim.nim` | Server simulation. Win conditions at `checkWinCondition` (lines 2780-2799). Time limit at `maxTicksReached` (lines 2772-2778). |
| `~/coding/bitworld/among_them/server.nim` | Among Them Nim WS server entrypoint |

## 9. Anti-patterns: hypotheses we wasted time on

So a future Claude can skip these traps directly:

- ❌ **"end_tick=120 means the bot disconnects at tick 120."** No — it
  means *no event-level trace fired after tick 120*. Use
  `trace_level=full` or look at the last `[trace:decisions]` tick, not
  the manifest `end_tick`, when running below `decisions`.
- ❌ **"7 visible players = meeting room."** It's also the spawn room
  immediately post-alibi. Don't infer phase from visible-player count
  alone; check the `phase` field in snapshots, and check for a
  contiguous position jump in the localizer.
- ❌ **"Episode `created_at` is when the game started."** It's when the
  EpisodeRequest was queued. The real game start is when slot 0
  connects (see slot 0's log line, which is timestamped). Off-by-a-minute
  in the queue gap will give you wildly wrong fps numbers.
- ❌ **"`end_tick=880` is the game end."** It's when *our* WS closed.
  Compare against other slots' last-frame numbers from
  `episode-logs --agent <slot>` to know whether the game continued
  without us.
- ❌ **"Trace level full is making the bot too slow, that's why we
  disconnect."** It's a real ~22 % slowdown, but recomputing
  wall-clock properly shows it's nowhere near 4×. Don't lead with
  perf-blame.
- ❌ **"Self-play running for ~790 ticks means the game ends at 790."**
  No — it means our self-play bots all get kicked progressively. Half
  of them won't even see the `game_over` screen.
- ❌ **"`coworld hosted-game create --variant default` uses the league
  config."** Only if you pass the right `--coworld` ID. The default
  in `hosted_play.py` is the previous package (v0.1.11), not the
  canonical league one.

## 10. Suggested next-session opening moves

1. **Preserve the wrapper ping fix when rebuilding or uploading.** Any
   Coworld image used for debugging should include
   `WEBSOCKET_CONNECT_OPTIONS["ping_interval"] = None`; otherwise it can
   reproduce the old 40-second self-close regardless of bot behavior.
2. **Use the websocket close diagnostics before inferring policy failure.**
   Check each `policy_agent_*.txt` for `BitWorld player websocket closed`;
   `sent_reason='keepalive ping timeout'` points at the Python wrapper,
   while a clean time-limit run should reach thousands of messages/actions
   and close only after the game exits.
3. **Wire up `[trace:perception]` emission** so we have one more
   stream to debug the localization regression with. (Search for
   `logPerception` in `bot.nim` — it's probably wired conditionally or
   not at all.)
4. **Patch the "not localized → mask=0" path** in `bot.nim`'s
   decision pipeline to emit a non-zero "keepalive wander" action.
   Rebuild `libguidedbot.dylib`. Re-run §7.4 self-play. Verify all
   8 agents survive to `maxTicks=10000` (or near it).
5. **If self-play now survives, build a new image** with this patch
   *and* the same `GUIDED_BOT_TRACE_LEVEL=full` setting, submit it,
   and check the next league episode for whether our slot reaches
   ~4800 frames.
6. **Independently, raise the Bedrock cred issue with Softmax** — even
   when we stop being kicked, the bot is playing without LLM
   guidance, which caps its strategic ceiling regardless.

## 11. Session changes already shipped

What this session actually changed in the repo:

- `guided_bot/coworld/Dockerfile:28` — `GUIDED_BOT_TRACE_LEVEL` bumped
  from `events` → `full`.
- `guided_bot/coworld/README.md` — added 2026-05-14 row to the
  submission log.
- `guided_bot/coworld/policy_player.py` — added websocket close
  diagnostics and disabled client keepalive pings for Coworld websocket
  connections after reproducing `sent_reason='keepalive ping timeout'`.
- `guided_bot/coworld/test_policy_player.py` — added focused coverage for
  the websocket diagnostics summary.
- New uploaded policy version
  `jamesboggs-guided-bot-coworld-20260514-092239:v1` is the **active
  champion** in the Among Them Daily league (membership
  `lpm_5324f856-8a27-49e7-84c7-3a7efd0e9cd2`, policy version id
  `96327238-9a16-484f-843b-ab735bc97d29`). It's the first submission
  with full tracing — every future league episode for this submission
  will produce diagnosable logs.

This document itself is uncommitted — commit it before the next
session so future-Claude can find it via `git log`.
