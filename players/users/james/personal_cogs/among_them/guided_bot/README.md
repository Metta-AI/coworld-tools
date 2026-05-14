# guided_bot

Modular hybrid agent for Among Them with a fast scripted inner loop
(per-tick perceive → update → decide → act) and a slower asynchronous
LLM guidance loop that sets the active **mode** and its structured
parameters. Meeting chat and vote choice are LLM-controlled through a
guarded action queue, while gameplay modes consume LLM params through
their mode handlers. Per-mode scratch summaries are included in LLM
snapshots so the model can see what the current mode is doing. Modes are
the primary extensibility surface; adding one is a new file plus one
registry entry.

**Design doc:** [`DESIGN.md`](DESIGN.md). Load-bearing — read it before
editing.

**Implementation plan:** [`IMPL_PLAN.md`](IMPL_PLAN.md). Phase 6+
roadmap based on a full mode audit (2026-05-01).

**Task mode design:** [`TASK_COMPLETING_DESIGN.md`](TASK_COMPLETING_DESIGN.md).
Detailed task lifecycle and completion detection.

**Open bugs:** [`TODO.md`](TODO.md). Known issues and reproduction
steps.

**Modulabot deprecation:** the local `../modulabot/` directory is fully
deprecated and kept only for historical reference. Do not inspect,
modify, test, run, or rely on it while working on guided_bot unless
James explicitly asks for modulabot. Historical mentions of modulabot in
older design notes describe provenance, not current source-of-truth
guidance.

## Status

**Phase 6 core mode behavior is implemented and live-verified.** The
bot completes tasks, navigates by hierarchical waypoints, identifies its
own colour from the centered player sprite, parses voting screens, and
executes cursor-aware votes in meetings. Meeting chat now flows through
the Nim action buffer, C FFI, Python policy hook, and local WebSocket
runner; LLM meeting snapshots include player memory, vote dots, recent
chat, solo-survival trust, distance-weighted body proximity, explicit
alive/dead voting status, witnessed venting, and a structured evidence
ledger. The meeting prompt now prefers one short living-player chat line
before voting, answers direct meeting chat when useful, confirms votes
only when the parsed cursor is already on the intended target slot, treats
dead/ghost players as wait-only in meetings, and gates crewmate player
votes on positive incriminating evidence rather than lack of trust.
Focused Nim/Python checks pass and the cogames shared library builds.

Latest end-to-end voting check: an 8-agent, 2-imposter live match with
600-tick kill cooldown, 600-tick vote timer, 16 tasks per crewmate, and
`--trace-level full` produced two meetings with frame traces. Every
living bot cast the intended temporary mechanical vote; ghosts correctly
did not vote. The post-2026-05-10 strategy path replaces that temporary
target with LLM-directed votes over a structured evidence ledger plus
hard legality guards for self, dead players, invalid slots, and known
imposter teammates. Trace root:
`guided_bot/traces/voting_mechanics_20260510_8p2i_cd600_vote600_tasks16_livetarget_full`.

Latest Bedrock meeting check: an 8-agent, 2-imposter live match with
standard 1200-tick kill cooldown, 8 tasks per crewmate, 180 seconds,
seed 42, and `--trace-level decisions` closed all manifests, detected
all roles, produced two meetings per bot, 358 successful LLM responses,
89 meeting actions, 6 chat lines, 12 vote attempts, and zero LLM
failures. Trace root:
`guided_bot/traces/meeting_bedrock_20260511_8p2i_standard`.

Latest prompt-tuning check: an 8-agent, 2-imposter Bedrock run with
seed 42, 600-tick kill cooldown, 16 tasks per crewmate, 120 seconds,
and `--trace-level decisions` was rerun after the living speak-first,
dead/ghost wait-only, and concrete-evidence gate prompt changes. It
closed all manifests, produced two `meeting_started` events per bot
(the second at match cutoff), 254 successful LLM responses, 37 meeting
actions, 7 living-player chat lines, 7 SKIP vote attempts, and zero LLM
failures. The dead bot emitted wait-only actions, and no crewmate vote
used "least vouched for" / no-alibi reasoning. One chat line clipped at
the 80-character cap before the final 45-55 character prompt cleanup.
Trace root:
`guided_bot/traces/prompt_loop_20260511_seed42_evidence_gate_v2`.

Latest evidence-ledger check: seed 44 was rerun after adding
solo-survival trust, distance-weighted body proximity, and legality-only
LLM vote guards. The 180-second run closed all manifests and showed the
LLM treating solo time as trust; a targeted 120-second first-meeting
rerun produced no "least trusted" votes, no solo-trust-as-suspicion
reasoning, and crewmate player votes only when near-body evidence had a
distance/score. There was one transient Bedrock startup call failure in
the targeted run; later calls recovered. Trace roots:
`guided_bot/traces/meeting_evidence_ledger_20260511_8p2i_180s_seed44_trustprompt`
and
`guided_bot/traces/meeting_evidence_ledger_20260511_8p2i_120s_seed44_notrustgap`.

Latest vent-evidence checks: the detector now separates hard proof from
probabilistic suspicion. `witnessed_vent` still marks a player as
imposter only when a crewmate had a clear prior empty view, while
`vent_suspected` / `near_vent_appearance` assigns distance-weighted
probability for newly appearing near a vent. Hard proof remains
crewmate-observer only and is blocked by self-sprite occlusion,
recent-sighting suppression, and same-vent de-duplication.

A 4-agent, 1-imposter seed-42 detector rerun with LLM disabled closed all
manifests with zero hard `vent_witnessed` events and four soft
`vent_suspected` events. Distances of 2, 10, 38, and 42 pixels produced
77%, 66%, 28%, and 23% probabilities respectively, confirming that
closer first sightings create stronger but still non-proof evidence.
Trace root:
`guided_bot/traces/vent_probability_20260511_4p_seed42`.

A full 8-agent, 2-imposter seed-42 LLM rerun closed all manifests, sent
short meeting chat, completed 51 crewmate tasks, confirmed two imposter
kills, and produced 36 soft `vent_suspected` events with zero hard
`vent_witnessed` events. The meeting prompt correctly surfaced a
probabilistic accusation ("Yellow appeared near vent twice") without
claiming hard vent proof. Follow-up prompt tuning now treats repeated
near-vent evidence, score 8+, or probability 60%+ as actionable voting
evidence unless stronger counterevidence exists. Trace root:
`guided_bot/traces/llm_vent_probability_20260511_seed42`.

Post-tuning reruns with the final prompt closed cleanly but did not
produce meetings: full 8-agent trace
`guided_bot/traces/llm_vent_probability_prompt2_20260511_seed42`
emitted 33 soft `vent_suspected` events and zero hard vent proofs; the
4-agent meeting-focused trace
`guided_bot/traces/llm_vent_probability_prompt2_4p_seed42` emitted a
62% / score-9 near-vent suspicion on the actual imposter color with zero
hard vent proofs or LLM validation failures.

Phases 1–5 (perception, action, LLM guidance, tracing, fallback
playability) remain intact underneath.

- **1.0** Frame unpacking, interstitial detection, ignore-mask scaffolding.
- **1.1** Baked reference data (palette, sprites, map, font) via `staticRead`.
- **1.2** Camera localization (~1 ms cold, <1 ms warm).
- **1.3** Actor scanning — crewmates, bodies, ghosts, role, center-sprite
  self-colour with round-latched recall (~2 ms).
- **1.4** Task-icon + radar-dot scanning (~0.1 ms).
- **1.5** ASCII OCR — `textMatches`, `bestGlyph`, `findText`, interstitial
  banner classification, plus a layout detector for the live 7px-font
  game-over summary.
- **1.6** Voting-screen parse — grid layout, slot parsing (alive/dead +
  colour), cursor/self-marker/vote-dot detection, SKIP text check,
  chat OCR with speaker attribution.

Total per-frame perception cost (gameplay): ~5 ms. Interstitial
classification: ~17 ms (banner OCR sweep plus game-over layout check).
Voting parse: variable, dominated by chat OCR line count.

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffolding, type shapes, registry, no-op pipeline, FFI + Python wrapper | done |
| 1.0 | Frame unpacking, interstitial detection, ignore-mask scaffolding, fixture tests | done |
| 1.1 | Perception reference data baked from upstream `~/coding/bitworld` checkout via `staticRead` | done |
| 1.2 | Camera localization (patch-hash global + local refit + spiral fallback) | done |
| 1.3 | Actor / body / ghost scanning + role + self-colour detection + ignore-mask exclusions | done |
| 1.4 | Task-icon scanning via `mb_scan_task_icons` + radar-dot scanning | done |
| 1.5 | ASCII OCR — `mb_best_glyph` + `mb_text_matches` + `findText` + interstitial classification | done |
| 1.6 | Voting-screen parse — grid layout, slot/cursor/vote-dot parsing, chat OCR + speaker attribution | done |
| 2.0 | Initial action layer — button-mask generation, discipline dispatch, ghost steering | done |
| — | Hierarchical waypoint navigation — replaces per-pixel A\* with precomputed graph + paths | done |
| 2.1 | `task_completing` mode — task-icon-based target selection, navigation, hold-A completion | done |
| 2.2 | `meeting` mode — cursor-aware voting, self-vote guard, evidence/alibi fallback target | done |
| 2.3 | Reflex system — 4 starter reflexes: body→reporting, body→fleeing, lone-crew→hunting, voting→meeting | done |
| 2.4 | `hunting` mode — preferred/opportunistic kill-strike + cover-behavior wander | done |
| 2.5 | `pretending` mode — walk-to-task loiter cycle for imposter cover | done |
| 2.6 | `reporting` mode — navigate to body, press A via DisciplineReport | done |
| 2.7 | `fleeing` mode — steer away from body for duration/distance | done |
| 3.1 | `snapshot.nim` — belief-state JSON rendering for LLM (DESIGN.md §8.3) | done |
| 3.2 | `llm.nim` — real Claude client via Bedrock or direct Anthropic (curly + jsony) | done |
| 3.3 | `guidance.nim` — worker thread + channels (snapshot→directive, meeting actions) | done |
| 3.4 | `bot.nim` — periodic/triggered snapshot submission + directive channel reads + TTL expiry | done |
| 3.5 | `modes/meeting.nim` — LLM-driven meeting behavior with chat, voting, and safety-net fallback | done |
| 3.6 | `prompts.nim` — system prompts for gameplay directives and meeting actions | done |
| 4 | Trace writer — structured JSONL output per DESIGN.md §11 | done |
| 5 | Fallback-only playability test; first submission | done |
| — | Trace enhancement: decision records include mask + self position | done |
| 6.1 | `task_completing` hold lifecycle + completion detection + belief task state + radar checkout | done |
| 6.2 | `reporting` success detection + body-visibility check + approach/in-range timeouts | done |
| 6.3 | `meeting` cursor-aware vote navigation + timer fix + auto-vote delay + chat emission + evidence/alibi fallback strategy | done |
| 6.4 | `hunting` cover patrol + target memory + kill confirmation + KillStrikeRange bump | done |
| 6.5 | `pretending` fake A-press during loiter + witness swap | done |
| 6.6 | `fleeing` post-flee cover navigation + flee target snap-to-passable | done |
| 7.1 | `alibi_building` mode — follow a non-imposter companion and fake nearby tasks without losing sight | done |

## Strategy

In one sentence: an LLM sets strategic intent (mode + params) on a slow
outer loop; a scripted inner loop runs modes whose decisions are a pure
function of the shared belief state, current directive params, and their
own scratch state. During meetings, the LLM gets a direct guarded action
queue for one chat/vote action at a time.

See DESIGN.md §5 (modes), §7 (meetings), §9 (fallback), §5.8 (reflexes).

## Directory layout

```text
guided_bot/
  DESIGN.md                 # design doc (living)
  README.md                 # this file
  constants.nim             # local copies of BitWorld constants (phase 0)
  types.nim                 # Bot, Belief, Directive, ActionIntent, ModeName
  tuning.nim                # cross-cutting tunable knobs
  bot.nim                   # initBot, decideNextMask, pipeline
  belief.nim                # initBelief, updateBelief
  navigation.nim            # hierarchical waypoint navigation (strategic + tactical)
  perception.nim            # phase-1 perception orchestrator
  perception/
    data.nim                # phase 1.1 — palette, sprites, map, font (baked);
                            #   TaskStation.passableCX/CY precomputed here
    frame.nim               # phase 1.0 — bit unpack + pixel helpers
    interstitial.nim        # phase 1.0 — black-pixel screen detector
    ignore.nim              # phase 1.0 — dynamic-pixel ignore mask
    geometry.nim            # phase 1.2 — camera / world coord math
    localize.nim            # phase 1.2 — camera localization orchestration
    actors.nim              # phase 1.3 — crewmate/body/ghost scan, role, self-colour
    tasks.nim               # phase 1.4 — task-icon scan (mb_scan_task_icons) + radar dots
    ocr.nim                 # phase 1.5 — pixel-font OCR (mb_best_glyph, textMatches, findText)
    voting.nim              # phase 1.6 — voting-screen parse (grid, slots, chat OCR)
    baked/                  # *.bin blobs (regen via tools/bake_assets.sh)
  action.nim                # ActionIntent -> button mask (discipline dispatch,
                            #   waypoint nav, snapToPassable utility)
  mode_registry.nim         # mode lookup + default directive
  reflex.nim                # reflex evaluation (edge-triggered mode switches)
  guidance.nim              # worker-thread + channels (phase 3)
  llm.nim                   # Claude client: AWS Bedrock preferred, direct Anthropic fallback
  snapshot.nim              # belief → JSON snapshot for the LLM (phase 3)
  prompts.nim               # system prompts for gameplay + meeting LLM calls (phase 3)
  trace.nim                 # trace writer (phase 4)
  nim.cfg                   # nimby package paths (curly, jsony, libcurl)
  nimby.lock                # package pins used by build_guided_bot.py in Docker
  coplayer_manifest.json    # BitWorld tournament-runner player manifest
  guided_bot.nim            # CLI entry + library gate
  coworld/
    Dockerfile              # linux/amd64 policy image for public Among Them
    policy_player.py        # /bin/guided_bot BitWorld + Coworld websocket bridge
    README.md               # image build, upload, and runtime notes
  modes/
    idle.nim               task_completing.nim      reporting.nim
    pretending.nim         hunting.nim              fleeing.nim
    alibi_building.nim     meeting.nim
  ffi/lib.nim               # FFI exports (gated by -d:guidedBotLibrary)
  build_guided_bot.py       # on-demand Nim build helper
  tools/
    bake_assets.nim         # regenerate perception/baked/ from upstream bitworld
    bake_assets.sh          # wrapper that wires nim --path: flags
    bake_nav.py             # compute nav_paths.bin from nav_graph.json + walk_mask
    waypoint_editor.py      # GUI tool for waypoint graph editing
  cogames/
    amongthem_policy.py     # cogames MultiAgentPolicy wrapper
    ship.sh                 # legacy Python-bundle dry-run / upload wrapper
    README.md
  test/
    smoke.nim               # phase-0 pipeline smoke test
    perception_test.nim     # phase-1.0 perception fixtures + end-to-end
    data_test.nim           # phase-1.1 baked-asset shape + parity
    localize_test.nim       # phase-1.2 camera-lock pinning + benchmark
    actors_test.nim         # phase-1.3 actor scan, role, self-colour, pipeline
    tasks_test.nim          # phase-1.4 task-icon scan, radar dots, pipeline
    ocr_voting_test.nim     # phase-1.5/1.6 OCR, voting parse, pipeline
    voting_pipeline_test.nim # voting parse -> belief -> meeting action pipeline
    meeting_test.nim        # meeting mode cursor pulses, target choice, self-vote guard
    voting_diag_test.nim    # fixture diagnostics for voting/game-over frames
    fallback_test.nim       # phase-5 fallback-only playability
    navigation_test.nim     # waypoint graph/path loading and action wiring
    guidance_lifecycle_test.nim # guidance wake/reset lifecycle
    mode_params_snapshot_test.nim # LLM mode params + current_mode.summary
    radar_exclusion_test.nim # radar/task exclusion interactions
    test_action_table.py    # Python: BITWORLD_ACTION_MASKS ordering guard
    fixtures/               # raw frame dumps for the fixture tests
```

## Building

Phase 3 requires `curly`, `jsony`, and `libcurl` (via nimby). Package
paths are configured in `nim.cfg` in the guided_bot directory. The Nim
compiler picks this up automatically when building from the repo root
with `--path:among_them/guided_bot`.

```sh
# CLI binary (release mode).
nim c -d:release --threads:on --mm:orc \
    -o:among_them/guided_bot/guided_bot \
    among_them/guided_bot/guided_bot.nim

# Shared library for cogames FFI.
nim c -d:release --opt:speed --app:lib -d:guidedBotLibrary \
    --threads:on --mm:orc \
    -o:among_them/guided_bot/libguidedbot.dylib \
    among_them/guided_bot/guided_bot.nim

# Or let the Python helper handle it on demand.
python3 among_them/guided_bot/build_guided_bot.py
```

## Tests

```sh
# Phase 0 smoke — pipeline shape, ghost override, default directives.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/smoke.nim

# Phase 1.0 — frame unpacking, interstitial detection, ignore mask,
# end-to-end perceive() + updateBelief() against fixture frames.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/perception_test.nim

# Phase 1.1 — palette / sprite / map / font shape, magic-number checks,
# parity pins against guided_bot's baked source data.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/data_test.nim

# Phase 1.2 — camera math, patch index, fixture-pinned camera locks,
# pipeline + reseed flow, smoke
# benchmark.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/localize_test.nim

# Phase 1.3 — actor scan (crewmates, bodies, ghosts), role + self-colour
# detection, ignore-mask actor exclusions, end-to-end bot pipeline,
# fixture sweep, smoke benchmark.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/actors_test.nim

# Phase 1.4 — task-icon scan (mb_scan_task_icons), radar-dot scan,
# imposter skip, ignore-mask task-icon exclusions, end-to-end bot
# pipeline, fixture sweep, smoke benchmark.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/tasks_test.nim

# Phase 1.5/1.6 — font packing, textMatches, bestGlyph, readRun,
# findText, classifyInterstitial, voting grid layout, end-to-end
# pipeline fixture sweep, smoke benchmarks.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/ocr_voting_test.nim

# Voting pipeline — parse voting frames, merge slot/alive/self/cursor
# state into belief, and drive meeting-mode actions from that belief.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/voting_pipeline_test.nim

# Meeting mode — cursor pulse/release navigation, evidence/alibi fallback
# target selection, guarded confirm behavior, chat intent, and self-vote prevention.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/meeting_test.nim

# Phase 5 — fallback-only playability: validation gate (non-NOOP
# within 10 frames), mode transitions, no-crash full sequence,
# default-directive-source invariant.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/fallback_test.nim

# Navigation — baked waypoint graph/path loading, strategic planning,
# reverse edge following, and ActionIntent wiring.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/navigation_test.nim

# Mode params + snapshots — LLM-selected mode params affect behavior and
# current_mode.summary is exported for guidance.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/mode_params_snapshot_test.nim

# Python — action-table ordering guard. Verifies BITWORLD_ACTION_MASKS
# matches the canonical direction×modifier formula that ffi/lib.nim's
# TrainableMasks relies on.
PYTHONPATH=among_them .venv/bin/python -m unittest \
    among_them.guided_bot.test.test_action_table -v

# Live integration test — runs full games against the Nim server with
# fillers, checks traces for correct role detection, mode entry, and
# manifest finalization. Requires server + filler binaries. ~3 minutes.
PYTHONPATH=among_them .venv/bin/python \
    among_them/guided_bot/test/live_test.py --keep-traces
```

Each prints `OK` and exits 0 on success, or `FAIL: <label> ...` lines
plus a non-zero exit on a regression.

## Regenerating baked assets

`perception/baked/*.bin` are deterministic outputs of
`tools/bake_assets.nim` against the upstream bitworld checkout
(`~/coding/bitworld`, override with `BITWORLD_DIR`). The tool is Nim
so it can use the same `bitworld/aseprite` parser the live server
uses to render `skeld2.aseprite` and `tiny5.aseprite` — no Python
aseprite library required, and no risk of a deprecated local snapshot
drifting from upstream.

Re-run when the upstream Among Them assets change:

```sh
among_them/guided_bot/tools/bake_assets.sh
# or override the source dir:
BITWORLD_DIR=/path/to/bitworld among_them/guided_bot/tools/bake_assets.sh
```

Regenerate the navigation path blob after editing the waypoint graph:

```sh
PYTHONPATH=among_them .venv/bin/python \
    among_them/guided_bot/tools/bake_nav.py
```

Edit the waypoint graph interactively:

```sh
PYTHONPATH=among_them .venv/bin/python \
    among_them/guided_bot/tools/waypoint_editor.py
```

Requirements: `nim` + `nimby`-installed `pixie` and `zippy` (already
available on any machine that's built bitworld). The `guided_bot`
runtime binary itself does not depend on either.

Bump `BakeSchemaVersion` in both `tools/bake_assets.nim` and
`perception/data.nim` on any layout change so a stale baked dir
trips the compile-time shape asserts.

## Running

The CLI entry point is primarily for build verification. For actual
gameplay, use the cogames FFI path —
`cogames/amongthem_policy.py` loads the shared library and routes
`step_batch` through it. See `among_them/scripts/play_local.py` for
live matches.

```sh
among_them/guided_bot/guided_bot --port:2000 --name:gb0
```

## Tracing

Structured trace output is opt-in via environment variables or per-instance
kwargs. When enabled, each bot writes JSONL streams and a manifest to a
**unique session subdirectory** under the trace root. Multiple bots sharing
the same `GUIDED_BOT_TRACE_DIR` are safe — a monotonic instance counter
ensures no collisions.

**Convention:** Store traces in `guided_bot/traces/` (gitignored, kept via
`.gitkeep`). Use this as the default `--trace-dir` for local development
and live tests rather than `/tmp`. This keeps trace output colocated with
the agent source for easier post-match analysis.

When disabled (the default), every trace call is a nil-check early return
with near-zero cost.

### Configuration

Two mechanisms control tracing, with a strict precedence rule:

1. **Environment variables:** `GUIDED_BOT_TRACE_DIR`, `GUIDED_BOT_TRACE_LEVEL`
2. **Policy kwargs:** `trace_dir`, `trace_level` (passed via `--policy-kwarg`
   or injected by `play_match.py`'s `--trace-dir`/`--trace-level` flags)

**Kwargs always override env vars.** When `play_match.py` receives
`--trace-dir`, it passes `trace_dir=<dir>/bot_<i>` and
`trace_level=<level>` as per-bot kwargs — so the CLI flags are
authoritative regardless of what env vars are set. The env vars serve
as a fallback for the standalone binary or when no kwargs are passed.

```sh
# Trace levels (from trace.nim):
#   off        — no output
#   events     — manifest.json + events.jsonl
#   decisions  — all of events + decisions/modes/reflexes/guidance/perception.jsonl
#   full       — all of decisions + snapshots.jsonl (every ~240 ticks) + frames.bin

# --- Recommended: use play_match.py CLI flags (authoritative) ---

# Full tracing with frames (4 agents, 3 minutes):
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --num-agents 4 --imposter-count 1 --duration 180 --seed 42 \
    --trace-dir among_them/guided_bot/traces \
    --trace-level full

# Decisions-level tracing (no frames.bin, much smaller output):
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --num-agents 8 --duration 180 --seed 42 \
    --trace-dir among_them/guided_bot/traces \
    --trace-level decisions

# --- Alternative: env vars (for standalone binary or connect.py) ---

GUIDED_BOT_TRACE_DIR=among_them/guided_bot/traces \
GUIDED_BOT_TRACE_LEVEL=full \
PYTHONPATH=among_them .venv/bin/python among_them/scripts/connect.py \
    --host 127.0.0.1 --port 2000

# --- Per-instance override via policy kwarg (wins over everything) ---
#   --policy-kwarg trace_dir=among_them/guided_bot/traces/custom
#   --policy-kwarg trace_level=full
```

**Important:** Setting `GUIDED_BOT_TRACE_LEVEL=full` as an env var has
no effect when using `play_match.py --trace-dir` because the script
injects `trace_level` as a kwarg (defaulting to `decisions` unless
`--trace-level` is explicitly passed). Always use the CLI flag.

### Output directory layout

Each bot invocation creates a unique session subdirectory:

```text
<GUIDED_BOT_TRACE_DIR>/
  2026-05-05T12-30-00-12345-0/    (bot 0, session 0)
    manifest.json
    events.jsonl
    decisions.jsonl
    modes.jsonl
    reflexes.jsonl
    guidance.jsonl
    snapshots.jsonl   (TraceFull only)
    frames.bin        (TraceFull only)
  2026-05-05T12-30-00-12345-1/    (bot 1, session 1)
    ...
```

The session directory name is `<ISO-timestamp>-<pid>-<instance-counter>`.
The `manifest.json` includes a `bot_index` field when the bot was created
with a known index (e.g. via the FFI `guidedbot_new_policy` call).

### Output files

| File | Level | Content |
|---|---|---|
| `manifest.json` | events | Round metadata, schema version, bot_index, role, start/end ticks, outcome |
| `events.jsonl` | events | Game events: body_seen, vent_witnessed, vent_suspected, meeting_started, role_revealed, chat_observed, game_over |
| `decisions.jsonl` | decisions | Per-frame mode, directive source, params, intent, final button mask, self position, localized flag |
| `perception.jsonl` | decisions | Per-frame perception: phase, interstitial flag/kind, black pixels, localization, visible actors, tasks, radar dots, voting parse |
| `modes.jsonl` | decisions | Mode transitions: entered/exited with duration |
| `reflexes.jsonl` | decisions | Reflex firings with trigger details |
| `guidance.jsonl` | decisions | LLM calls: exact snapshot_sent payloads, llm_response, directive_published, llm_call_failed |
| `snapshots.jsonl` | full | Periodic full-belief JSON snapshots (~every 240 ticks) |
| `frames.bin` | full | Raw 128x128 frame bytes for replay |

See DESIGN.md §11 for the exact JSON schemas.

## Submissions

Use [`coworld/README.md`](coworld/README.md) for the current public Among Them
Daily Coworld v2 Docker-image flow from
<https://softmax.com/play_amongthem.md>. The older
[`cogames/README.md`](cogames/README.md) Python-bundle wrapper remains only
for legacy bundle experiments and does not submit to Among Them Daily.

Phase 5 added fallback-only playability: the bot emits non-NOOP actions from
tick 1 on gameplay frames. For the current public image flow, the local smoke
check is the linux/amd64 image build plus `/bin/guided_bot --help`; when
practical, also run `uv run coworld run-episode` against the downloaded
`among_them` Coworld manifest. The hosted runner drives the image through
`COGAMES_ENGINE_WS_URL`.

The `mettagrid.bitworld` import is now optional in `amongthem_policy.py`
(inline fallback constants) so the policy loads in Docker images that
only ship `mettagrid` without the `bitworld` extra.

## Submission log

| Date | Policy name | Season | Validation / upload | Leaderboard |
|---|---|---|---|---|
| 2026-05-01 | jamesboggs-guided-bot-fallback-test | among-them | **blocked**: season 404 | — |
| 2026-05-01 | jamesboggs-guided-bot-dryrun | beta-cvc (fallback) | import fixed, Nim build attempted | — |
| 2026-05-11 | jamesboggs-guided-bot-20260511-115205:v1 | among-them | Docker dry-run built library, connected 8 players, completed 10-step episode; failed only known no-op gate, shipped with `--skip-validation` | pending |
| 2026-05-11 | jamesboggs-guided-bot-coworld-20260511-120701:v1 | none — Coworld image upload for daily website | linux/amd64 Docker build passed; container smoke loaded `AmongThemPolicy` and stepped slot 3; image upload completed via `crane` after Docker 29 ECR `HEAD` failure | website submission pending |
| 2026-05-11 | jamesboggs-guided-bot-coworld-20260511-142920:v1 | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 Docker build passed; smoke verified `/bin/guided_bot` and `(4, 128, 128)` pixel policy env; standard upload hit Docker 29 ECR `HEAD` 403 and completed via `crane` | placed (`lpm_ed695228-4241-4c28-b16c-c9372462b133`); score pending |
| 2026-05-12 | jamesboggs-guided-bot-public-20260512-152010:v1 | legacy `among-them` only | linux/amd64 `docker buildx build --load` passed; `/bin/guided_bot --help` smoke passed; public-guide upload completed via local Coworld uploader plus ECR `put-image` manifest workaround | policy id `de944167-b1ac-40d7-88ea-8c5495896795`; submitted to legacy `competition`, but Coworld v2 showed no Among Them Daily submission for this policy |
| 2026-05-13 | jamesboggs-guided-bot-coworld-20260513-095131:v1 | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 `docker buildx build --load` passed; `/bin/guided_bot --help` smoke passed; `coworld run-episode` against `among_them:0.1.11` completed; standard upload hit Docker 29 ECR `HEAD` 403 and completed via `crane`; image `img_b386faae-79ef-4f9e-81d9-32787588c736` digest `sha256:4fd6d88da39c74186fc8a0d5aef954b32eceeeb5eda1b98a4ffa20d907b16c54`; Bedrock env stored | policy id `cdac788e-8ae0-4b07-81ca-8bd45a84ebad`; submitted as `sub_9414c5e8-1e44-461b-a497-51b59cfa32d5`; placed as active champion `lpm_290240c5-2eea-4648-b479-d428a22e43d2` in `div_334593c6-da90-4651-98c7-606573ea1474` |

## Change log (recent)

**2026-05-05 — Player roster + imposter awareness**

- **`types.nim`:** `PlayerSummary` gained `role: BotRole` and
  `alive: bool` fields. Per-player memory now tracks last-seen
  position, death status (from body sightings), and known role.
- **`belief.nim`:** `mergeActorPercept` now maintains the per-player
  roster: updates `lastSeenTick/X/Y` from visible crewmates (when
  localized) and marks players dead when their body is spotted.
  `initMemoryState` initializes all players as alive with
  `RoleUnknown`.
- **`perception/actors.nim`:** New `scanRoleRevealImposters` —
  detects imposter team colors from the role-reveal interstitial by
  counting per-palette-index pixel occurrences and comparing against
  expected stable-pixel contributions. Handles the palette-14
  collision (visor shares a palette index with PlayerColors[3]) via a
  pixel-count threshold (body tint adds ~40 px vs ~10 px from visor).
- **`bot.nim`:** Role-reveal scan runs on every interstitial frame
  (gated by title-text presence at Y=15-21 + 24-frame stability
  check). On detection, populates `knownImposterColors` and marks
  roster entries. Also fixed OCR cache to not cache
  `InterstitialUnknown`, allowing retry on later frames.
- **`modes/hunting.nim`:** Target selection now filters
  `visibleCrewmates` to exclude colors in `knownImposterColors`
  before computing witness count or selecting targets. Prevents
  imposters from chasing their partner.
- **`trace.nim`:** `writeLine` now flushes after every line so all
  JSONL trace files (events, modes, reflexes, guidance) survive
  unclean shutdown.
- **Result:** In 8-player/2-imposter matches, both imposters
  correctly identify their partner's color during the interstitial
  (t≈30-61) and target only crewmates. Zero false kills on partners.
  All crewmate agents correctly produce no detection.

**2026-05-01 — action-table fix + idle wander + compile-time guard**

- **`ffi/lib.nim`:** `TrainableMasks` reordered to match
  `mettagrid.bitworld.BITWORLD_ACTION_MASKS`. The old ordering
  (direction-first: noop/a/b/up/down/left/right/up+a/...) had 22 of
  27 entries misaligned with the Python-side table (direction+modifier:
  noop/a/b/up/up+a/up+b/down/...). This caused every non-trivial
  action the Nim bot produced to be garbled when sent to the game
  server. Compile-time assertion (`CanonicalMasks` + `static:` block)
  added to prevent future drift.
- **`test/test_action_table.py`:** Python-side guard that verifies
  `BITWORLD_ACTION_MASKS` itself follows the canonical
  direction×modifier formula.
- **`types.nim` / `action.nim` / `tuning.nim` / `modes/idle.nim`:**
  New `DisciplineWander` — raw directional movement without
  localization or waypoint routing. Idle mode now cycles through
  cardinal directions on non-interstitial frames instead of returning
  noop. Helps the localizer see fresh map pixels and passes the
  cogames 10-step gate.
- **`DESIGN.md`:** §6.1 (`DisciplineWander`) and §6.2 (FFI
  action-index contract) added.

## Known gaps / next steps

For forward-looking work, see [`IMPL_PLAN.md`](IMPL_PLAN.md).

### Done (phase 6.1–6.6)

- ~~Task-completion detection~~ → 3-phase hold lifecycle, belief task
  state, radar checkout, tiered selection. Live-verified.
- ~~Reporting give-up~~ → body-visibility check, approach/in-range
  timeouts. Structurally verified (no body encounters in test seeds).
- ~~Meeting cursor~~ → position-aware shortest-path navigation, timer
  fix (600 not 1200), auto-vote delay, edge-triggered cursor pulses,
  self-vote guard, chat emission, and evidence/alibi fallback target
  selection.
  Live-verified in 8-agent/2-imposter matches with full frame traces.
- ~~Hunting cover~~ → station patrol, target memory, kill confirmation,
  **imposter-aware target filtering**. Live-verified in 3-min 8-player
  matches; imposters correctly avoid targeting partners.
- ~~Pretending fake A-press~~ → fake-hold sub-phase during loiter +
  witness swap. See `PRETENDING_DESIGN.md`.
- ~~Fleeing cleanup~~ → post-flee cover navigation + `snapToPassable`
  on flee target. See `FLEEING_DESIGN.md`.

### Live-verification infrastructure (resolved)

The following blockers have been fixed:

- ~~**Role control.**~~ All server-starting scripts now support
  `--force-role {crewmate,imposter}`, which passes the server's
  native `"slots"` config to pin the policy agent's role.
- ~~**Per-agent trace directories.**~~ The trace writer now appends a
  per-instance monotonic counter to session IDs, so multiple writers
  in the same process (e.g. `play_match.py`) get unique session dirs.
- ~~**Body-report button mismatch.**~~ guided_bot uses A for body
  reports, matching the server's `tryReport` trigger.

**Live voting status:** Meeting detection, voting parse, cursor
navigation, alive-slot merging, and vote confirmation are verified
end-to-end from live traces. Chat emission and evidence-based fallback
strategy are implemented. The Bedrock LLM provider is smoke-tested, and
the full LLM chat/vote path is standard-run live validated. Current
meeting votes use hard legality guards and give the LLM structured
incriminating/exculpatory evidence instead of a symbolic evidence veto.

### Remaining implementation (IMPL_PLAN.md)

- **6.7 Reflex scope** — body reflexes only fire from one mode each.
  Trivial.
- **LLM response formatting** — Claude still wraps otherwise valid JSON
  in code fences despite prompt instructions; the parser tolerates it.
- **LLM strategy authority outside meetings** — gameplay modes now consume
  their existing directive params and expose per-mode scratch summaries in
  snapshots. The remaining limitation is strategy quality: the inner loop
  still uses deterministic handlers for tactical movement, timing, and
  safety backstops.

### Lower-priority gaps (carried forward)

- **Localization drops on kill animation.** After the imposter's
  A-press lands a kill, the localizer loses lock for 15+ frames
  (death sprite / blood effect breaks camera-fit scoring). This
  prevents kill confirmation detection and delays post-kill fleeing.
  Kills still land server-side; the bot just can't self-verify.
  See `TODO.md` § "Localization drops on kill animation".
- **Localization reliability.** Spiral fallback fires on lobby frames
  (interstitial detector misses colored non-map content). Pre-game
  frame rejection would eliminate wasted spiral calls.
- **Prompt iteration.** System prompts in `prompts.nim` are starting
  points.
- **CurlPool reuse.** Fresh pool per LLM call; thread-local pool
  would be cleaner.
- **Historical modulabot notes.** Any remaining modulabot-specific
  issues are out of scope for guided_bot unless James explicitly asks.
