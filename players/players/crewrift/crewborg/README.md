# Crewborg

A [Player-SDK](../../player_sdk/) agent that plays **Crewrift**, a Coworld
social-deduction game (Among Us–style). Crewborg plugs Crewrift-specific
perception, belief, modes, and strategy into the SDK's two-loop runtime and ships
as a Docker image the Coworld runner launches.

- **Design spec:** [`design.md`](./design.md) — the settled architecture.
- **Orientation:** [`AGENTS.md`](./AGENTS.md) — codebases, protocol, source pointers.
- **Design docs:** [`docs/designs/`](./docs/designs/) — living deep-dives, e.g.
  [`suspicion.md`](./docs/designs/suspicion.md) (the Bayesian model + likelihood-ratio
  table + how we learn/improve the weights) and
  [`agent-tracking.md`](./docs/designs/agent-tracking.md) (probabilistic location
  tracking for imposter search).
- **Benchmark workflow:** [`docs/experience-request-benchmark-analysis.md`](./docs/experience-request-benchmark-analysis.md)
  captures the Observatory experience-request process used to run and analyze
  hosted Crewrift policy matchups.

## What it does

Crewborg plays **both roles** end-to-end. As a crewmate it does tasks, attends
meetings, reports bodies, flees believed imposters, and **votes out the most-likely
imposter** — a **Bayesian suspicion model** (`strategy/suspicion.py`) maintains a
posterior `P(imposter)` per player (a combinatorial prior updated by likelihood
ratios for witnessed kills/vents and graded event-log cues); it flees anyone over a
probability threshold and at meetings votes the highest-`P` player above the vote
bar (else skips), with reporting a visible body taking priority over fleeing. As an
imposter the
role-aware selector runs a priority order during `Playing`: **Evade** immediately
after its own kill (vent if possible, else move away from the body), **Report Body**
for non-fresh visible bodies, **Hunt** (kill ready *and* a victim visible → commit
to the most-isolated visible crewmate, close via a trajectory-led intercept, and
strike when in range and unwitnessed),
**Search** (within the kill lead window, walk ranked occupancy hot spots until a
victim is visible, then follow that target), and **Pretend** (the default — pick a
real task station in the highest-scoring occupancy room, penalizing rooms another
imposter is likely occupying, then fake the task for one task duration). Meetings
reuse **Attend Meeting**. With `CREWBORG_LLM_MEETINGS=1` and `ANTHROPIC_API_KEY`,
Attend Meeting uses a fast Haiku-class LLM call on the meeting fast path to chat,
respond to other players, keep a tentative vote, and submit early when requested;
otherwise it preserves the deterministic canned-chat + suspicion-vote fallback.
Hunt is gated on a visible kill opportunity whose isolation bar relaxes with
urgency, not merely on the cooldown ending. The action layer covers `kill` (edge-A
in KillRange) and `vent` (level-B in VentRange).

## Layout

```
crewborg/
  __init__.py        build_runtime(): assemble the AgentRuntime + bake the map
  agent_tracking.py  reachability-disc location beliefs + coarse occupancy grid search
  types.py           the six SDK types + perceive/update_belief + phase machine
  action.py          action layer: stateful resolve_action + movement/edge FSMs
  nav.py             baked nav graph: pixel-validated A* + reachability + anchors + vent-teleport routing
  trace.py           stderr-JSON trace & metrics sinks
  events.py          CrewborgEventTracer: on_step_complete hook → domain.* events
  modes/             idle/normal/attend_meeting/report_body/flee + evade/pretend/search/hunt (+ imposter_common helpers)
  strategy/          rule_based.py: mode selector + suspicion.py: Bayesian P(imposter) → believed_imposters + event_log.py: per-player observation log + occupancy.py: perception-tape predicates + opportunity.py: victim/witness logic + trajectory.py: intercept prediction
  perception/        Sprite-v1 decoder (decoder/tables) + resolution (resolve/entities)
  map/               vendored croatoan.resources + ported parser/bake (§6)
  coworld/           policy_player.py (bridge), scene.py, Dockerfile, entrypoint.sh
  viewer/            browser trace replay UI for agent-perspective forensics
  scripts/play_local.sh      run crewborg against a local Crewrift server
  scripts/fetch_episodes.py  download full data for the N most recent hosted episodes
  build.sh
  tests/
```

## Develop

From the workspace root (`~/coding/players_checkouts/players`):

```sh
uv sync --extra test
uv run pytest players/crewrift/crewborg/tests
uv run ruff check players/crewrift/crewborg
```

## Run locally

Start a Crewrift dev server (see `AGENTS.md` §"Connecting / running locally"),
then:

```sh
players/crewrift/crewborg/scripts/play_local.sh
```

`COGAMES_ENGINE_WS_URL` defaults to `ws://localhost:2000/player?slot=0&token=`;
override it to point elsewhere.

Set `CREWBORG_BE_DUMB=1` (or `BE_DUMB=1`) for the aggressive imposter experiment:
during `Playing`, imposters skip Pretend/Evade/body reports and stay in Search
unless kill-ready with a visible victim, then Hunt.

Crewborg traces its reasoning to stderr as JSON lines (per-player event log,
suspicion posteriors, occupancy seek targets, a ranked `suspicion_snapshot` at
every meeting, meeting LLM context/decisions when enabled, …; see `design.md`
§11). Set `CREWBORG_TRACE=viewer` for the per-tick replay view model consumed by
the browser UI, or `CREWBORG_TRACE=debug` for the viewer frames plus the heavier
suspicion / kill / occupancy debug dump. Set `CREWBORG_LLM_TRACE_RAW=1` (or
`CREWBORG_TRACE=debug`) to include raw LLM request/response text.

## View trace replays

Open [`viewer/index.html`](./viewer/index.html) in a browser and load a
`logs/crewborg_slot{N}_v{V}.log` file from `scripts/fetch_episodes.sh`, or any
local stderr trace captured from `scripts/play_local.sh`. Logs generated with
`CREWBORG_TRACE=viewer` or `CREWBORG_TRACE=debug` include:

- `domain.viewer_map`: static rooms, task stations, vents, button, and home.
- `domain.viewer_occupancy_grid`: the reachable coarse grid used by the tracker.
- `domain.viewer_frame`: one per tick, with active mode + directive params,
  current intent, self/camera, nav route and target, roster/body beliefs, task
  state, and the live occupancy belief grid.

The viewer can still load older lean logs, but without `domain.viewer_frame` it
falls back to a sparse event timeline and cannot draw full map-space belief
overlays.

## Fetch hosted episode data

Download the full data for the most recent episodes crewborg played in the
hosted Crewrift league (auth via `softmax login`):

```sh
players/crewrift/crewborg/scripts/fetch_episodes.sh -n 10
players/crewrift/crewborg/scripts/fetch_episodes.sh -n 5 --version 2 --out /tmp/eps
```

Writes one directory per episode (default `episode_data/`, gitignored) plus an
`index.json` summary. Each episode dir holds `episode.json` +
`episode_request.json` (metadata, participants, scores, game_config), the
binary `replay.json` (the whole game — load it with the
[`COGAME_LOAD_REPLAY_URI`](docs/crewrift-replays.md) viewer recipe) and its raw
compressed `replay.json.z`, and `logs/crewborg_slot{N}_v{V}.log` — crewborg's
own per-tick stderr trace for each slot it controlled. The run is idempotent
(`--force` to re-download); see `--help` for `--no-replay` / `--no-logs`.

The official `coworld episodes` / `coworld replays` / `coworld episode-logs`
commands *would* cover similar ground, but as of 2026-06-02 they are **broken
against the live server**: the server renamed its episode-request API
(`/v2/episode-requests*` → `/v2/experience-request*`) and even the latest CLI
(coworld 0.1.13) still calls the old paths, so those commands 404. This script
calls the current routes directly (and reads raw JSON), so it keeps working
across that kind of client/server drift — prefer it. (If you need the official
CLI, check `<api>/observatory/openapi.json` for the live route names first.)

## Build the image

```sh
players/crewrift/crewborg/build.sh            # build + emit manifest snippet
players/crewrift/crewborg/build.sh --no-build # only render manifests
```

The build context is the repo root; the image installs the local `players`
package (no mettagrid/cogames stack needed). **stdout = protocol channel,
stderr = logs/traces.**
