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

## What it does

Crewborg plays **both roles** end-to-end. As a crewmate it does tasks, attends
meetings, reports bodies, flees believed imposters, and **votes out the most-likely
imposter** — a **Bayesian suspicion model** (`strategy/suspicion.py`) maintains a
posterior `P(imposter)` per player (a combinatorial prior updated by likelihood
ratios for witnessed kills/vents and graded event-log cues); it flees anyone over a
probability threshold and at meetings votes the highest-`P` player above the vote
bar (else skips), with reporting a visible body taking priority over fleeing. As an
imposter the
role-aware selector runs a priority order during `Playing`: **Report Body**
(self-report any body in view — fire the inevitable meeting + kill-cooldown reset at
once, denying the crew the task-time a body would buy while unfound), **Hunt** (kill
ready *and* a victim trackable → commit to the most-isolated crewmate, stalk it via a
trajectory-led intercept, and strike when in range and unwitnessed), and
**Pretend** (the default — a small FSM that follows a crewmate, fakes a task when it
tails one into a room, and searches likely crew occupancy during the kill lead
window when none are trackable, falling back to room wandering otherwise, never idling);
meetings reuse **Attend Meeting**. Hunt is gated on an actual *kill opportunity*
(shared with the selector) whose isolation bar relaxes with urgency, not merely on
the cooldown ending. The action layer covers `kill` (edge-A in KillRange) and `vent`
(level-B in VentRange). The LLM strategy
seam (`design.md` §10) remains in place but unused.

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
  modes/             idle/normal/attend_meeting/report_body/flee + hunt/pretend (+ imposter_common helpers)
  strategy/          rule_based.py: mode selector + suspicion.py: Bayesian P(imposter) → believed_imposters + event_log.py: per-player observation log + occupancy.py: perception-tape predicates + opportunity.py: victim/witness logic + trajectory.py: intercept prediction
  perception/        Sprite-v1 decoder (decoder/tables) + resolution (resolve/entities)
  map/               vendored croatoan.resources + ported parser/bake (§6)
  coworld/           policy_player.py (bridge), scene.py, Dockerfile, entrypoint.sh
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

Crewborg traces its reasoning to stderr as JSON lines (per-player event log,
suspicion posteriors, occupancy seek targets, a ranked `suspicion_snapshot` at
every meeting, …; see `design.md` §11). Set `CREWBORG_TRACE=debug` for the heavy
per-tick dump of the full `P(imposter)` vector and occupancy snapshot — useful
when debugging why a vote, flee, or pre-kill search did (not) happen.

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
