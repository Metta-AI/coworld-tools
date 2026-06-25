# guided_bot Implementation Plan

This document has been reset for the Coworld-only runtime.

The previous plan described local server scripts, raw frame capture helpers,
legacy bundle wrappers, and deprecated historical bot paths. Those files have
been removed. Future implementation planning should assume that:

- Coworld is the only supported execution and validation surface.
- Runtime commands should be `uv run coworld ...` from the repo-local UV
  project.
- Meeting LLM control is allowed.
- Gameplay directives from the LLM should stay disabled by default.
- No new local server launcher, hosted-play shim, or legacy bundle path should
  be added.

## Near-Term Plan

1. Validate `uv run coworld play MANIFEST_URI [PLAYER_IMAGES]...` with a real
   guided_bot image. **Done 2026-05-16** — 8-player default-variant run with
   `among-them-guided-bot:vote-slot-map`, crew victory, replay produced.
2. Validate `uv run coworld run-episode MANIFEST_URI [PLAYER_IMAGES]... -o DIR`
   with stderr JSONL tracing. **Done 2026-05-16** — pipeline + stderr trace
   surface confirmed working. See the `run-episode` note below: this command
   is a *smoke test only* and is not a substitute for full-match behavior
   evaluation.
3. ~~Decide explicitly whether the policy remains a Nim-core Coworld image or
   is rewritten as a no-Nim Python policy.~~ **Decided 2026-05-16: keep the
   Nim-core policy image.** See "Policy Direction Decision" below.

## `run-episode` Is A Smoke Test, Not A Behavior Benchmark

The Coworld `run-episode` runner overrides the manifest's `config.json` with a
stripped-down smoke configuration (observed for `among_them` v0.1.20:
`maxTicks=300`, `tasksPerPlayer=1`, `startWaitTicks=0`, `gameOverTicks=1`,
`roleRevealTicks=0`, `voteTimerTicks=120`, and `killCooldownTicks=900` left
unchanged). With a 900-tick kill cooldown in a 300-tick game, imposter kills
are structurally impossible; with one task per player and 300 ticks of game
time, the crew side rarely completes any of them. Almost every `run-episode`
ends in `draw: time limit reached` with all-zero kills regardless of policy
quality.

Use `run-episode` only to confirm:

- the policy image starts and connects to the game server,
- the Coworld websocket adapter exchanges frames and actions without
  protocol errors,
- the stderr JSONL trace surface is reachable in
  `logs/policy_agent_N.txt`,
- `results.json` / `replay.json` / per-agent logs land in `-o DIR`.

Do not use `run-episode` to read behavior, compare policy variants, or judge
strategy. For that, use `uv run coworld play` (full manifest match) or
submit to a league.

## Policy Direction Decision

Decision (2026-05-16): the guided_bot Coworld policy remains a Nim-core image.
The no-Nim Python rewrite is explicitly rejected as a near-term path.

Implications:

- The Nim implementation under `among_them/guided_bot/` (`bot.nim`,
  `belief.nim`, `guidance.nim`, `navigation.nim`, `modes/*.nim`,
  `perception/*.nim`, `snapshot.nim`, `trace.nim`, `types.nim`, `ffi/lib.nim`,
  and so on) remains the production policy core.
- The Python adapter at `among_them/guided_bot/coworld/policy_player.py` and
  `among_them/guided_bot/coworld/amongthem_policy.py` continues to be the
  Coworld-side wrapper around the Nim core. It is not a step toward a no-Nim
  rewrite.
- New behavior work belongs in Nim unless it is intrinsically Python (e.g.
  Bedrock or other LLM client glue, websocket framing, Coworld protocol
  adaptation, trace serialization at the boundary).
- The Nim FFI surface (`ffi/lib.nim`) is the supported integration seam. Do
  not add a parallel Python implementation of any module that already exists
  in Nim.
- Any future meeting-LLM control narrowing (e.g. chat-only) should be
  implemented against the Nim core, not used as an excuse to start migrating
  mode/voting logic to Python.

If the Nim-vs-Python question is revisited later, treat it as a deliberate
proposal with its own design doc and a fresh decision — not as a creeping
migration through individual PRs.

## Documentation Rule

If a future change adds or changes the Coworld run command, update:

- `README.md`
- `guided_bot/README.md`
- `guided_bot/coworld/README.md`
- `guided_bot/coworld/INSPECTING_RESULTS.md`
