# Cyborg Policy Frameworks — Initial Reports

*Date: 2026-05-18*

This document collects initial reports that review and catalog the cyborg policy frameworks in this repo: the **Cogamer framework**, the **CVC Debugger Robot**, **Cogora** (the LLM-only tournament player that seeded Cogamer), **Coborg** (the reusable inner/outer-loop cyborg framework), and **Cyborg Evolution** (the closed-loop play-analyze-evolve framework). All originate from upstream Metta-AI / Softmax repositories and were collated into `agent-policies` with light renames.

A trailing section — **Authorship & Provenance** — was added on 2026-05-18 after going back to the upstream Metta-AI org and reconstructing the lineage from commit history.

---

## Report 1 — Cogamer framework

### Origin and authorship

- Original repository: `Metta-AI/cogamer` @ `b57f070541cc19872a5ed6b03e962277edbc18ad`. Source layout there was `src/cogamer/cvc/...`; copied into this repo as `src/agent_policies/frameworks/cogamer/`.
- Provenance note (`docs/source-provenance.md:14`): "Copied policy core, PCO code, skills, memory, lifecycle, and relevant docs; API/control-plane code left out." So the upstream cogamer was a larger product (with an API and control plane) and only the agent-shaped subset lives here.
- Author: not recorded in this checkout. The only post-collation contributors visible in `git log` for this subtree are Richard Higgins (added Cogamer decision-log benchmark metrics, the most recent substantive change) and James Boggs (mechanical "make agent-policies importable" rename). The original upstream author lives in `Metta-AI/cogamer`'s history, not here — I can't name them with certainty without going to that repo. Based on the surrounding context (Softmax email domain, "softmax-cli" tooling, the "cogamer" platform concept), it's a Softmax/Metta-AI internal artifact; Richard Higgins is the most likely primary author given he's the only non-trivial contributor I can see, but treat that as inference, not fact.

### Top-level structure

```
src/agent_policies/frameworks/cogamer/
├── cvc/          # the playable CvC policy + Coglet runtime primitives
│   └── agent/    # heuristic engine internals (A*, pressure, roles, ...)
├── pco/          # Proximal Coglet Optimizer — PPO restated as a coglet graph
├── skills/       # 5 Markdown SKILLs: setup, play, evaluate, analyze, improve
├── lifecycle/    # start / wake / tick / sleep / die / message-owner prompts
├── memory/       # memory-load / -save / -wipe + memory.md (session log spec)
└── docs/         # architecture, cvc, strategy, cogames
```

Two things to notice upfront:

1. **Markdown is runtime, not just documentation.** `skills/*.md` and `lifecycle/*.md` are operator-facing slash commands the cogamer process actually runs — the framework treats prompt files as first-class executable artifacts.
2. **The framework is two things bolted together.** A Python policy + asyncio Coglet runtime (`cvc/`, `pco/`) that runs inside the game, and a Markdown-driven self-improvement meta-loop (`skills/`, `lifecycle/`, `memory/`) that runs outside the game and edits the Python.

### Components

#### Runtime primitives (`cvc/`)

- `coglet.py` — `Coglet`: universal "actor". Two decorators define handlers:
  - `@listen("channel")` — data-plane handler
  - `@enact("command")` — control-plane handler

  Discovered via `__init_subclass__`; sync and async both supported.
- `channel.py` — `ChannelBus` / `ChannelStats`: async pub/sub. Each `subscribe()` gets an independent queue (no message loss for slow consumers, but no replay). Rolling-window stats at 1s/5s/60s/1h/24h plus last-N history per channel.
- `handle.py` — `CogBase` / `CogletHandle` / `Command`: `CogBase` is "a recipe for a Coglet" (class + kwargs + restart policy). `CogletHandle` is the opaque ref a parent COG holds — exposes only `observe()` and `guide()`. Parents never reach into children.
- `runtime.py` — `CogletRuntime`: boots and supervises the tree on asyncio. Handles spawn/shutdown, exponential-backoff restart, ASCII tree visualization, and optional jsonl tracing of transmits and enacts.
- Mixins:
  - `LifeLet` — `on_start` / `on_stop` lifecycle hooks
  - `TickLet` — periodic-tick hooks (a stub here; original wasn't in the source)
  - `ProgLet` — unified program table where each entry has an `executor` field (`"code"`, `"llm"`) and a pluggable `Executor` protocol
- Executors:
  - `CodeExecutor` — calls `program.fn(context)` (sync or async)
  - `LLMExecutor` (`llm_executor.py`) — drives an Anthropic-compatible client through a multi-turn tool-use loop, dispatching tool calls back through the `invoke` callback into other programs
- `trace.py` — jsonl event recorder injected by the runtime when enabled.

#### CvC policy (`cvc/cogamer_policy.py`, `cvc/programs.py`, `cvc/agent/`)

This is the playable agent. The architecture from `docs/architecture.md` and `docs/cvc.md`:

```
CvCPolicy (MultiAgentPolicy)
  └─ StatefulAgentPolicy[CvCAgentState]  ← one per agent, framework-managed
       └─ CvCPolicyImpl (StatefulPolicyImpl)
            ├─ GameState (wraps the CvcEngine)
            ├─ Program table — 31 code programs + 1 LLM program ("analyze")
            └─ LLM brain (periodic Claude calls → resource_bias/role/objective)
```

Programs split into four categories (`programs.py`): **query** (read state), **action** (movement), **decision** (compose queries+actions; includes `step` and `summarize`), and **LLM** (`analyze`). The engine under `cvc/agent/` is conventional decomposed game logic: A* (`pathfinding.py`), pressure budgets (`budgets.py`), targeting/claims (`targeting.py`), per-tick state (`tick_context.py`), decision pipeline (`decisions.py` — 10 composable check functions, first non-None wins), and a `WorldModel` for entity memory.

The hard constraint emphasised everywhere: **agents share zero state**. Each gets its own `GameState`, `WorldModel`, program-table instance. The only inter-agent signal is the game-provided `team_summary`.

#### PCO (`pco/`) — PPO as a coglet graph

`ProximalCogletOptimizer` (`pco/optimizer.py`) orchestrates one PPO-style epoch as a coglet graph:

```
rollout (actor)  →  critic  →  losses[]  →  learner  →  constraints[]
                                                          │
                                            (reject + reason)
                                                          ↓
                                                   retry up to N times
                                                          │
                                                  accepted ↓
                                                   update actor + critic
```

The optimizer spawns `actor` and `critic` as child Coglets (`on_start`), then in `run_epoch` it: (1) guides the actor to run and awaits an experience message, (2) dispatches that into the critic, awaits evaluation, (3) fans the pair out to every `LossCoglet`, collects signal messages, (4) hands the full context to the `LearnerCoglet`, awaits an update patch, (5) sends the patch to every `ConstraintCoglet` for verdicts, and either accepts (apply to both children) or feeds rejection reasons back into the learner for the next attempt. Everything moves through the channel bus — there are no direct function calls between training stages.

#### Skills (`skills/`) — the iterate loop

Five Markdown SKILLs that are slash commands for an LLM operator (run via `softmax-cli`):

| Skill | What it does |
|---|---|
| `cogamer.setup` | install softmax-cli, OAuth login, create/find player, run a 100-step smoke game |
| `cogamer.play` | run one CvC game, write LLM-Python trace to `/tmp/cvc-trace/*.json` |
| `cogamer.evaluate` | multi-episode / multi-seed eval, produce JSON metrics |
| `cogamer.analyze` | from eval + trace, write `cogamer/analysis.md`: weakness, evidence, root cause (with file:line), proposed fix, risk |
| `cogamer.improve` | implement the proposed fix, eval against baseline, submit if improved, revert if regressed, one change per cycle |

Two principles ground this loop: **one weakness per analysis**, **revert on regression**, no exceptions.

#### Lifecycle (`lifecycle/`) and memory (`memory/`)

This is the framework treating the cogamer as a persistent autonomous agent rather than a single-shot script. The lifecycle prompts:

- `start.md` — first boot; wake + dashboard + announce + a "create hook" that prompts the operator to choose archetype / motto / doctrine and writes `cogamer/IDENTITY.md`
- `wake.md` — restore identity, intention, memory, todos; autostart `/loop 30m improve.md` to continuously self-improve
- `tick.md` — every 10 min: heartbeat, check messages, save state, commit, regenerate dashboard
- `sleep.md` — persist memory, commit `cogamer: sleep - <summary>`, push
- `die.md`, `message-owner.md` — termination and owner-comms hooks

Memory format (`memory/memory.md`): `sessions/YYYYMMDD-NNN.md` per-session logs, periodic `summaries/weekly-*.md` rollups, and a running `learnings.md`. Explicit cleanup rules (sessions >2 weeks with a covering summary get deleted; learnings folded into docs get removed).

### How the components interact

- **Inside a game, fast loop (every tick):** game observation → `process_obs()` updates `GameState` and `WorldModel` → `desired_role()` consults pressure budgets and `_llm_resource_bias` → `step()` builds a `TickContext` once → runs the decision pipeline (heal, retreat, unstick, mine, gear, role_dispatch, explore — first non-None wins) → returns an `Action`. All deterministic Python.
- **Inside a game, slow loop (every ~500 steps):** the `summarize` program collects state → `_build_analysis_prompt` makes a structured prompt → `LLMExecutor` (or the simpler periodic LLM call in `cogamer_policy.py`) sends to Claude Sonnet → `_parse_analysis` validates JSON → applies three knobs: `resource_bias` (which element miners prioritize), `role` (override), `objective` (`expand`/`defend`/`economy_bootstrap`, which reshapes pressure budgets). The LLM never picks individual actions — it steers heuristics via soft overrides.
- **Across components (Coglet runtime):** parents communicate with children via `guide(handle, Command(...))` (control plane) and `observe(handle, channel)` (data plane). Coglets transmit on named channels via `ChannelBus`; `runtime.link(src, ch, dest, ch)` is an async pipe that forwards data from one coglet's transmit channel into another's `@listen` handler. PCO is the canonical demo of this — every PPO stage is just a Coglet wired through channels.
- **Outside the game, improvement loop:** an LLM operator runs setup → play → evaluate → analyze → improve (or has it run automatically every 30 min via the wake hook's `/loop`). Each improve cycle is gated on an eval improvement and writes results back into `cogamer/analysis.md` and `memory/sessions/`. Identity and memory persist in the repo across restarts.

### Primary languages

- **Python (asyncio)** — runtime, policy, engine, PCO. Single source of truth for behaviour during a game.
- **Markdown** — the meta-loop. Skills (`SKILL.md`), lifecycle prompts, memory format, design docs. The framework genuinely executes these via `softmax-cli` / Claude Code; they're not commentary.
- **JSON** — LLM I/O contracts (analyze response, trace logs, learnings files), eval output.

### Design philosophy

1. **Two speeds, one table.** Fast deterministic Python + slow LLM advisor live in the same evolvable program table. Either can be modified by the improvement loop.
2. **LLM as strategic advisor, never actuator.** Cost and latency constraints (~2s/call, ~160 calls/game for 8 agents) plus action timeouts make per-tick LLM use untenable. The LLM nudges Python knobs every ~500 steps and Python does the rest.
3. **Agent independence is non-negotiable.** Zero shared state. The doc explicitly says "Sharing causes 0.00 score." Cogamer agents may run in separate processes against different opponents.
4. **Coglets as the universal primitive.** Actor, critic, loss, constraint, optimizer — all the same shape (`Coglet` + mixins) communicating through channels under a supervision tree. Erlang/Akka-flavoured. This is what lets PPO be written as a graph instead of a training loop.
5. **Markdown-driven self-improvement, with hard guardrails.** One change per cycle. Revert on regression. Multi-seed eval (5+) before believing a result. Self-play improvements don't predict freeplay improvements (called out explicitly in `strategy.md`).
6. **The cogamer is a persistent entity.** Identity, intention, memory, todos all live as files; lifecycle prompts (start/wake/tick/sleep) make the agent resumable across reboots, with a heartbeat to a control plane.

### Walkthrough — making an agent

Assume you want a new cogamer named, say, "scissors":

1. **Bootstrap.** Run `/cogamer.setup` to install softmax-cli, OAuth-login, and create the player. Then trigger `start.md`'s create hook to pick archetype, motto, and doctrine — these get written to `cogamer/IDENTITY.md` and inform later LLM prompts and your own reasoning.
2. **Decide your customization surface.** Four options, in increasing depth:
   - **Constants** (`cvc/agent/types.py`): `RETREAT_MARGIN`, `DEPOSIT_THRESHOLD`, etc.
   - **Programs** (`cvc/programs.py`): the 32 program functions and the LLM analyze prompt/parser.
   - **Engine** (`cvc/agent/*.py`): pressure budgets, role logic, A*, targeting, scoring.
   - **Policy stack** (`cvc/cogamer_policy.py`): override `CvCPolicyImpl.step_with_state` or replace pieces wholesale; or write a brand-new `MultiAgentPolicy` against `mettagrid.policy.policy` and reuse only the Coglet primitives.
3. **Establish a baseline.** `/cogamer.evaluate` over `machina_1` across seeds 42–46, record the average score. Without this you can't tell improvement from variance.
4. **Capture a trace.** `/cogamer.play -m machina_1 --save-replay-file /tmp/cvc-replay.json.z` to produce `/tmp/cvc-trace/*.json` showing every LLM prompt, response, and parsed knob.
5. **Diagnose.** `/cogamer.analyze` reads the trace + eval JSON, cross-references against `docs/architecture.md` (the `alpha.0` comparison) and `docs/strategy.md` ("dead ends — don't retry"), and writes `cogamer/analysis.md` pinning a single weakness to a `file:line` root cause.
6. **Iterate.** `/cogamer.improve` makes the one focused change, re-evals across 5 seeds, and either submits (`cogames upload -p class=cvc.cogamer_policy.CvCPolicy -n scissors -f cvc -f setup_policy.py --setup-script setup_policy.py --season beta-cvc`) or reverts. Append the result block to `cogamer/analysis.md`, the session log to `memory/sessions/`, and any insight to `memory/learnings.md`.
7. **Run it autonomously.** Let `wake.md` keep `/loop 30m cogamer.improve` going. The agent will heartbeat every 10 min (`tick.md`), commit and push at sleep, and pick up where it left off on next wake.
8. **Want to train, not just hand-edit?** Use the PCO subpackage: define an actor Coglet that consumes `Command("run")` and emits experience, a critic that consumes experience and emits evaluation, one or more `LossCoglet`s emitting signal, a `LearnerCoglet` emitting update, and `ConstraintCoglet`s emitting verdict. Hand them all to `ProximalCogletOptimizer`, call `run(num_epochs)`, and the channel graph does the rest.

### Things worth flagging

- **The provenance note's "API/control-plane code left out" is load-bearing.** The cogamer "platform" referenced in `start.md`/`wake.md` (heartbeats, control plane, dashboard, message channels) is not in this repo. The lifecycle prompts assume a runtime harness (`softmax-cli`? a separate cogamer platform service?) that isn't shipped here. Anyone trying to actually run the lifecycle here needs to know that.
- **There's vestigial path drift.** Skills reference `cvc_policy.cogamer_policy.CvCPolicy` while docs and code use `cvc.cogamer_policy.CvCPolicy` or `agent_policies.frameworks.cogamer.cvc.cogamer_policy.CvCPolicy`. Post-collation rename hasn't fully reached the `SKILL.md` files — they would break as-is. Worth flagging if anyone tries to actually run `/cogamer.play`.
- **`ticklet.py` is explicitly a stub** ("the original `coglet.ticklet` was not present in the source repo"). Anything depending on tick-based coglets won't work without filling that in.
- **The framework is more interesting as a pattern than as a runnable artifact in this repo.** What's portable is: (a) the `ProgLet` "two-speed program table" idea, (b) the Coglet/channel/supervision model for orchestrating training graphs (PCO), and (c) the Markdown-skill + lifecycle + memory shape for autonomous self-improving agents. Those three ideas are largely independent and reusable separately.

---

## Report 2 — CVC Debugger Robot

This is a concrete cyborg policy (deterministic Python with an optional LLM advisor) targeting Cogs vs Clips in CogsGuard. It is unusual among the cyborg policies in this repo because it ships with a fully-built debugging-and-observability harness — that's the "debugger" in the name.

### Origin and authorship

- Source repo: `Metta-AI/cvc-debugger` @ `8666c607f54ae204893dc43558e3efb51a1c3d40`.
- In this repo:
  - Policy + tests + docs → `src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot/`
  - Container-based iterative-improvement harness → `tools/research/cogsguard/cvc-debugger-policy-optimizer/`
- Provenance note: "Copied robot policy, tests, policy architecture docs, and optimizer container; web UI left out." (`docs/source-provenance.md:18`). One quirk: `robot/dashboard.html` is still here — it's a single-file dashboard served by the embedded FastAPI server, which is what makes the rest of the observability harness usable without the external web UI.
- Author: only James Boggs shows up in this repo's git log for the subtree, and that's the mechanical rename. Upstream authorship lives in `Metta-AI/cvc-debugger` — I can't name it from this checkout alone. The naming, structure, and tooling (OpenRouter via Claude Opus 4.6, OpenCode CLI in the optimizer, AWS Bedrock setup script) look like Softmax internal work.

### Target game

Cogs vs Clips on MettaGrid — 88×88 grid, 10,000 ticks, two teams. Score = `sum_t(junctions_held / max_steps)`. Roles (miner/aligner/scrambler/scout), four resources (carbon/oxygen/germanium/silicon), hearts as the territorial-action currency (7 of each element = 1 heart), 5 discrete actions, all interaction by bumping. Documented in `CVC_GAME.md`.

### Overall structure

```
cvc_debugger_robot/
├── CVC_GAME.md                  # game rules cheat sheet
├── ROBOT_POLICY_ARCHITECTURE.md # 6-step control loop + role draft
├── tests/test_perception.py
└── robot/
    ├── types.py            # Coord, MacroKind, NavStatus, MacroCommand, NavState
    ├── perception.py       # parse_observation() → FrameScan (only reader of obs.tokens)
    ├── memory.py           # SpatialMemory, SelfState, GameClock
    ├── pathfinding.py      # a_star, flood_fill, find_frontier, Navigator
    ├── state.py            # WorldSnapshot + build_snapshot (only reader of memory)
    ├── brain.py            # RobotBrain.decide(snapshot) → MacroCommand (~1280 lines)
    ├── blackbox.py         # ring-buffer tick telemetry
    ├── roster.py           # DraftBoard, TeammateMemory (in-game talk channel)
    ├── policy.py           # RobotAgent control loop + RobotPolicy wrapper
    ├── policy_specs.py     # canonical spec strings
    ├── llm_coordinator.py  # optional per-miner LLM advisor (OpenRouter)
    ├── observability.py    # FastAPI WebSocket hub
    ├── anomaly_detector.py # live anomaly stream (stuck, death spiral, etc.)
    ├── investigator.py     # post-hoc LLM "moment investigator"
    ├── policy_agent.py     # server-side LLM policy editor (with tools)
    ├── launcher.py         # standalone debugger launcher
    ├── game_runner.py      # background runner + multi-seed eval orchestrator
    ├── eval_engine.py      # headless `cogames run --format json` driver
    ├── dashboard.html      # single-file web UI (kept despite the provenance note)
    └── baseline_results.txt # pre/post-Softy regression notes
```

### Components

#### Decision pipeline (one tick)

`policy.py` documents the actual loop as 8 steps (the architecture doc shows 6 — the policy adds LISTEN and DRAFT):

```
PERCEIVE → LISTEN → UPDATE → DRAFT → SNAPSHOT → DECIDE → EXECUTE → RECORD
```

- **PERCEIVE** (`perception.py`): parse the 13×13 egocentric token window into a `FrameScan`. Only file that touches `obs.tokens`.
- **LISTEN** (`roster.py`): pull 140-char talk messages from the `FrameScan` into `TeammateMemory`.
- **UPDATE** (`memory.py`): integrate `FrameScan` into `SpatialMemory` — walls (from token data and movement-failure feedback), open cells, visited cells, territory AOE values, entity staleness.
- **DRAFT** (`roster.py`, ticks 0–14): agents negotiate a role on a shared `DraftBoard`; assignment then locks. Current 8-agent target: 2 miners, 5 aligners, 1 scrambler.
- **SNAPSHOT** (`state.py`): assemble a `WorldSnapshot` from memory + role + teammates. Only file that reads memory.
- **DECIDE** (`brain.py`): `RobotBrain.decide(snapshot)` → `MacroCommand` plus a `pending_talk` string.
- **EXECUTE** (`pathfinding.py`): `Navigator` turns the `MacroCommand` into one of 5 actions via two-pass A* (strict over confirmed-open cells, then optimistic treating unknowns as passable) with stuck detection (≤2 unique positions in last 6 moves → clear path cache, random move).
- **RECORD** (`blackbox.py` + `observability.py`): push to a ring buffer and the WebSocket hub.

#### Brain — role-locked strategies

`brain.py` runs a phase-gated, role-locked strategy with explicit anti-stuck rigging:

- **Miner**: gear up → mine extractor → deposit when any resource ≥ 40 or total cargo high (`_any_resource_at_threshold`) → maybe switch role after enough deposits.
- **Aligner**: gear up → if no heart, hub → if heart, capture nearest neutral/alignable junction → repeat.
- **Scrambler**: same but targets enemy junctions to neutralize them.
- **Emergency overrides** (apply to any role):
  - HP ≤ 5 → CRITICAL → FLEE to friendly territory
  - HP ≤ 15 or HP runway < 5 ticks → HIGH → FLEE
  - Energy ≤ 5 outside friendly territory → HIGH → FLEE
- **Heart capacity curve:** `DEFAULT_HEART_CURVE = [(100, 3), (300, 10)]` — pre-tick-100 capacity is 1, then 3, then 10. An obviously-tunable parameter, called out as a sweep target.
- **Frontier probing:** aligners aim for `CORNER_PROBE_OFFSETS = [(-12,-12), (-12,12), (12,-12), (12,12)]` to discover neutral-zone junctions without wasting 30+ ticks walking to map edges.
- **Anti-congestion:** `congestion_ticks` counter (0–15); at 15 the brain forces an "explore" command. High average congestion = strategy is stuck.

#### Coordination model

- **No shared world state object.** Each agent has its own `SpatialMemory`.
- Coordination is via in-game 140-char talk messages — `pending_talk` set by the brain, parsed by other agents in LISTEN, stored in `TeammateMemory`.
- The `DraftBoard` is shared during ticks 0–14 for role negotiation; after that each agent is fully autonomous.
- The architecture doc mentions a `SharedMap` in `policy.py` that merges spatial memory between teammates after exploration — this is a softer team-mode and a point of nuance vs. the strict "no shared state" rule the Cogamer framework enforces.

#### LLM integration (`llm_coordinator.py`)

Optional and per-agent, not shared:

- Activated by passing `kw.llm_model=anthropic/claude-opus-4.6` to `RobotPolicy`.
- Default mode: each miner agent periodically asks Claude Opus 4.6 (via OpenRouter) whether to switch from mining to capturing/scrambling a junction. Valid actions are constrained to a small set: `{switch_gear, collect_heart, capture_junction, scramble_junction, explore_area}`.
- The coordinator only sees this agent's own `WorldSnapshot` — agent independence preserved.
- Falls back to the deterministic brain when no key/model is configured.

#### Observability harness (the "debugger" part)

This is what distinguishes this policy from the Cogamer-generated ones:

- `observability.py` runs a FastAPI server in a daemon thread. `ObservabilityHub` is a thread-safe ring buffer (300 ticks/agent) wired via `queue.Queue` so the game thread can push without touching the asyncio thread. Enable with `ROBOT_DEBUG=1` or `kw.debug=true`.
- `dashboard.html` is the web UI — single-file HTML/JS that connects to the WebSocket stream. (Despite the provenance "web UI left out", this client lives in the policy folder.)
- `anomaly_detector.py` consumes the tick stream and flags six classes of behavioral anomaly in real time: stuck agents, death spirals, wasted hearts, resource starvation, position oscillation, gearless agents acting.
- `investigator.py` is an LLM-driven postmortem tool — given a tick and optional `agent_id`, it pulls surrounding context from the hub and produces a structured "narrative + root cause + suggested fix" via OpenRouter.
- `policy_agent.py` goes one step further: a server-side LLM with tools that can read and edit policy files and run evals. Conversation state in memory per session.
- `launcher.py` lets you start the debugger first and launch games into the existing hub from the UI; `game_runner.py` adds a queue + multi-seed eval orchestrator; `eval_engine.py` is the headless `cogames run --format json` subprocess driver for rapid iteration.

#### Iterative improvement loop (`tools/research/cogsguard/cvc-debugger-policy-optimizer/`)

Not part of the policy proper, but separated by the collation. It's a containerised loop that drives this policy upward:

- `Dockerfile` (Python 3.12 + AWS CLI + OpenCode CLI + cogames/mettagrid/pufferlib-core).
- `optimize.sh` runs the main loop: target score 75+, regression threshold 2.0, milestones at 40/50/60/75; quick eval seeds 42,500,5000; full eval seeds 42,100,200,300,500,1000,2000,3000,5000,9999. Drives an OpenCode agent through analyze → edit → eval → checkpoint cycles.
- `AGENT_INSTRUCTIONS.md` is the agent's brief, including the explicit "Softy" comparison (a higher-scoring competing policy whose advantages — a `SoftyCoordinator` shared object, frontier-aware junction scoring, dynamic role switching — are listed as transferable ideas to mine).

### How the components interact

```
                              tick N
        ┌─────────────────────────────────────────────────┐
        │                                                 │
  obs.tokens → perception → FrameScan                     │
                       │                                  │
                       ↓                                  │
              roster.LISTEN → TeammateMemory              │
                       │                                  │
                       ↓                                  │
            memory.update(FrameScan)                      │
                       │                                  │
                       ↓                                  │
       (ticks 0–14)  roster.DraftBoard.assign()           │
                       │                                  │
                       ↓                                  │
            state.build_snapshot() → WorldSnapshot ───────┼──→ to_prompt() ──→ LLMCoordinator
                       │                                  │                       │
                       ↓                                  │             (every N ticks, miners)
            brain.decide() → MacroCommand                 │                       │
                  (optionally biased by LLMCoordinator ←──┘                       │
                   suggestion)                                                    │
                       │                                                          │
                       ↓                                                          │
       pathfinding.Navigator.execute() → action                                   │
                       │                                                          │
                       ↓                                                          │
  blackbox.append + observability.push_tick ───→ WebSocket ─→ dashboard.html      │
                                              ├─→ AnomalyDetector ─→ events       │
                                              └─→ Investigator (on demand) ──────┘
```

Two boundaries do a lot of work:

1. **`WorldSnapshot`** — `state.py` is the only reader of memory. Brain, blackbox, LLM coordinator, investigator, and dashboard all consume snapshots and nothing else. `to_dict()` produces JSON; `to_prompt()` produces natural language ("Tick 450/10000 (EARLY). Pos (12, -5). Gear: miner, cargo: 6 carbon. HP 180, Energy 18 ..."). Both LLMs and humans get the same view.
2. **`MacroCommand`** — the brain's only output. Deterministic brain and LLM advisor produce the same type; the Navigator doesn't know which produced it.

### Primary languages

- **Python (asyncio + FastAPI)** — policy, server, anomaly detector, LLM clients, eval harness. The bulk.
- **HTML/JS** — `dashboard.html` (single file).
- **Bash + Docker** — `optimize.sh`, `launch.sh`, `run_local.sh`, `Dockerfile`, `docker-compose.yml` in the optimizer container.
- **Markdown** — `CVC_GAME.md`, `ROBOT_POLICY_ARCHITECTURE.md`, `CONTEXT.md`, `ROBOT_AI_AGENT_DEBUGGING_GUIDE.md`, `AGENT_INSTRUCTIONS.md` (the optimizer's brief). The Markdown is partly documentation and partly prompts for the LLM operators (investigator, policy_agent, optimizer's OpenCode agent).
- **JSON** — tick payloads, eval results, BlackBox records, LLM I/O. The serialization format that ties Python policy and HTML dashboard together.

### Design philosophy

1. **Built from first principles, no policy dependencies.** Own A*, own flood fill, own perception parser, own spatial memory. `CONTEXT.md` is explicit: "It does not depend on any existing policy files in this repo (`awareness.py`, `pathfinder.py`, `macro_actions.py`, etc.)." Predecessor policies existed; this one was a clean-room rewrite.
2. **Hard separation of concerns, enforced by file-level invariants.** "`perception.py` only parses tokens"; "`memory.py` only stores state"; "`state.py` only reads memory"; "`brain.py` only makes decisions". No file reaches into another's internals. Stated import order: types → perception → memory → pathfinding → state → brain/blackbox → policy (no cycles).
3. **Everything is serialisable, everything is inspectable.** `WorldSnapshot.to_dict()` and `WorldSnapshot.to_prompt()` are co-equal exit points. The BlackBox keeps a full per-agent ring buffer. The hub streams every tick over WebSocket. This is what makes the debugger and the LLM investigator possible at all.
4. **Deterministic first, LLM as drop-in.** `RobotBrain.decide(snapshot) → MacroCommand` is the LLM-swap interface. The deterministic brain is the fallback whenever a model isn't configured. The LLM only ever returns a `MacroCommand`; it never picks actions.
5. **Agent independence with negotiated coordination.** Each agent has its own memory; they coordinate via in-game talk plus a draft board for role assignment. The `SharedMap` merger is a softer touch than Cogamer's strict "no shared state" rule — coordination is allowed but only through channels the game already provides.
6. **Robustness rigging is first-class.** Two-pass A* (handles partial map knowledge), stuck detection, congestion counter, emergency overrides, anomaly stream, baseline results file checked into the policy folder. The policy is designed to be regressed against and improved iteratively.
7. **The policy and the optimization process are co-designed.** The optimizer container (in `tools/`) drives this policy's score upward via OpenCode; the observability harness and `AGENT_INSTRUCTIONS.md` are the inputs that loop needs. Even the Softy comparison is encoded — the optimizer is told where to look for ideas.

### Notable things to flag

- **`baseline_results.txt` documents a regression.** Post-Softy upgrades dropped 2000-step avg from 1.87 → 1.66 (-11%) and 10000-step from 4.88 → 3.69 (-24%), even though miner deaths dropped 60–85%. Survival improved, score didn't. That's a real performance gap the optimizer is targeting, and worth being aware of if anyone touches this policy.
- **`ROBOT_POLICY_ARCHITECTURE.md` is partly stale** — it documents the 6-step loop, but `policy.py` runs an 8-step loop with LISTEN and DRAFT inserted. The 8-step version is in `policy.py`'s docstring and in `ROBOT_AI_AGENT_DEBUGGING_GUIDE.md`. Worth reconciling if anyone audits the docs.
- **`AGENT_INSTRUCTIONS.md` references "Softy"** as a competing higher-scoring policy with a shared coordinator. Softy is not in this repo — it's referenced as something to mine for ideas if a snapshot is available. The optimizer expects that snapshot but the policy doesn't depend on it.
- **The "web UI left out" claim is ambiguous.** `dashboard.html` is here and the FastAPI server serves it, so a developer can run the debugger end-to-end inside this repo without the upstream web UI. What's missing is whatever broader UI shell was in the upstream `cvc-debugger` repo (multi-game, persistent storage, auth, etc., presumably).
- **LLM cost surface is large.** Three distinct LLM consumers (live miner coordinator, post-hoc investigator, server-side policy editor) plus the optimizer container's OpenCode agent. Anyone reusing this should expect to wire up OpenRouter/Bedrock credentials and budget for it.

---

## Report 3 — Cogora (Alpha CvC player cog)

Cogora is unusual among the cyborg policies in this repo because it is the **predecessor** to the others. The Cogamer framework explicitly bootstrapped its `PolicyCoglet` from Cogora's LLM player (commit `91652241` in `Metta-AI/coglet`: "copy cogora LLM policy as PolicyCoglet baseline — scoring 1.01 per cog"). The CVC Debugger Robot, in turn, was a clean-room reaction against this same lineage. So Cogora is the seed.

It's also unusual structurally: the upstream `Metta-AI/cogora` repo was originally a **Claude Code MCP plugin** ("Observatory tournament API as MCP tools for Claude Code"), not a policy. The MCP server was the original purpose. The CvC player cog was added later as a passenger — and is the only part that survived into `agent-policies` (the MCP plugin code was left out of the collation).

### Origin and authorship

- Source repo: `Metta-AI/cogora` @ `436d60e52c33382da2547a05cf564918b8a4154d`.
- In this repo: `policies/cyborg/cogamer/cogora/`. The path nests it *under* `cogamer/` because Cogora is treated as a Cogamer ancestor.
- Provenance note (`docs/source-provenance.md:22`): "Copied CVC player cog and SDK code; large cogent session logs left out." The `cogents/alpha/sessions/` self-improvement journal — the actual record of the Alpha cogent's hundreds of iterations — did not come along.
- Author: see Authorship & Provenance section below — short version: the **CvC player cog code is Richard Higgins's** (designed in the metta monorepo as the "code-mode cyborg" architecture, PRs #8846…#8857, 2026-03-08 to 2026-03-13). **David Bloomin copied it into the cogora plugin** on 2026-03-27 and added the cogent memory/lifecycle wrapper. **Claude** (running as the persistent agent "Alpha") wrote 1309 of the 1341 cogora commits — almost all of them policy-iteration sessions ("alpha policy v3: dead-reckoning nav", "v915 avg 1.37, heuristic ceiling ~2-3").

### Target game

Cogs vs Clips on MettaGrid, played through `cogames` CLI against a tournament leaderboard ("Cogara"). Same 88×88 grid, ~10,000 ticks, same role/resource model as the CVC Debugger Robot, but the player here is an **LLM-on-cyborg-baseline** rather than the deterministic robot, and is evaluated in a competitive tournament against other "Cogents" (rivals are other LLM agents running their own player cogs).

### Overall structure

```
policies/cyborg/cogamer/cogora/
├── pyproject.toml          # cogora MCP server package metadata (vestigial — server code not copied)
├── run.sh                  # MCP server launcher (vestigial)
├── setup_policy.py         # tournament-side dependency install (anthropic+openai)
└── src/
    ├── cvc/
    │   ├── setup.sh
    │   ├── setup_policy.py
    │   └── cogent/
    │       ├── main.md     # "You are Alpha, a Cogent living in the Cogara" — the agent's brief
    │       ├── memory.md   # session lifecycle: start/during/end, 5-minute save rule
    │       ├── cogames.md  # game setup, tournament workflow, architecture overview
    │       └── player_cog/         # the cog-cyborg implementation (origin: relh, metta monorepo)
    │           ├── policy/
    │           │   ├── semantic_cog.py            # deterministic heuristic baseline (1388 lines)
    │           │   ├── semantic_cog_v65.py        # frozen v65 snapshot
    │           │   ├── semantic_cog_original.py   # frozen original snapshot
    │           │   ├── pilot_base.py              # LLM-pilot wrapper (PilotAgentPolicy, PilotCyborgPolicy)
    │           │   ├── anthropic_pilot.py         # 53k lines — 22+ Alpha variants + Anthropic policy
    │           │   ├── openai_pilot.py            # OpenAI variant
    │           │   └── helpers/                   # geometry, resources, targeting, types
    │           ├── runtime/
    │           │   ├── pilot.py                   # LivePolicyBundleSession (LLM session loop)
    │           │   ├── pilot_runtime_common.py    # PilotSession, prompt assembly, scratchpad merge
    │           │   ├── execution.py               # compile_policy + sandboxed execute (250ms timeout)
    │           │   ├── artifacts.py               # ArtifactStore (main.py, memory.md, plan.md, traces)
    │           │   ├── anthropic_pilot.py / openai_pilot.py
    │           │   └── models.py                  # ExperienceTraceRecord, ReviewDecisionRecord
    │           ├── memory/                        # MemoryStore + retrieval
    │           ├── providers/                     # Anthropic + OpenAI client wrappers
    │           ├── scratchpad.py                  # keyed scratchpad merge logic
    │           └── secret_utils.py
    └── mettagrid_sdk/      # the SDK the LLM-generated step(sdk) sees
        ├── sdk/            # MettagridSDK, actions, helpers, state, log, types, directives
        ├── runtime/        # observation parsing
        └── games/cogsguard/ # CogsguardSemanticSurface + prompt adapter + scenarios + progress
```

Two upfront notes:

1. **The pyproject.toml is misleading.** It declares the package as `cogora` (an MCP server with entry point `cogora.server:main`), but the `cogora/server/` source was *not* copied. What's actually here is just the CvC player cog and SDK — `cvc.cogent.player_cog.*` and `mettagrid_sdk.*`.
2. **`anthropic_pilot.py` is 53,072 lines with 1,222 class definitions.** It is not normal code — it is a frozen snapshot of every policy variant Alpha generated over hundreds of self-improvement sessions, kept side-by-side as `AlphaV65TrueReplicaAgentPolicy`, `AlphaV65RealignAgentPolicy`, `AlphaStableBoostAgentPolicy`, etc. Read it as a fossil record, not a live module.

### Components

#### Persona / lifecycle layer (Markdown)

Three Markdown files in `src/cvc/cogent/` define who the agent is and how it operates between sessions:

- `main.md` — the agent's brief: "Your name is Alpha, you are a Cogent living in the Cogara. … Your job is to get to the top of the leaderboard for CogsVsClips. … Don't just free-play endlessly — enter the tournament regularly. Don't just upload blindly — free-play first."
- `memory.md` — session-state protocol. **Session start**: `git pull --rebase`, check for crashed session (`data/active-session.txt`), read `data/recent.md` and `data/todos.md`, create `sessions/YYYY-MM-DD-HHMMSS/`. **During session**: append to `activity.log`, **commit and push every 5 minutes** (the 5-minute save rule, explicit bash snippet provided). **Session end**: write `learnings.md` and `summary.md`, set status `completed`, update `todos.md`, prepend to `recent.md`, push.
- `cogames.md` — environment setup, free-play commands, tournament workflow, key game-mechanics cheat sheet, and an explicit "**CRITICAL: No Shared Mutable State Between Agents**" section forbidding shared dicts/sets between `AgentPolicy` instances. Same constraint Cogamer enforces.

These aren't documentation — they're the operator's playbook for the Alpha cogent, intended to be read by Claude Code at the start of every session.

#### Deterministic baseline (`policy/semantic_cog.py`)

`SemanticCogAgentPolicy` (1388 lines) is the heuristic policy: A* pathfinding, target selection, role logic (aligner/scrambler/miner/scout), retreat thresholds, oscillation-unstick (`_OSCILLATION_HISTORY_STEPS = 6`, `_OSCILLATION_UNSTICK_STEPS = 4`), and a `SharedWorldModel` that tracks `KnownEntity`s seen by this single agent. Tuned constants like `_RETREAT_MARGIN = 20`, `_TARGET_SWITCH_THRESHOLD = 3.0`, `_SHARED_JUNCTION_MEMORY_STEPS = 400` are exposed for the LLM to override at runtime. This is the same logical shape that became the Cogamer CvC engine, but here it predates the Coglet runtime.

`MettagridSemanticPolicy` is the `MultiAgentPolicy` wrapper that spawns one `SemanticCogAgentPolicy` per agent. The pilot variants (`AnthropicCyborgPolicy` etc.) replace these with `PilotAgentPolicy` instances.

#### Cyborg / pilot layer (`policy/pilot_base.py`)

`PilotAgentPolicy` (extends `SemanticCogAgentPolicy`) is the cyborg wrapper. It carries a `PilotSession` and overrides `_macro_directive(state)` to ask the LLM what to do at strategic decision points. Internally it maintains:

- A `_RuntimeObservation` ring buffer (`_RUNTIME_OBSERVATION_WINDOW = 12`) of recent `(step, position, subtask, target_position, target_kind, objective, directive_resource_bias, heart)`.
- A set of **stagnation detectors** — oscillation, target fixation, resource-bias mismatch, stagnation, bootstrap stagnation, pressure stagnation — each with its own history window, min-step threshold, and review-cooldown step count (e.g. `_TARGET_FIXATION_REVIEW_COOLDOWN_STEPS = 96`).
- A `_runtime_review_steps` dict throttling LLM reviews per trigger.

When a detector fires, the pilot escalates to the LLM via a `ReviewRequest`. The LLM can respond with directives or — in the more aggressive mode — by rewriting the live policy.

#### Live workspace + sandboxed execution (`runtime/`)

This is the **code-mode cyborg** core, and it is the load-bearing innovation of the whole framework.

- **`runtime/artifacts.py`** — `ArtifactStore` exposes a per-cog workspace with five canonical files: `main.py` (executable `step(sdk)`), `memory.md` (scratchpad), `plan.md` (durable plan), `experience_trace.jsonl` (append-only obs+exec trace), `review_transcript.log` (append-only LLM rewrite transcript).
- **`runtime/execution.py`** — `compile_policy(source)` parses the LLM-written `main.py` with `ast`, then executes it in a sandbox with a restricted builtins map (`_SAFE_BUILTINS`: `abs, all, any, bool, dict, enumerate, …` — no `open`, no `__import__`). Each call to `step(sdk)` runs under a `signal.SIGALRM` deadline (`DEFAULT_POLICY_TIMEOUT_SECONDS = 0.25`). `BoundedPolicyError` / `PolicyExecutionTimeoutError` are first-class.
- **`runtime/pilot_runtime_common.py`** — `PilotSession` orchestrates the loop: at each tick the SDK is built from `MettagridState`, the compiled `step(sdk)` is invoked, the result becomes a `MacroDirective`, the experience trace and review transcript are appended. When stagnation triggers fire the pilot calls into the model with `CodeReviewRequest`, gets back a `CodeReviewResponse` (which can `replace_scratchpad`, `replace_plan`, or supply a new `set_policy` source), validates and re-compiles.
- **`runtime/pilot.py`** — `LivePolicyBundleSession`, thread-safety, retry/validation feedback ("Previous output failed validation: <error>. Ensure set_policy is valid executable Python with correct indentation and a callable step(sdk).").

The contract is small and explicit: the LLM produces a Python function `step(sdk) -> MacroDirective`, never picks individual game actions. The deterministic baseline still handles movement, mining, deposits, retreating, gear acquisition, hearts, alignment, scrambling.

#### MettagridSDK (`src/mettagrid_sdk/`)

The abstraction the LLM-generated `step(sdk)` sees. `MettagridSDK` is a dataclass exposing:

- `state: MettagridState` — current game state (visible entities, self state, step number, team summary)
- `actions: MettagridActions` — what the agent can do at this tick
- `helpers: MettagridHelpers` — utility functions (distance, pathing, target predicates)
- `memory: MemoryView` — keyed memory + scratchpad (`memory.md`)
- `plan: PlanView | None` — durable plan (`plan.md`)
- `log: LogSink` — append `LogRecord`s into the experience trace
- `progress: ProgressSnapshot | None` — game-relative progress signals

`games/cogsguard/` provides the CvC-specific surface: `CogsguardSemanticSurface`, `CogsguardPromptAdapter`, scenarios, constants, learnings. This is the layer that turns raw mettagrid observations into prompt-ready semantic descriptions.

`MemoryRecord` / `EventMemoryRecord` / `PlanMemoryRecord` / `BeliefMemoryRecord` are the typed records the durable memory stores. Retrieval scores combine relevance, recency, importance.

### How the components interact

```
                                    one tick
        ┌──────────────────────────────────────────────────────────────┐
        │                                                              │
   raw obs ──→ mettagrid_sdk parse ─→ MettagridState                   │
                                          │                            │
                                          ↓                            │
                          SemanticCogAgentPolicy.step                  │
                          (deterministic baseline)                     │
                                          │                            │
                              ┌───────────┴───────────┐                │
                              │                       │                │
                       no LLM in path           PilotAgentPolicy       │
                              │                       │                │
                              ↓                       ↓                │
                           Action                 build MettagridSDK   │
                                                      │                │
                                                      ↓                │
                              compile_policy(main.py)  ←─ artifact store
                                                      │     (memory.md,
                                                      ↓      plan.md)
                                          step(sdk) → MacroDirective   │
                                          (LLM-written, ≤250ms,        │
                                           sandboxed builtins)         │
                                                      │                │
                              ┌───────────────────────┤                │
                              │                       │                │
                       MacroDirective       append experience_trace.jsonl
                              │                       │                │
                              ↓                       ↓                │
                  SemanticCogAgentPolicy    stagnation detectors fire? │
                  uses directive to            │       │       │       │
                  bias next decision           │       │       │       │
                              │            oscillation │  target       │
                              ↓                        │  fixation     │
                           Action              ReviewRequest →         │
                                                  Anthropic / OpenAI   │
                                                       │               │
                                                       ↓               │
                                               CodeReviewResponse:     │
                                                replace_scratchpad     │
                                                replace_plan           │
                                                set_policy (new main.py)
                                                       │               │
                                                       ↓               │
                                                append review_transcript
                                                recompile main.py      │
                                                                       │
        ┌──────────────────────────────────────────────────────────────┘
        │
   between sessions  (cogent/main.md, memory.md, cogames.md govern Claude Code)
        ↓
   git pull → read recent.md/todos.md → free-play games → analyze logs →
   edit policy code → cogames upload → check tournament matches →
   write learnings.md + summary.md → git push → terminate session
```

Two seams that absorb a lot of the design weight:

1. **`step(sdk) → MacroDirective`** is the LLM's only output during a game. Same dual-mode pattern as the CVC Debugger Robot (`brain.decide(snapshot) → MacroCommand`) and Cogamer (LLM produces `resource_bias`/`role`/`objective` knobs). Here the LLM can additionally *rewrite the step function itself*, not just return a directive — that is what makes this **code-mode** rather than directive-mode cyborg.
2. **The cogent's git repo as state.** `cogents/alpha/` is the durable identity. Sessions persist as git directories; the agent is resumable across container restarts because all of its memory, plans, todos, and learnings are committed and pushed. The 5-minute save rule is an availability guarantee.

### Primary languages

- **Python** — semantic baseline, pilot framework, MettagridSDK, sandboxed execution. The bulk.
- **Markdown** — the cogent's playbook (`main.md`, `memory.md`, `cogames.md`) and durable plan/scratchpad files (`memory.md`, `plan.md` per session). The LLM both reads and rewrites these.
- **JSON / JSONL** — `experience_trace.jsonl` (per-tick obs+exec records), `review_transcript.log` (LLM I/O), code-review request/response schemas via `pydantic`.
- **Bash** — `setup.sh`, `run.sh`, the in-prompt git-save snippet in `memory.md`.

### Design philosophy

1. **Code-mode cyborg, not directive-mode.** The LLM does not just steer the heuristic with knobs — it writes the `step(sdk)` function that gets executed. This is more expressive than Cogamer's `resource_bias`/`role`/`objective` shape and more expressive than the CVC Debugger's `MacroCommand`. It is also more dangerous, which is why the sandbox (AST, safe builtins, 250ms deadline) is load-bearing.
2. **Deterministic baseline always present.** `SemanticCogAgentPolicy` handles movement, A*, gear, deposits, retreats, alignments, scrambles. The LLM only makes strategic choices (which junction to target, what role to be, what resource to favour). Same "LLM as advisor, never actuator" principle as the other policies, just at a different abstraction level.
3. **Stagnation-driven LLM use.** The LLM is not called every tick. The pilot watches the experience trace for known failure patterns (position oscillation, target fixation, resource-bias mismatch, score stagnation) and only escalates when one fires. Each trigger has its own cooldown. This is what keeps an LLM-on-cyborg policy viable inside a tournament timing budget.
4. **Durable per-cog workspace.** `main.py` + `memory.md` + `plan.md` + `experience_trace.jsonl` + `review_transcript.log` are files on disk. The LLM rewrites them; the runtime reads them. This is the "code-mode cyborg contract" from relh's metta PR #8846.
5. **Persistent agent identity, git as state.** Alpha is a single named cogent with continuous memory across sessions. The repo is the agent's brain. The session lifecycle (`memory.md`) is mandatory and tightly specified — start with `git pull`, save every 5 minutes, end with `learnings.md` + `summary.md` + push.
6. **Agent independence — same hard rule.** `cogames.md` explicitly forbids shared mutable state between agent policy instances. Each agent sees only its own `MettagridState` and the read-only `team_summary.shared_inventory`. Same rule Cogamer enforces.
7. **Tournament-first feedback signal.** The agent's brief explicitly says "tournament signal is more valuable than local testing alone" and "Don't just free-play endlessly". Self-play results are treated as suspect (the same dead end Cogamer's `strategy.md` calls out); tournament matches against other Cogents are the trusted signal.

### Walkthrough — how Alpha actually iterated

The local snapshot is silent on Alpha's history because the session logs were left out. The upstream commit log fills in the picture. A typical Alpha session looked like:

1. **Wake.** `git pull --rebase origin main`. Check `data/active-session.txt`. Read `data/recent.md` and `data/todos.md`. Create `sessions/YYYY-MM-DD-HHMMSS/`, write `activity.log: status=in-progress`. Commit "session start: …". (Each of these is a real commit by `Claude` in the cogora log — e.g. `6b25f40b` "session start: 2026-03-27-035531".)
2. **Free-play.** Run `cogames play -m machina_1 -c 8 -p class=cvc.cogent.player_cog.policy.anthropic_pilot.AlphaCyborgPolicy -r log --autostart > /tmp/cogames/latest.log`. Read `/tmp/cogames/latest.log`, grep `[COG]` lines, extract score and event counts.
3. **Diagnose.** Form a hypothesis ("losing_territory gate shifts to scramblers in 6v2 when it shouldn't"). Edit the relevant `Alpha*AgentPolicy` class in `anthropic_pilot.py` to produce a new variant (e.g. `AlphaV65RealignAgentPolicy`). Commit "v918/v919: fix losing_territory gate — don't shift to scramblers in 6v2".
4. **Validate.** Re-run free-play. Compare scores. If improved, **upload to tournament**: `cogames upload -p "class=cvc.cogent.player_cog.policy.anthropic_pilot.AnthropicCyborgPolicy" -n alpha.N -f src/cvc -f src/mettagrid_sdk --setup-script src/cvc/setup_policy.py --secret-env COGORA_ANTHROPIC_KEY=$COGORA_ANTHROPIC_KEY --skip-validation`.
5. **Wait for tournament results.** `cogames matches`, `cogames matches <id> --logs`, `cogames match-artifacts <id>`. Compare against opponents. Record opponent insights into `learnings.md`.
6. **Iterate.** If the tournament regressed, revert (the commit log is full of "revert post-v84 changes that hurt freeplay (17.02 → 10.19)" patterns from the coglet fork — same operator behaviour).
7. **Sleep.** Write `learnings.md` + `summary.md`, update `todos.md`, prepend to `recent.md`, commit "session complete: 2026-03-31-071539 — v915 avg 1.37, heuristic ceiling ~2-3" — this last line is the literal final commit in cogora (`436d60e5`, the provenance SHA).

This is what produced the 1,222 `AlphaXxxAgentPolicy` classes that now live frozen in `anthropic_pilot.py`. The variants accumulated rather than replaced because Alpha used class extension (`class AlphaV65RealignAgentPolicy(AlphaV65TrueReplicaAgentPolicy):`) as its diffing mechanism — every experiment is preserved as a class, the active one is selected by which `*Policy` wrapper class is registered.

### Things worth flagging

- **The MCP server is not here.** `pyproject.toml`, `run.sh`, and the `cogora-server` entry point are vestigial — the original purpose of the cogora repo (Observatory tournament API as MCP tools for Claude Code) was deliberately not copied. Don't expect `cogora-server` to run.
- **The 53k-line `anthropic_pilot.py` is fossil, not architecture.** It accumulates every Alpha variant rather than replacing. If you reuse this code, prune to `AlphaCogAgentPolicy` / `AlphaCogV2AgentPolicy` (the final lineage) + `AnthropicPilotAgentPolicy` / `AnthropicCyborgPolicy`; the rest is provenance for the variants that didn't pan out.
- **The cogent's session logs are missing.** `cogents/alpha/sessions/`, `recent.md`, `todos.md`, `learnings.md`, weekly summaries — none of this was copied. Without it the agent's biography (which experiments worked, which didn't, what opponent patterns it observed) is not in this repo. It still exists in the upstream `Metta-AI/cogora` repo's git history.
- **The pilot's stagnation thresholds are tightly tuned.** `_OSCILLATION_REVIEW_COOLDOWN_STEPS = 24`, `_TARGET_FIXATION_REVIEW_COOLDOWN_STEPS = 96`, `_STAGNATION_REVIEW_COOLDOWN_STEPS = 192`, etc. These were tuned for the specific cost/latency budget of an Anthropic API call inside a CvC tournament tick. Reuse outside that context will need re-tuning.
- **`mettagrid_sdk` here is a vendored fork.** `cogames.md` notes "The `mettagrid_sdk` package used in `cvc/cogent/player_cog/policy/semantic_cog.py` is not on PyPI." It lives inside this repo, not as a dependency. Some symbols (`MacroDirective`, `ReviewRequest`, `CogsguardSemanticSurface`) may have evolved upstream in metta/mettagrid since the copy.
- **The line between "agent" and "developer" is the most interesting thing here.** The CvC Debugger Robot is a policy a human edits. Cogamer is a policy a human edits with AI assistance. Cogora is a policy *that edits itself*: the LLM rewrites `main.py` at runtime, and a Claude Code agent rewrites the surrounding heuristic class hierarchy between sessions. This is the only one of the three that genuinely closes the self-improvement loop without an external operator in the inner loop.

---

## Report 4 — Coborg (reusable Cyborg framework)

Coborg is different from the other three reports because it is **not a policy targeting a specific game**. It is a generic, game-agnostic Python framework — a *substrate* — for building cyborg-pattern agents. The package name is `coborg`; the framework name in its own documentation is "the Cyborg framework". It is also the youngest of the four (originating PR landed 2026-05-11, one day before the `agent-policies` repo itself was created), and the one with the cleanest authorship trail: a single human author distilling three of his own prior agent projects into a generalized two-loop runtime, with documentation aimed at future human and AI maintainers.

### Origin and authorship

- Source repo: `Metta-AI/metta:cogames-agents` @ `aa1d7c5b48c8548d29632562137e571d738d0650`. The upstream path was `cogames-agents/cyborg/` inside the metta monorepo. Formerly imported as `cogames_agents.cyborg`.
- In this repo: `src/agent_policies/frameworks/coborg/` plus design docs in `docs/metta_cogames_framework/`.
- Provenance note (`docs/source-provenance.md:15` and the post-collation entry): "Former `cogames_agents.cyborg` runtime plus Coborg docs/examples." And, importantly: "2026-05-12: copied uncommitted metta `cogames-agents` cyborg framework updates into `src/agent_policies/frameworks/coborg` and `validation/agent-policies-tests/test_cyborg_framework.py` before deleting metta's copy. These source-preserving updates add shared locked memory snapshots, `ModeDecision`, `AsyncStrategyRunner`, metrics sinks, and priority `ReflexRule` support. They came from the metta worktree rather than from a committed metta revision."
- Author: see Authorship & Provenance section below — short version: this is **James Boggs's framework**. He distilled it from three of his own personal-cog projects (Persephone/Orpheus, Among Them/guided_bot, Bulbacog) and committed it as **metta PR #13018 "Add reusable cyborg agent framework"** on 2026-05-11, then iterated locally before forklifting it into `agent-policies`. The framework's own `README.md` is dated "Generated: 2026-05-11" — the same day as the originating PR — and `SOURCE_REPOS.md` points at the three source projects under `/Users/jamesboggs/coding/`. Co-authored on the PR by GPT-5 Codex.

### Target game

None. Coborg is deliberately game-agnostic: `AgentRuntime` does not know game rules, and game-specific behavior (`perceive`, `update_belief`, modes, reflexes, action resolution) is injected as callables and class registrations. The README's framework reference is generic; the `examples/toy_grid_agent.py` is a four-cell grid where one mode is "move toward target". Two known consumers in this repo are **Bitworld / Among Them** (the `coborg_among_them` flavour) and the Cogamer-line policies — Coborg sits underneath them, not next to them.

### Overall structure

```
src/agent_policies/frameworks/coborg/
├── __init__.py                       # re-exports everything (84 lines, all public surface)
├── types.py                          # Pydantic models: ModeDirective, ModeParams,
│                                     # ModeDecision, SharedMemory, BeliefSnapshot,
│                                     # ActionIntent, ActionCommand, StrategyResult
├── modes.py                          # Mode base + ModeRegistry + DirectiveValidationError
├── runtime.py                        # AgentRuntime + RuntimeContext + ReflexRule
├── strategy.py                       # 4 runners: Synchronous, Threaded, Async, Manual
├── buffers.py                        # OverwriteBuffer (latest-value, newest-wins)
├── trace.py                          # TraceEvent, MetricSample, Null/List/Logging/Wandb sinks
└── docs/metta_cogames_framework/
    ├── README.md                     # 831 lines — the full design doc / framework reference
    ├── PYTHON_FRAMEWORK.md           # 134 lines — quickstart
    ├── SOURCE_REPOS.md               # 26 lines — local paths to the three source projects
    └── examples/toy_grid_agent.py    # minimal runnable example
```

Total Python: 1,269 lines across 7 files (`types.py` 198, `runtime.py` 380, `strategy.py` 280, `modes.py` 117, `trace.py` 152, `buffers.py` 58, `__init__.py` 84). Documentation: another ~990 lines of Markdown plus the toy example.

Three things to notice upfront:

1. **The framework is small.** Under 1,300 lines of code. The conceptual surface in `__init__.py` lists 36 public names, but the substantive runtime fits in `runtime.py` (one class, 380 lines).
2. **Documentation is co-equal to code.** The README is longer than any single Python module and reads as the durable design specification — invariants, anti-patterns, validation strategy, trace schema, open questions. The provenance note explicitly says this version of the framework was generalized for *future agents* to read and use, including LLM-driven agents.
3. **Pydantic is the type discipline.** `ModeDirective`, `ModeParams`, `ModeDecision`, `TraceEvent`, `MetricSample`, `ActionIntent`, `ActionCommand`, `StrategyResult` are all `frozen=True, extra="forbid"` Pydantic models. The directive surface between strategy and runtime is fully validated, and `extra="forbid"` means a typo'd field is a hard error.

### Components

#### Types layer (`types.py`)

The structural vocabulary of the framework. Six load-bearing pieces:

- **`ModeParams`** — Pydantic base. Frozen, extra-forbidden. Game-specific params are subclasses.
- **`EmptyModeParams`** — singleton for parameterless modes.
- **`ModeDirective`** — `{mode, params, source, issued_at_tick, ttl_ticks, reason, metadata}`. The single thing the strategy layer emits. `expired_at(tick)` and `issued(tick)` are the two methods; the directive is otherwise pure data.
- **`SharedMemory[BeliefT, ActionStateT]`** — wraps belief, action_state, and active_directive behind a `threading.RLock`. Exposes `read()` and `write()` as context managers yielding a `SharedMemoryView`. The lock is the only synchronization mechanism between the inner loop and the strategy loop.
- **`BeliefSnapshot`** — frozen envelope `{tick, memory, wake_reason, mode_status, mode_status_reason}`. What strategy code receives. `snapshot.read()` / `snapshot.write()` proxy through to the underlying `SharedMemory`. **Strategy code is given a handle, not a copy** — it acquires the lock briefly to build context, releases it before calling the LLM.
- **`ModeDecision[IntentT]`** — `{intent, status: "running" | "complete" | "stalled", reason, metadata}`. Modes either return an intent directly or wrap it in a `ModeDecision`. The framework provides `ModeDecision.running/complete/stalled` constructors. Completing or stalling triggers a fallback and wakes the strategy with the reason.

`ActionIntent` and `ActionCommand` are generic base shapes for examples; real agents subclass or replace them.

#### Mode layer (`modes.py`)

`Mode[BeliefT, ActionStateT, IntentT]` is the ABC. Each subclass defines:

- `name: ClassVar[str]` — stable directive name.
- `params_type: ClassVar[type[ModeParams]]` — expected params subclass (default `EmptyModeParams`).
- `on_enter(belief, action_state)` — optional lifecycle hook called once when the mode becomes active.
- `on_exit(belief, action_state, next_directive)` — optional cleanup called once before replacement.
- `is_legal(belief) -> bool` — optional legality check; if false, the runtime falls back to the default directive.
- `decide(belief, action_state) -> IntentT | ModeDecision[IntentT]` — the only required method.

`Mode.matches_directive(directive)` is the diff mechanism: a directive matches the live mode iff `directive.mode == self.name and directive.params == self.params`. This means reaffirming the same directive does **not** re-instantiate the mode (mode scratch survives); changing either `mode` or `params` triggers `on_exit` + `on_enter`.

`ModeRegistry` validates that a directive names a known mode and carries the right params type, then instantiates it. Validation errors are returned as strings (so the runtime can trace the rejection) or raised as `DirectiveValidationError`.

#### Runtime (`runtime.py`)

`AgentRuntime` is the inner-loop orchestrator. The `step(observation)` loop is annotated as:

```
tick += 1
percept = perceive(observation, tick)
update_belief(belief, percept)         ← inside shared_memory.write()
observe_strategy()                     ← non-blocking; submits BeliefSnapshot to strategy runner
consume_strategy_result()              ← non-blocking; polls latest StrategyResult
run_reflexes()                         ← priority-ordered; first one to return a directive wins
reconcile_fallbacks()                  ← TTL expiry + is_legal() check → install default_directive
decision = active_mode.decide(belief, action_state)
intent = decision.intent
command = resolve_action(intent, belief, action_state)
handle_mode_status(decision)           ← if complete/stalled: trace, fallback, wake strategy
return command
```

Five things the runtime enforces:

1. **Single owner of mutation.** The entire `step()` body runs under `shared_memory.write()`. The strategy loop only reads through the snapshot and writes back through the runner; the inner loop owns live mutation.
2. **Non-blocking strategy.** `_consume_strategy_result()` polls the runner; there is no blocking wait. If the strategy hasn't produced a directive yet, the runtime continues with the current mode.
3. **Validate before installing.** Every directive (from strategy or reflex) goes through `mode_registry.validation_error()`. Rejects trace as `directive_rejected` with the validation message; do not install.
4. **Reaffirm vs replace.** `install_directive()` checks `active_mode.matches_directive()`. Reaffirmed directives just update the active-directive metadata; replacements trigger the full `on_exit` → `mode_registry.create()` → `on_enter` lifecycle.
5. **Fallback paths are first-class.** TTL expiry (`directive.expired_at(tick)`), mode illegality (`active_mode.is_legal(belief) == False`), and mode-status completion/stalling all install the default directive and trace the reason. Default directive can be a constant `ModeDirective` or a function `belief -> ModeDirective`.

`Reflex` is a callable receiving a `RuntimeContext(tick, belief, action_state, active_directive, active_mode_name)` and returning an optional `ModeDirective`. `ReflexRule(name, priority, callback)` orders them — higher priority first, ties broken by registration order. The first reflex to return a directive that validates wins; the runtime traces every check, the winner, and which lower-priority rules were skipped.

#### Strategy layer (`strategy.py`)

Four `StrategyRunner` implementations, all conforming to the same protocol (`observe(snapshot)` / `poll() -> StrategyResult | None` / `close()`):

| Runner | When to use | Threading model |
|---|---|---|
| `SynchronousStrategyRunner(strategy, cadence_ticks=N)` | Deterministic strategies, tests, simple rule-based agents. | Inline on the inner-loop thread; cadence-limited (evaluates every Nth tick at most). |
| `ThreadedStrategyRunner(strategy)` | Blocking LLM clients, expensive deterministic reasoning. | Background `threading.Thread`. Snapshots flow in via `OverwriteBuffer` (newest-wins); results out via `OverwriteBuffer`. |
| `AsyncStrategyRunner(strategy, loop=None, cadence_ticks=N)` | Async LLM clients (async-first SDKs). | `asyncio.create_task` on a caller-provided event loop. Newest-snapshot semantics: each completed task immediately starts the next with the latest available snapshot. |
| `ManualStrategyRunner()` | Tests; harnesses that publish directives by hand. | None — caller calls `publish(result)` to enqueue. |

The two async/threaded runners use `OverwriteBuffer[T]` (`buffers.py`, 58 lines): `publish()` replaces any unread value, `take()` is non-blocking, `wait_take(timeout)` blocks up to a timeout. The semantics are deliberately "latest wins, drop stale" — the README and code comments both call out that a stale strategic directive is worse than no directive.

Strategy.decide can return any of: a `StrategyResult` (directive + inferences), a bare `ModeDirective` (normalized via `normalize_strategy_result`), or `None` (no decision this round). `StrategyResult.inferences` is a free-form dict that the runtime hands to an optional `apply_inferences(belief, inferences)` callback — this is the framework's escape hatch for strategy-written facts (the README recommends a separate inference namespace rather than mutating belief directly).

#### Tracing & metrics (`trace.py`)

`TraceEvent(tick, name, data)` plus `MetricSample(kind, name, value, tags)` are the two emission types. Five trace sinks and four metric sinks:

- Trace: `NullTraceSink`, `ListTraceSink` (test), `LoggingTraceSink` (stdlib `logging` with structured extra), and the protocol surface for custom sinks.
- Metrics: `NullMetricsSink`, `ListMetricsSink` (test), `LoggingMetricsSink`, `WandbMetricsSink` (W&B run adapter, no `wandb` dep — duck-typed on `.log()`).

The runtime emits sixteen distinct event names: `perception`, `belief_updated`, `snapshot_submitted`, `strategy_evaluated`, `strategy_inferences`, `directive_rejected`, `directive_reaffirmed`, `mode_entered`, `mode_exited`, `mode_completed`, `mode_stalled`, `reflex_evaluated`, `reflex_fired`, `fallback_activated`, `action_intent`, `act_command`. Plus six metric series: `cyborg.step.latency_ms`, `cyborg.strategy.observe_ms`, `cyborg.strategy.decide_ms`, `cyborg.strategy.observed`/`.result`, `cyborg.mode.ran`/`.status`/`.duration_ticks`, `cyborg.directive.age_ticks`, `cyborg.fallback`, `cyborg.reflex.fired`.

The README's stated criterion for the trace surface: "These traces and metrics should let a developer answer whether bad behavior came from perception, belief update, strategy, mode logic, action lowering, or slow outer-loop reasoning." Each event name maps to one of those boundaries.

### How the components interact

```
                                    one tick
        ┌──────────────────────────────────────────────────────────────┐
        │                                                              │
   observation ──→ perceive(obs, tick) ──→ percept                     │
                                                │                      │
                                                ↓                      │
                              ┌─────── shared_memory.write() ──────┐   │
                              │                                    │   │
                              │  update_belief(belief, percept)    │   │
                              │                                    │   │
                              │  ┌─→ observe_strategy() ─→ snapshot │  │
                              │  │                          │       │  │
                              │  │                          ↓       │  │
                              │  │                  StrategyRunner  │  │
                              │  │                 (sync/threaded/  │  │
                              │  │                  async/manual)   │  │
                              │  │                          │       │  │
                              │  ↑                          ↓       │  │
                              │  │              Strategy.decide()   │  │
                              │  │              (Python rules, LLM, │  │
                              │  │               or hybrid)         │  │
                              │  │                          │       │  │
                              │  │                          ↓       │  │
                              │  └── poll() ←── OverwriteBuffer ────┘  │
                              │       │                                │
                              │       ↓                                │
                              │  apply_inferences(belief, ...)         │
                              │       │                                │
                              │       ↓                                │
                              │  install_directive(...) → ModeRegistry │
                              │       validates; reaffirm OR           │
                              │       on_exit + create + on_enter      │
                              │       │                                │
                              │       ↓                                │
                              │  run_reflexes() (priority order)       │
                              │       │                                │
                              │       ↓                                │
                              │  reconcile_fallbacks() (TTL, is_legal) │
                              │       │                                │
                              │       ↓                                │
                              │  active_mode.decide(...) → intent      │
                              │       │     or ModeDecision            │
                              │       ↓                                │
                              │  resolve_action(intent, ...) → command │
                              │       │                                │
                              │       ↓                                │
                              │  handle_mode_status(decision)          │
                              │       (if complete/stalled: fallback   │
                              │        + wake strategy)                │
                              └────────┬───────────────────────────────┘
                                       │
                                       ↓
                                    command
```

Three seams carry most of the design weight:

1. **`BeliefSnapshot`** — the strategy interface. Strategy code only ever sees this. `snapshot.read()` gives it a `SharedMemoryView` under lock; it builds prompt context, releases the lock, calls the LLM. **The shared-memory lock is never held across a model call** (this is stated as a design rule in both `README.md` and `PYTHON_FRAMEWORK.md`).
2. **`ModeDirective`** — the strategy output. Validated by `ModeRegistry` before install, frozen Pydantic, hard `extra="forbid"`. The strategy cannot smuggle raw actions; it can only name a mode that the registry knows about, with params that match the mode's `params_type`.
3. **`OverwriteBuffer`** — the dropping semantics. Strategy runners post latest results into a single-slot buffer; the runtime polls and consumes; un-consumed older values are silently discarded. This is what keeps a slow LLM from producing stale directives that fire after the game phase has changed.

### Primary languages

- **Python (typed, Pydantic, asyncio + threading)** — the entire framework. `from __future__ import annotations`, `Generic`/`TypeVar` everywhere, Pydantic v2 (`ConfigDict(extra="forbid", frozen=True)`), `Protocol` for sink and strategy contracts.
- **Markdown** — the durable design layer. The README is structured as a framework reference, not as marketing prose.

No other languages — Coborg is a pure-Python substrate.

### Design philosophy

1. **Two loops, one bridge.** Fast deterministic symbolic inner loop (perception → belief → mode → action) + slow strategy outer loop (snapshot → LLM/rules → directive). The bridge is `ModeDirective` going one way and `BeliefSnapshot` going the other. The README states the rule as: "The outer loop decides what kind of work should be done. The inner loop decides exactly how to do it safely this tick."
2. **The inner loop never waits for the outer loop.** `_consume_strategy_result()` is non-blocking. If the LLM hasn't produced a directive yet, the runtime continues with whatever is current. This is the framework's hardest real-time guarantee.
3. **Typed directives, validated before install.** Pydantic everywhere, `extra="forbid"`, frozen. The directive surface is small enough to validate end-to-end. An LLM cannot smuggle in unknown modes or fields.
4. **Modes own scratch; belief owns truth.** Mode-local planning state stays inside the mode instance. Belief is the durable symbolic model. The README forbids polluting belief with mode scratch — the explicit ownership rule is "Perception owns evidence ingestion. The inner loop owns belief mutation. Modes may write only their own scratch or explicit mode-status facts. The outer loop may write strategic inferences only through a clearly named inference namespace."
5. **Reflexes for urgent overrides.** Priority-ordered, run inside the inner loop, can install a directive without waiting for strategy. This is the safety-critical escape hatch (phase transitions, hazards, deadlines).
6. **TTL + legality + completion as first-class fallbacks.** Directives expire. Modes can become illegal. Modes can complete or stall. All three paths fall back to the default directive and trace the reason. The framework is allergic to silent fallbacks.
7. **Tracing as architecture, not an afterthought.** Sixteen event names and six metric series, designed so that you can answer "where did the bad behavior come from" without re-running the agent. The README's "Trace Schema Recommendations" section reads like a contract.
8. **LLM control is opt-in, schema-driven, and bounded.** README §"LLM Boundary" requires six pieces (context builder, prompt, provider, validator, executor mapping, trace) and explicitly forbids LLM-as-actuator: "Do not let an LLM directly emit per-frame movement buttons, cursor pulses, or transport packets."
9. **The framework is opinionated about anti-patterns.** Listed explicitly: calling an LLM every tick; using LLM output as raw button masks; letting unvalidated JSON construct modes; applying stale directives after phase changes; storing mode scratch in global belief; etc.

### Walkthrough — building a new game agent

The README's "Building A New Game Agent" section is a 12-step protocol. The shape:

1. Define observation and action transport types.
2. Define belief, action state, and percept types.
3. Implement `perceive(observation, tick) -> percept`.
4. Implement `update_belief(belief, percept)`.
5. Implement `idle` mode plus one useful mode (subclass `Mode`, set `name` and `params_type`, implement `decide`).
6. Register modes in a `ModeRegistry`.
7. Implement `resolve_action(intent, belief, action_state) -> command`.
8. Add a default rule-based `Strategy` that emits `ModeDirective`s.
9. Add traces at every boundary (via the trace sink).
10. Add reflexes and a `default_directive` for urgent state changes.
11. Add structured snapshot builders and validators for future LLM use.
12. **Enable LLM strategy only after deterministic replay and trace review.**

Step 12 is the philosophical claim of the framework: get the deterministic version right before introducing model-based control, and treat the trace as the contract that lets you do so.

The `examples/toy_grid_agent.py` is a minimal demonstration: `IdleMode` and `MoveToMode` on a 1-D position grid, with a `SynchronousStrategyRunner` running a deterministic strategy. The agent shape in 80-odd lines.

The two known game-specific consumers in this repo are **Bitworld / Among Them** (`src/agent_policies/policies/cyborg/bitworld/coborg_among_them/`) and **Cogamer's CvC policy line** — Coborg sits underneath both. Among Them is the natural fit because the framework's design language ("meeting mode", "hunt mode", `chat_mentions`, "claim vs trust") in the README is taken straight from social-deduction game vocabulary.

### Things worth flagging

- **The framework is younger than the policies that use it.** Coborg's originating PR (`Metta-AI/metta` #13018) landed 2026-05-11, well after Cogamer (Coglet PR/architecture work, late March 2026), Cogora (mid-March 2026), and CVC Debugger Robot (mid-April 2026). It is a *retroactive* distillation, not the foundation those policies were built on. Treat it as forward-looking infrastructure: this is the substrate the *next* policies are meant to be built on.
- **The local copy is ahead of the metta version.** Per the provenance doc's 2026-05-12 entry, the metta worktree contained uncommitted updates (locked memory snapshots, `ModeDecision`, `AsyncStrategyRunner`, metrics sinks, priority `ReflexRule`) that were copied directly into `agent-policies` without ever being committed upstream. If you compare against `Metta-AI/metta` at `aa1d7c5b` you'll see an older version. The local `coborg/` is the canonical one now.
- **`SOURCE_REPOS.md` points at absolute paths on the original author's machine.** It names `/Users/jamesboggs/coding/personal_cogs/persephone`, `/Users/jamesboggs/coding/personal_cogs/among_them/guided_bot`, and `/Users/jamesboggs/coding/cogames_playground/bulbacog` as the three projects this framework was generalized from. The first two now live inside this repo under `users/james/personal_cogs/`; Bulbacog does not, and the framework specifically calls out that the originally requested path (`cogames_sandbox/bulbacog`) was missing at the time the framework report was written. Anyone trying to trace claims back to source projects should expect Bulbacog to require external archaeology.
- **No game integration tests live with the framework.** `validation/agent-policies-tests/test_cyborg_framework.py` (mentioned in the provenance doc) is the test surface — the framework itself ships only `examples/toy_grid_agent.py` as an executable demonstration. Verification against real games happens in the consuming policies.
- **`WandbMetricsSink` is duck-typed.** It calls `run.log(payload)` and assumes a W&B-like run object. No `import wandb` — you can pass any object with a `.log(dict)` method. Convenient for testing, but means the adapter will silently no-op if the runtime object doesn't conform.
- **The framework is opinionated about LLMs in ways the others are not.** Coborg's README is the only document in this repo that explicitly enumerates legal LLM-use modes (`shadow`, `advisory`, `constrained control`, `full strategy`, `hybrid`) and recommends `hybrid` by default. Cogamer/Cogora/CVC Debugger Robot adopt this pattern implicitly; Coborg writes it down as a contract.

---

## Report 5 — Cyborg Evolution (closed-loop self-improving policy framework)

Cyborg Evolution is the third framework in this repo and the one most explicitly designed for **self-improvement automation**. Where Coborg is a runtime substrate (modes/directives/snapshots, per tick) and Cogamer is a game-specific policy + improvement loop bolted together, Cyborg Evolution is a clean separation: a per-game runtime (BasePolicy / BaseBrain / BaseHarness) connected to an *outer loop that edits its own source code between games* — analysis LLM scores the run, evolution LLM makes surgical `str_replace` edits to `brain.py` and `wiki/*.md`, git commit + PR + auto-merge, score tracker, automatic difficulty escalation when performance plateaus.

It is also the **only multi-game framework** of the three (Cogamer/Coborg are CvC-shaped or game-agnostic-in-theory; Cyborg Evolution ships a `games/new_game/` template and a `Adding a New Game` 9-step protocol).

### Origin and authorship

- Source repo: `Metta-AI/policies` @ `f0c7a851dd60caa2ed586acd4d62ca58cd0c703d`. Archived 2026-04-29 — repo lived for ~30 minutes between creation and archival.
- In this repo: `src/agent_policies/frameworks/cyborg_evolution/` (framework source) plus `tools/research/cursor-skills/` (the Cursor IDE skill bundle that ships with the framework).
- Provenance note (`docs/source-provenance.md:20`): "Copied framework source and Cursor skills."
- Author: see Authorship & Provenance section below — short version: **Aaron Landy (`aaln`) is the sole author**. Four commits, all on 2026-04-29 in a 15-minute window:
  - `f8dc0120` 01:24:56Z "Initial commit: Cyborg Policy Framework"
  - `c35cdd73` 01:34:48Z "Add illustrative diagrams to README"
  - `c9d6164d` 01:39:04Z "Add Cursor skills for cyborg policy framework components"
  - `f0c7a851` 01:39:44Z "Rename skills from cvc-* to cyborg-* for game-agnostic naming" ← the provenance SHA.

  The "rename cvc-* to cyborg-*" final commit is the giveaway: this framework was extracted and generalized from Aaron's earlier CVC Debugger Robot work, with the CvC-specific naming stripped out in the last 40 seconds. The repo was then immediately archived as a single-shot snapshot.

### Target game

None directly. The framework is multi-game by design: `games/new_game/` is a template, and `Adding a New Game` is the framework's instruction set, not a tutorial. There are no game-specific consumers of Cyborg Evolution inside this repo at the moment — the `games/` directory ships only `new_game/` (the template) and no concrete game.

### Overall structure

```
src/agent_policies/frameworks/cyborg_evolution/
├── __init__.py                     # one-line docstring; framework is import-by-module
├── types.py                        # Command, CommandKind, Directive, GameConfig, Coord
├── base_policy.py                  # BasePolicy ABC — perceive → directive → decide → execute
├── base_brain.py                   # BaseBrain ABC — prepare, decide, apply_directive, debug_state
├── base_harness.py                 # LLM daemon thread, directive mailbox, snapshot intake
├── base_triggers.py                # BaseEventDetector — priority-based when-to-consult
├── base_memory.py                  # 3-tier memory: WorkingMemory, EpisodicMemory, StrategicMemory
├── base_evolution.py               # str_replace edit loop, learnings → code, git workflow
├── base_analysis.py                # post-game LLM scoring pipeline (→ *_learnings.json)
├── score_tracker.py                # rolling history, avg, escalation trigger
├── providers.py                    # LLM provider abstraction (Bedrock / OpenRouter / Anthropic)
│
├── wiki/                           # framework-level transferable knowledge
│   ├── mechanics/                  # evolution-loop, memory-tiers, trigger-system
│   ├── skills/                     # frame-parsing, movement, memory-management, llm-integration, role-selection
│   └── strategy/                   # opening, resource-management, adaptation, common-mistakes
│
├── games/                          # per-game plugins (one template, no consumers shipped)
│   └── new_game/
│       ├── brain.py / triggers.py / harness.py / policy.py / game_config.py
│       ├── README.md
│       └── wiki/strategy/{common-mistakes,opening}.md
│
├── scripts/                        # pipeline orchestration
│   ├── continuous_loop.sh          # outer loop template (placeholders for game engine + evolution)
│   ├── record_score.py             # score history + escalation check
│   ├── policy_manager.py           # weekly fork/reset lifecycle
│   ├── reporting_agent.py          # change documentation
│   └── promote_patterns.py         # promote per-game patterns into framework wiki
│
└── docs/
    └── POLICY_GENERATION.md        # the durable architecture + pipeline doc
```

Outside the framework proper, the Cursor skills live at:

```
tools/research/cursor-skills/skills/
├── cyborg-policy/SKILL.md
├── cyborg-brain/SKILL.md
├── cyborg-harness/SKILL.md
├── cyborg-triggers/SKILL.md
├── cyborg-wiki/SKILL.md
├── cyborg-code-evolution/SKILL.md
└── cyborg-post-game/SKILL.md
```

Sizes: ~2,360 lines of Python in framework base + ~290 lines in `new_game` template + ~1,070 lines of pipeline scripts + ~1,170 lines of Markdown wiki + docs. About 2.5× larger than Coborg's code surface, but with comparable doc-to-code ratio.

Three things to notice upfront:

1. **Evolution is in the framework, not bolted on.** `base_evolution.py` (421 lines) is the LLM-driven `str_replace` editor. Cyborg Evolution is the only framework in this repo where automatic source-code editing of policy files is a first-class component, not a side-loop run by a human operator.
2. **The framework has its own wiki.** `wiki/` contains framework-level transferable knowledge (mechanics + skills + strategy). Per-game `wiki/` lives under `games/{game}/wiki/`. Both are read into the LLM prompt; the per-game wiki can be edited by evolution; the framework wiki "graduates" patterns from per-game wikis via `scripts/promote_patterns.py`.
3. **The framework has a lifecycle.** Beyond the per-game tick loop, Cyborg Evolution defines a weekly policy lifecycle: fork (`policy_manager.py fork`) → continuous play (`continuous_loop.sh`) → report (`reporting_agent.py`) → promote (`promote_patterns.py`) → reset (`policy_manager.py reset`). The framework explicitly models the longer-horizon "develop a policy over a week, distill what generalized, restart" loop.

### Components

#### Per-tick runtime (`base_policy.py`, `base_brain.py`, `base_harness.py`, `base_triggers.py`)

The per-game runtime is shaped like Coborg's but with different vocabulary. `BasePolicy.step(raw_observation)` runs:

```
tick += 1
snapshot = perceive(raw_observation); snapshot["tick"] = tick
if harness:
    harness.push_snapshot(snapshot, brain.debug_state())
    directive = harness.read_directive()
    if directive: brain.apply_directive(directive)
    if harness.game_surrendered: return execute(IDLE)
command = brain.decide(snapshot)
return execute(command)
```

The four ABCs:

- **`BasePolicy`** — `perceive`, `execute`, `create_brain`, `create_harness`. Initialization sets up the brain via `prepare(config)` and starts the harness thread.
- **`BaseBrain`** — `prepare(config)`, `decide(snapshot) -> Command`, `apply_directive(Directive)`, `debug_state() -> dict`. Game-agnostic by design — the framework never looks inside the snapshot.
- **`BaseHarness`** — runs as a daemon thread. Receives `(snapshot, brain_state)` via `push_snapshot`, evaluates triggers, builds LLM context, calls the in-game provider, parses the response into a `Directive`, deposits it into a mailbox. The brain polls `read_directive()` next tick.
- **`BaseEventDetector`** — `detect_game_events(prev, curr, memory) -> [(trigger_name, GameEvent)]`. Plus two built-in framework triggers: **Periodic** (priority 10, fires every N ticks as baseline check-in) and **Idle** (priority 20, fires when the agent has been doing the same thing for N ticks).

The trigger system uses a documented **priority schema**:

| Range | Typical use |
|---|---|
| 90–100 | Critical: death, territory lost, imminent threat |
| 70–80 | Important: phase change, key resource available |
| 50–60 | Notable: objective completed, score change |
| 30–40 | Informational: new discovery, deposit |
| 10–20 | Baseline: periodic check-in, idle detection |

Per-trigger debounce prevents rapid re-consultation on the same event type.

The `Directive` type is simpler than Coborg's `ModeDirective`: `{role, command, target, reasoning, params, hold, until, issued_tick, expires_tick}`. It is a dataclass (mutable), not a validated Pydantic model — by design easier for the LLM to produce from a free-form JSON response than Coborg's `extra="forbid"` Pydantic surface.

#### Three-tier memory (`base_memory.py`)

The memory model is one of the framework's most concrete contributions. `GameMemory` contains:

| Tier | Class | Lifetime | Content |
|---|---|---|---|
| 1 | `WorkingMemory` | One tick | `snapshot_dict`, `active_directive`, `recent_commands` (last 5), `nav_target`, `nav_eta`. Replaced via `update_from_snapshot()` every tick. |
| 2 | `EpisodicMemory` | Game (ring buffer max 500) | `{tick, hall, text, landmark, data}` events. Landmarks are protected from eviction; non-landmark events evicted first. |
| 3 | `StrategicMemory` | Game (no eviction; facts can expire or be superseded) | `{key, fact, category, tick_created, tick_expires, superseded_by}`. New facts with the same key supersede old ones, archived to history (audit trail). |

Plus **`PerfWindow[]`** — rolling rate trackers; the game registers windows like `memory.add_perf_window("score_rate", window_size=100)` and the framework computes cumulative-over-window rate-of-change. Plus **`directive_history`** — append-only log of all LLM directives issued.

`GameMemory.dump()` produces a single JSON dict that is the **input to post-game analysis**. The framework's contract: a "narrator" / context builder selects compact slices (last 10–20 episodic events filtered by relevance; active strategic facts in relevant categories; current and peak PerfWindow rates) for the LLM prompt rather than dumping raw memory.

#### Evolution loop (`base_evolution.py`, `base_analysis.py`, `score_tracker.py`, `scripts/`)

This is the framework's distinguishing component. The closed loop:

```
1. PLAY a game (game-specific entry; produces runs/{game}/{game_id}_memory.json)
2. ANALYZE: analysis LLM reads memory dump → {game_id}_learnings.json with schema:
     {score, what_worked[], what_failed[], actionable_rules[],
      biggest_mistake, recommended_next_game_strategy}
3. EVOLVE: evolution LLM receives learnings + editable source files + memory dump
     + cross-game memory; uses str_replace to make 1-3 surgical edits to
     brain.py and wiki/*.md (editable files defined in game_config.py;
     framework infrastructure is never editable)
4. COMMIT + PR: git add → git commit (with game ID and score) → push to
     evolution/{game_id} branch → gh pr create → auto-merge for tracking
5. SCORE + ESCALATE: record_score.py updates history; when last N games
     all score ≥ threshold (default last-5-≥-8/10), step count escalates
     (2500 → 3500 → 4500 → …) creating an automatic curriculum
6. Loop
```

`continuous_loop.sh` (148 lines) is the bash template that drives the outer loop. It is genuinely a template — has explicit `TODO` placeholders for the game-engine run command and the evolution entry point, plus framework-level scaffolding for state persistence (`runs/{game}/score_history.json`), pipelined background post-game work, and pending-step-count handoff.

Two LLM providers are wired (`providers.py`, ~395 lines):

- **In-game provider** — used by `BaseHarness` for real-time strategic consultations. Configured for low-latency, ~512 max tokens.
- **Analysis provider** — used by `base_analysis.py` for post-game review. Typically a stronger model, ~2048 max tokens.

Provider strings support `bedrock`, `bedrock:us.anthropic.claude-sonnet-4-…`, `openrouter`, `openrouter:anthropic/claude-haiku`, `anthropic`.

#### Weekly policy lifecycle (`scripts/policy_manager.py`, `reporting_agent.py`, `promote_patterns.py`)

Beyond the per-game loop the framework defines a longer-horizon process:

```
Week N:
  1. fork    — policy_manager.py fork --game your_game
                creates a fresh fork from the current base
  2. play    — continuous_loop.sh your_game  (runs all week)
  3. report  — reporting_agent.py --game your_game
                produces a change-log of what evolution did this week
  4. promote — promote_patterns.py --game your_game
                lift successful patterns from games/{game}/wiki/
                into the framework-level wiki/ so they apply across games
  5. reset   — policy_manager.py reset --game your_game
                blow away the per-game brain/wiki, keep promoted framework wiki

Week N+1:
  Base branch now includes promoted patterns from week N.
  Fresh fork starts with improved framework wiki but clean game code.
```

This is the framework's answer to a problem the other frameworks don't solve directly: how do per-game discoveries become reusable framework knowledge. Cogamer's `learnings.md` is per-cogent and never graduates; Cogora's wiki is per-cogent ("Alpha's `cogents/alpha/learnings.md`"). Cyborg Evolution makes graduation explicit — `promote_patterns.py` is the lifecycle hook that moves accumulated rules from `games/{game}/wiki/` up into `wiki/` so a new game can start with them.

#### Cursor skills (`tools/research/cursor-skills/skills/cyborg-*/SKILL.md`)

Seven Cursor IDE skill bundles ship with the framework, one per major component:

- `cyborg-policy` — using `BasePolicy` to wire a game engine into the framework.
- `cyborg-brain` — implementing `BaseBrain.decide`.
- `cyborg-harness` — wiring up the LLM consultation thread.
- `cyborg-triggers` — defining `BaseEventDetector` for a new game.
- `cyborg-wiki` — authoring game and framework wiki content.
- `cyborg-code-evolution` — running the str_replace evolution loop.
- `cyborg-post-game` — running the analysis pipeline.

These are the human-operator equivalent of Cogamer's `cogamer.setup` / `cogamer.play` / `cogamer.improve` SKILL files — Markdown skill specs that a Cursor agent reads to drive the framework. They are split out into `tools/research/cursor-skills/` (rather than living with the framework) presumably because Cursor's `.cursor/skills/` layout is editor-specific.

### How the components interact

```
                                     outer loop (continuous_loop.sh)
        ┌────────────────────────────────────────────────────────────────┐
        │                                                                │
        ↓                                                                │
   game runs ──→ BasePolicy.step(obs) one tick:                          │
                  perceive → snapshot                                    │
                  harness.push_snapshot(snapshot, brain.debug_state())   │
                                │                                        │
                                ↓                                        │
                  BaseHarness daemon thread:                             │
                     BaseEventDetector.detect_game_events(prev, curr)    │
                     priority-resolve triggers + debounce                │
                     winner triggers consultation:                       │
                        build context from GameMemory (3-tier)           │
                        + cross_game_memory.json                         │
                        + wiki/ (framework) + games/{game}/wiki/         │
                        → in-game provider (Bedrock / OpenRouter)        │
                        → parse JSON → Directive                         │
                        → mailbox                                        │
                                │                                        │
                                ↓                                        │
                  brain.apply_directive(directive)                       │
                  command = brain.decide(snapshot)                       │
                  execute(command) → game action                         │
                                │                                        │
                                ↓                                        │
   game end ──→ harness.dump_memory() → runs/{game}/{game_id}_memory.json │
                                │                                        │
                                ↓                                        │
                  base_analysis.py:                                      │
                     analysis provider reads memory dump                 │
                     produces {game_id}_learnings.json (score + rules)   │
                                │                                        │
                                ↓                                        │
                  base_evolution.py:                                     │
                     evolution agent gets learnings + editable files +   │
                     memory + cross_game_memory                          │
                     issues 1-3 str_replace edits to brain.py, wiki/*.md │
                     (game_config.editable_files gates this)             │
                                │                                        │
                                ↓                                        │
                  git add → commit (game_id, score) → push               │
                  evolution/{game_id} branch → gh pr create → auto-merge │
                                │                                        │
                                ↓                                        │
                  scripts/record_score.py:                               │
                     append to score_history.json                        │
                     if last 5 games all ≥ 8/10:                         │
                        step_count += 1000 (escalation)                  │
                                │                                        │
                                └──────────────────────────────────────→ back to game runs
```

Across weeks:

```
weekly: fork base → run continuous_loop a week → reporting_agent (changelog)
        → promote_patterns (per-game wiki → framework wiki) → reset
```

Three boundaries do most of the design work:

1. **The `GameMemory.dump()` JSON** is the single hand-off between live runtime and offline analysis. The post-game LLM never sees Python objects — only the dump.
2. **`game_config.editable_files`** is the safety boundary for the evolution loop. The evolution LLM can `str_replace` only files on this list (typically `brain.py`, `wiki/skills/*.md`, `wiki/strategy/*.md`). Infrastructure files — `providers.py`, `base_evolution.py`, the framework itself — are explicitly excluded. This is what makes "an LLM editing its own source code" not catastrophic.
3. **`actionable_rules[]` in `*_learnings.json`** is the structured carrier from analysis to evolution. The analysis prompt is game-specific but the JSON schema is universal, which is why the same evolution agent works across games.

### Primary languages

- **Python** — framework runtime, base classes, evolution loop, analysis, providers. Uses dataclasses (not Pydantic — different style choice from Coborg), `from __future__ import annotations`, `ABC`/`abstractmethod`. ~2,650 lines.
- **Bash** — `continuous_loop.sh` and pipeline orchestration. The outer loop is genuinely bash, not Python.
- **Markdown** — framework wiki + per-game wiki + design doc (`POLICY_GENERATION.md`) + Cursor SKILL files. ~1,400 lines. This is the LLM-readable surface — wiki is loaded into prompts; SKILLs drive the editor.
- **JSON** — `*_memory.json` (per-game state dumps), `*_learnings.json` (analysis output), `cross_game_memory.json` (accumulated patterns), `score_history.json` (escalation state). The serialization format that ties Python and Markdown together.

### Design philosophy

1. **The framework is responsible for the *meta-process*; the game module is responsible for the policy.** Subclass `BasePolicy`, `BaseBrain`, `BaseHarness`, `BaseEventDetector`. Provide `game_config.py`. Everything else — when to consult the LLM, how to write learnings, how to edit code, how to track scores, how to escalate difficulty — is framework property.
2. **Self-improvement is a first-class subsystem.** Cogamer's improvement happens via a Markdown skill that a human operator invokes; Cyborg Evolution's improvement happens via a Python module the framework runs every Nth game. The git commit + PR + auto-merge audit trail is in the framework, not the user's workflow.
3. **Three-tier memory enforces information hygiene.** Working = ephemeral; Episodic = ring buffer with landmarks; Strategic = key-value with supersession + audit. The narrator selects from each tier — the LLM never sees raw dumps. This is more disciplined than the other frameworks' memory models, which tend to be a single `memory.md` scratchpad.
4. **Curriculum is automatic.** No human picks step counts. The framework escalates difficulty when the agent demonstrates stable improvement (last 5 games ≥ 8/10) and never escalates ahead of capability. Anti-pattern: cranking step counts and then failing to learn.
5. **Patterns must graduate to apply across games.** `promote_patterns.py` is the framework's stance on transfer: per-game discoveries stay per-game until something explicitly lifts them into the framework wiki. This prevents over-fitting the framework to one game's quirks.
6. **The evolution LLM has a narrow, audited surface.** `str_replace` only, 1-3 edits per cycle, editable files whitelisted in `game_config.py`, every change committed as its own PR with the game ID and score in the message. Anti-pattern: free-form rewrites of the brain.
7. **Bash, not Python, owns the outer loop.** `continuous_loop.sh` is intentionally a shell script — it survives Python crashes, handles process supervision, runs post-game analysis in the background while the next game starts. The framework treats the outer loop as infrastructure, not application code.

### Walkthrough — adding a new game

The `Adding a New Game` 9-step protocol:

1. `cp -r games/new_game/ games/your_game/`.
2. Implement `brain.py` — your per-tick decision logic (subclass `BaseBrain`, implement `prepare`, `decide`, `apply_directive`, `debug_state`).
3. Implement `triggers.py` — game events that trigger LLM consultation (subclass `BaseEventDetector`).
4. Implement `harness.py` — LLM context building and directive parsing for your game.
5. Implement `policy.py` — bridge to your game engine's observation/action interface (subclass `BasePolicy`, implement `perceive`, `execute`, `create_brain`, `create_harness`).
6. Configure `game_config.py` — editable files list, system prompts, mission text.
7. Add `wiki/` markdown — initial game knowledge for the LLM (`strategy/opening.md`, `strategy/common-mistakes.md` at minimum).
8. Update `continuous_loop.sh` (or a per-game variant) with your game engine's run command.
9. Run: `./scripts/continuous_loop.sh your_game`.

The `new_game/` template ships stubs for all five Python files and two strategy Markdown files. The template is genuinely empty — `new_game/brain.py` is 35 lines of `pass`-bodied methods — so the framework's "fill in the blanks" interface is small.

### Things worth flagging

- **No game is actually wired up.** `games/new_game/` is the only game directory. None of the existing policies in `agent-policies` (CVC Debugger Robot, Cogamer-generated, Cogora, Bitworld Among Them) consume Cyborg Evolution. It is currently *aspirational* infrastructure, available for new games but not load-bearing for any policy in this repo. Aaron created and archived the upstream repo in 30 minutes; nothing has been built on it since.
- **The framework was extracted from CVC Debugger Robot at the last minute.** The fourth and final commit (`f0c7a851` — our snapshot SHA) literally renames everything from `cvc-*` to `cyborg-*`. The Cursor skills, the wiki strategy docs, the new_game template — all originated in CvC-specific form 40 seconds earlier. Reading the framework, you can still see CvC's fingerprints (the strategy docs mention "role selection", "frontier exploration", "resource management" in language tuned to CvC).
- **`continuous_loop.sh` has `TODO` placeholders that exit 1.** Lines 110–114 explicitly say "TODO: Add your game engine run command here" and `exit 1`. The template is genuinely not runnable as-shipped; every consumer must fork the script.
- **The evolution agent's edit history is a real git branch.** Each evolution cycle creates a `evolution/{game_id}` branch and merges it. This means a long-running deployment of Cyborg Evolution would accumulate hundreds of `evolution/*` branches — exactly the pattern visible in `Metta-AI/debugger` (the upstream CVC Debugger repo also has 23+ `evolution/*` branches, which confirms the lineage from Aaron's earlier work).
- **`policy_manager.py fork` and `reset` are real git operations.** The framework manipulates branches as part of its lifecycle. Anyone running this should understand the script will create, push to, and reset branches — not just edit files.
- **Two providers, two budgets.** Anyone reusing this needs Bedrock and/or OpenRouter and/or Anthropic credentials, and should budget for both per-game in-game consultations (smaller, more frequent) and post-game analysis (larger, less frequent). The framework does not enforce per-game budget caps — `base_evolution.py` has a `max_budget_usd` parameter, but enforcement is the caller's responsibility.
- **The three frameworks (Coborg, Cogamer, Cyborg Evolution) overlap but are not unified.** Cogamer has skills + lifecycle + memory; Coborg has modes + runtime; Cyborg Evolution has analysis + evolution + escalation. No one has yet built an agent that combines all three. The "ideal" cyborg agent in this repo would probably use Coborg's mode runtime as the inner loop, Cyborg Evolution's three-tier memory and evolution pipeline as the outer loop, and Cogamer's lifecycle Markdown as the operator interface. That synthesis does not exist yet.

---

## Authorship & Provenance (post-hoc reconstruction, 2026-05-18)

The original reports flagged that authorship could not be determined from `agent-policies` alone — git history was discarded during collation. This section reconstructs it by going back to the Metta-AI org and reading commit history directly. Methodology: `gh api repos/Metta-AI/<repo>/commits/<sha>`, contributor stats, and tracing fork/parent relationships across predecessor repos.

### People

| GitHub | Real name | Email(s) | Affiliation cue |
|---|---|---|---|
| `daveey` | **David Bloomin** | `daveey@gmail.com` | `daveey.github.io`; Softmax/Metta-AI principal (commit pattern across most policy & framework repos) |
| `aaln` | **Aaron Landy** | `aaronlan95@gmail.com` | `implyinfer.com` |
| `relh` | **Richard Higgins** | `richard@relh.net`, `richard@softmax.com` | Softmax (email domain) |
| `JBoggsy` | **James Boggs** | `jmsboggs@gmail.com` | Center for Integrated Cognition (per GitHub profile); the `agent-policies` repo owner; author of the Coborg framework |
| `claude` | (AI tool — Claude Code) | `noreply@anthropic.com` | Anthropic Claude operating under a human's direction; commit count is large in self-improvement loops |
| `codex@openai.com` | (AI tool — GPT-5 Codex / OpenAI Codex) | — | Co-author on several JBoggsy PRs (#13018, #13056, #13138); never the primary author |

The `claude` GitHub account appears as the committer on commits authored *through* Claude Code. Treat those as human-directed AI work, not autonomous: the volume tracks `/coach.improve` and `/loop` sessions driven by the listed humans. The `GPT-5 Codex` / `OpenAI Codex` co-author trailers on JBoggsy's PRs play the same role for his work.

### Cogamer framework — author trail

Repository lineage (oldest → newest):

1. **`Metta-AI/coglet`** — created **2026-03-28 08:12Z** by **daveey**, not a fork. First commit `a30bf25` 2026-03-28T08:12:25Z "add coglet architecture and tournament system design docs"; second commit `2f05279` "implement coglet framework and cogames player". This is **the genesis of the Coglet runtime, PCO, and the CvC policy**. Contributor count: 83 `claude` / 81 `daveey` — early architecture commits are all daveey; later "coach: session N — …" tuning commits are claude under daveey's supervision (e.g. `5bcc3f8` "coach: session 56 — interleaved role priorities (+217% self-play)"). PCO ships in `08f131b8` 2026-03-29 "add ProximalCogletOptimizer: PPO as a coglet graph" — David Bloomin.
2. **`Metta-AI/cogamer-v0`** — created **2026-04-01**, **fork of `Metta-AI/coglet`** (`parent: Metta-AI/coglet`). Archived 2026-04-07. Contributor count: 145 `daveey` / 71 `claude`. This is where the structural refactoring happened (e.g. `08afc88a` "restructure cvc policy: flat agent/ modules with mixin-based engine"; `fefe1384` "Extract decision pipeline from monolithic _choose_action, add TickContext"; `459e7b58` "Fold cvc_policy.py and cogames_policy.py into cogamer_policy.py") — all David Bloomin.
3. **`Metta-AI/cogamer`** — created **2026-04-08**, archived **2026-04-10**, not a fork. Only **14 commits, all daveey**. This is the thin top-level platform wrapper added when cogamer merged with the `cogent` package (commit `ddda5725` "feat: add cogamer package — merge cogent + cogamer repos (#11043)" — PR number `#11043` lives in the metta monorepo). The provenance SHA `b57f070...` is daveey's final commit here: "Replace old skills with cogamer.* skills using softmax cogames CLI", 2026-04-10T22:45:14Z.

**The "cogamer" code in this repo was authored primarily by David Bloomin (daveey).** Claude Code (the AI) wrote a large fraction of commits but only in a directed/tuning capacity — design, framework primitives, and structural refactoring are daveey. The Markdown skills, lifecycle prompts, and memory format are daveey's design.

Earlier upstream context worth noting: the Coglet CvC policy was bootstrapped from an LLM-only baseline in **`Metta-AI/cogora`** — commit `91652241` 2026-03-28 "copy cogora LLM policy as PolicyCoglet baseline — scoring 1.01 per cog". The `cogora` repo itself is 1309 `claude` / 32 `daveey` — a heavily AI-driven self-improvement loop, again under daveey.

**Recent contributors after the framework stabilised:** Richard Higgins shows up in the agent-policies subtree as the only post-collation contributor with substantive changes (decision-log benchmark metrics). He is not part of the original cogamer authorship but does sustained work on it now.

### CVC Debugger Robot — author trail

This one is much cleaner — single repo, no predecessor.

- The provenance doc names the source as `Metta-AI/cvc-debugger`. That repo no longer exists under that name; it was **renamed to `Metta-AI/debugger`** (visible because the SHA `8666c60...` resolves there). The repo is currently **private**, with the same description ("Real-time debugger and iteration workbench for developing smart AI policies for Cogs vs Clips").
- Created **2026-04-17 00:34Z** by **Aaron Landy** (`aaln`). First two commits:
  - `45ec060b` 2026-04-17T00:34:02Z Aaron Landy "Initial commit from Create Next App"
  - `42104be8` 2026-04-17T02:30:54Z Aaron Landy "**Init cvc debugger**"
- Aaron Landy wrote essentially **all of the policy** in the first day:
  - `bdd183e7` 2026-04-17T06:51:52Z "Add starter policy, readme, debugger ui, api chat, and more!" — this is the seed of `policies/robot/` (the future `cvc_debugger_robot`).
  - `32cdce20` 2026-04-17T21:57:48Z "Add streaming evals, investigation summaries, LLM logs panel, and evals dashboard" — the observability harness (anomaly detector, investigator, LLM logs).
- The eval engine and the optimizer container that this repo splits into `tools/research/cogsguard/cvc-debugger-policy-optimizer/` are also Aaron's: `c8d05b90` "docs: update README with eval engine, cloud eval, and policy optimizer", and the surrounding 2026-04-20 commits ("standalone eval server (no Docker required)", "eval engine UI with multi-seed eval, auto-improve, and cloud support").
- **Richard Higgins** then made the last two commits — both on 2026-04-24, both touching territory perception:
  - `dd09beb4` "feat: rebuild robot territory perception"
  - `8666c607` "Rebuild robot territory perception from edge observations (#2)" — **this is the SHA recorded in `source-provenance.md`**, i.e. the collation pulled from immediately after Richard's territory-perception rewrite.

**The CVC Debugger Robot — both the policy proper and the surrounding observability/optimization harness — was authored primarily by Aaron Landy.** Richard Higgins contributed the territory-perception rebuild that the collated snapshot is dated to.

### Cogora — author trail

This one has two distinct provenance trails because Cogora is two things glued together: an MCP plugin and a CvC player cog. They have different authors.

**The cogora repo container** (`Metta-AI/cogora`) was created **2026-03-25 08:03Z** by **daveey** as a Claude Code MCP plugin (the description still reads "Observatory tournament API as MCP tools for Claude Code"). The first commit is `a411f91f` 2026-03-25T08:03:53Z David Bloomin "Initial cogora plugin — Observatory API as MCP tools". The next half-day of commits are all daveey building out the MCP server (marketplace.json, `/cogora:connect` slash command, bash wrappers). **The MCP server code was deliberately not copied into `agent-policies`** — only the CvC player cog and SDK came along — so the part of cogora that daveey originally built is *not* in this repo.

**The CvC player cog** (the substance of `policies/cyborg/cogamer/cogora/src/cvc/cogent/player_cog/` and the entire `mettagrid_sdk/`) was authored by **Richard Higgins (`relh`)** in the metta monorepo as the "**code-mode cyborg**" architecture. The originating PR is `Metta-AI/metta` PR **#8846 "Part 1 of 12: Specify the per-cog code-mode cyborg contract"**, opened by relh 2026-03-08T22:26:19Z. Its body literally describes the file-set we see locally: "define the per-cog code-mode workspace around `main.py`, `memory.md`, `plan.md`, `experience_trace.jsonl`, and `review_transcript.log`; make `.log()` plus `ReviewRequest` the canonical in-episode escalation path; specify the executable/socket player model, per-cog identity, and review/rewrite loop." The remaining 11 parts of the stack — including PR **#8854 "Part 8 of 12: Add file-backed per-cog memory accessors"** by relh — implement that contract.

**The import event** was daveey's commit `5d5761a3` 2026-03-27T01:49:22Z David Bloomin "**Add cvc_cog package copied from metta cog_cyborg**" (file count 34, the entire `src/cvc_cog/` directory in one commit, co-authored-by Claude Opus 4.6). This is the moment relh's code crossed from the metta monorepo into cogora. Daveey then renamed `cvc_cog` to `cvc/cogent/player_cog`, added the cogent memory/lifecycle layer (`memory.md`, `cogames.md`, `main.md`, `setup.sh`), and from that point on the cogent named **Alpha** (running as Claude under the lifecycle daveey designed) took over: 1309 commits as the GitHub user `claude` — almost all of them "alpha policy vN: …", "session start/progress/complete", and "vN/vN+1: fix …" — produced the 22+ frozen `Alpha*AgentPolicy` variants in `anthropic_pilot.py`.

Daveey's 32 commits across the whole cogora repo split roughly into: the MCP plugin setup (~6 commits, 2026-03-25), the cvc_cog import + restructuring (~10 commits, 2026-03-27 early), the cogent memory/lifecycle docs (~4 commits, 2026-03-27 early), and **periodic syncs of cyborg-policy improvements from the metta monorepo** (e.g. `f92a07f7` 2026-03-27T21:41:45Z "Sync cyborg policy from metta repo — fix all-miners deadlock") — meaning relh's ongoing work in metta continued to flow into cogora during Alpha's iteration window.

The provenance SHA `436d60e5` is the final commit on cogora's main: `Claude` 2026-03-31T08:21:28Z "session complete: 2026-03-31-071539 — v915 avg 1.37, heuristic ceiling ~2-3". The cogora repo has not been touched since (last push 2026-03-31), which makes sense — by 2026-03-28 daveey had started Coglet and copied the Alpha policy in (`91652241` "copy cogora LLM policy as PolicyCoglet baseline — scoring 1.01 per cog"), shifting active work into the Coglet/Cogamer line.

**Authorship summary for Cogora:**

- **Richard Higgins** (`relh`) — original author of the code-mode cyborg architecture (the `player_cog/policy/`, `player_cog/runtime/`, `player_cog/memory/`, `player_cog/providers/`, and `mettagrid_sdk/` substrate) via metta monorepo PRs #8846–#8857 and surrounding cleanup work (#9105–#9120, #9164, etc.). This is the only part of cogora that survived into `agent-policies`.
- **David Bloomin** (`daveey`) — original author of the cogora MCP plugin shell (not copied), the cogent memory/lifecycle wrapper Markdown (`main.md`, `memory.md`, `cogames.md`), the `setup.sh` + `setup_policy.py` packaging for tournament uploads, and the operator decisions about how the cogent runs.
- **Claude** (running as the persistent cogent **Alpha**) — 1309 commits producing the policy-variant iterations (`AlphaV65…`, `AlphaCog…`, `AlphaStableBoost…`, etc.) in `anthropic_pilot.py`, written across hundreds of self-improvement sessions under daveey's supervision.

### Coborg — author trail

This is the cleanest trail of the four because Coborg is the youngest framework and has a single human author.

- The framework was added to the metta monorepo as **PR `Metta-AI/metta` #13018 "Add reusable cyborg agent framework"** opened by `JBoggsy` (James Boggs) on **2026-05-11 22:11Z**, merged as `b9ed6ebb` on 2026-05-11 22:53Z. Twelve files changed, +2,122 / −0 lines. PR body: "Build a generic inner/outer loop framework for mode-driven game agents, with documentation, a toy example, and focused tests. Co-authored-by: GPT-5 Codex". The framework's own `README.md` is dated "Generated: 2026-05-11" — same day.
- Source projects James generalized from (per the framework's own `SOURCE_REPOS.md`):
  - `/Users/jamesboggs/coding/personal_cogs/persephone` (Persephone / Orpheus) — present locally at `users/james/personal_cogs/persephone/`.
  - `/Users/jamesboggs/coding/personal_cogs/among_them/guided_bot` (Among Them / guided_bot) — present locally at `users/james/personal_cogs/among_them/guided_bot/`.
  - `/Users/jamesboggs/coding/cogames_playground/bulbacog` (Cogs v Clips / Bulbacog) — **not** in this repo. `SOURCE_REPOS.md` explicitly notes "the originally requested Bulbacog path … was not present when the framework report was created."
- **Follow-on PRs by JBoggsy in the same week**, all in metta:
  - `#13056` "Audit cogames-agents documentation" (2026-05-11 23:45Z, ~50 min after #13018).
  - `#13068` "docs: specify agent policies workspace" (2026-05-12).
  - `#13138` "Externalize policy workspaces" (2026-05-13 05:21Z) — body: "Remove the collated cogames-agents and cogames-rl-researcher source trees from the Metta monorepo after copying them into the agent-policies workspace." **This is the PR that completes the cutover** from metta-monorepo-resident framework to standalone `agent-policies` repo.
  - `#13139` "Add cogames agents migration guard" (same day) — locks down accidental re-imports.
- **Out-of-band carry-forward.** The provenance doc records that on 2026-05-12 James copied **uncommitted metta worktree updates** into `src/agent_policies/frameworks/coborg/` before deleting the metta copy. Those updates introduced shared locked memory snapshots, `ModeDecision`, `AsyncStrategyRunner`, metrics sinks, and priority `ReflexRule` support. **The local `coborg/` is therefore ahead of the metta-monorepo version at `aa1d7c5b`**, and that delta exists only in this repo.
- AI co-authorship: PRs #13018, #13056, and #13138 all carry `Co-authored-by: GPT-5 Codex <codex@openai.com>` trailers. Treat them like the `claude` co-authorship in Cogamer/Cogora — model-assisted human work, not autonomous output.

**Authorship summary for Coborg:**

- **James Boggs** (`JBoggsy`) — sole human author and designer. Framework distilled from three of his own prior agent projects (Persephone/Orpheus, Among Them/guided_bot, Bulbacog). All four originating commits in the upstream metta monorepo are his (#13018, #13056, #13068, #13138, #13139). The framework's documentation (`README.md`, `PYTHON_FRAMEWORK.md`, `SOURCE_REPOS.md`) reads as his own design specification.
- **GPT-5 Codex / OpenAI Codex** — AI co-author trailer on the relevant PRs; not a separate authorship voice.

### Cyborg Evolution — author trail

This is the shortest trail in the document. The entire upstream history fits in four commits.

- Source repo `Metta-AI/policies` was created **2026-04-29 01:09:27Z** by `aaln` (Aaron Landy) with the description "Just policies." (terse and accurate). Last pushed 2026-04-29 01:39:46Z — **about 30 minutes after creation** — then **archived**. The repo lived as an active repo for half an hour.
- Four commits total, all by Aaron Landy on 2026-04-29:
  - `f8dc0120` 01:24:56Z "Initial commit: Cyborg Policy Framework" — the entire framework, the new_game template, the wiki, the scripts, the design doc — dropped in as one initial commit ~15 minutes after the repo was created.
  - `c35cdd73` 01:34:48Z "Add illustrative diagrams to README" — added `assets/evolution-loop.png`, `assets/plugin-architecture.png`, `assets/weekly-lifecycle.png`.
  - `c9d6164d` 01:39:04Z "Add Cursor skills for cyborg policy framework components" — added the seven `.cursor/skills/cvc-*/SKILL.md` bundles.
  - `f0c7a851` 01:39:44Z "Rename skills from cvc-* to cyborg-* for game-agnostic naming" — **40 seconds later**, renamed every `cvc-*` symbol/path to `cyborg-*`. This is the provenance SHA used in the collation.
- Contributor stats: 4 commits, 1 contributor (`aaln`). No PRs, no issues — single-shot snapshot.
- **Lineage from `Metta-AI/cvc-debugger` (now `debugger`).** The final rename commit, plus the framework's strategy/skills wiki vocabulary (role selection, frontier exploration, resource management, mining/aligning patterns), confirms Cyborg Evolution was an extraction and generalization of Aaron's earlier work on the CVC Debugger Robot. The CVC Debugger Robot repo (created 2026-04-17 by Aaron, snapshot SHA `8666c60` from 2026-04-24) is the proximate predecessor; the framework code likely existed in Aaron's local working tree for the week between 2026-04-24 and 2026-04-29 before being dropped into `Metta-AI/policies` as a clean snapshot.
- **Carry-over into `agent-policies`.** Per the provenance doc, the collation copied this snapshot in two pieces: the framework source to `src/agent_policies/frameworks/cyborg_evolution/`, and the Cursor skills (which live under `.cursor/skills/` in the upstream repo) to `tools/research/cursor-skills/skills/`. The Cursor skills' `.cursor/` parent directory was dropped during the move — only the inner `skills/cyborg-*/` directories were preserved.

**Authorship summary for Cyborg Evolution:**

- **Aaron Landy** (`aaln`) — sole human author. Single-shot framework distillation from his CVC Debugger Robot work, dropped into a dedicated repo, polished for 15 minutes, and archived. No co-authors, no AI co-author trailers.

### Related artifacts in the provenance doc

- **`Metta-AI/cogamer-policy-cvc`** (the generated CvC policy artifact copied into `policies/cyborg/cogamer/generated/cvc-policy`) — 147 commits `daveey`, 5 `relh`. This is the policy *output* by the cogamer framework, tuned by daveey, with Richard's late CI/territory fixes.
- **`Metta-AI/cogamer-policy-cogony`** (the generated Cogony policy artifact, archived, fork) — same lineage pattern: a generated artifact rather than a hand-written policy.

### Bottom line

| Component in `agent-policies` | Primary human author | Notable co-authors / contributors |
|---|---|---|
| `src/agent_policies/frameworks/coborg/` (reusable Cyborg framework: types, modes, runtime, strategy runners, tracing) | **James Boggs** (`JBoggsy`) | GPT-5 Codex (co-author trailer on PR #13018); distilled from his own Persephone/Orpheus, Among Them/guided_bot, and Bulbacog projects |
| `src/agent_policies/frameworks/cogamer/` (Coglet runtime, PCO, CvC policy, skills, lifecycle, memory) | **David Bloomin** (`daveey`) | Claude Code (heavy in `/coach.improve` tuning); Richard Higgins (post-collation decision-log work); Cogora baseline by **Richard Higgins** seeded the CvC `PolicyCoglet` |
| `src/agent_policies/frameworks/cyborg_evolution/` + `tools/research/cursor-skills/` (closed-loop play-analyze-evolve framework, 3-tier memory, weekly lifecycle) | **Aaron Landy** (`aaln`) | — (sole author, single-shot extraction from CVC Debugger Robot lineage) |
| `policies/cyborg/cogamer/generated/cvc-policy` (generated artifact) | **David Bloomin** | Richard Higgins (late CI/territory) |
| `policies/cyborg/cogamer/cogora/` (Alpha CvC player cog + mettagrid_sdk) | **Richard Higgins** (`relh`) — code-mode cyborg architecture from metta monorepo | David Bloomin (cogent lifecycle wrapper, packaging, periodic syncs from metta); Claude (1309 commits producing the Alpha policy-variant tree as the cogent "Alpha") |
| `src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot/` (robot policy + observability harness) | **Aaron Landy** (`aaln`) | Richard Higgins (territory perception rewrite — this is the version snapshotted into `agent-policies`) |
| `tools/research/cogsguard/cvc-debugger-policy-optimizer/` (optimizer container) | **Aaron Landy** | — |

### Source notes

All SHAs and dates verified against the GitHub API on 2026-05-18 using `gh api repos/Metta-AI/<repo>/commits/<sha>` and `repos/Metta-AI/<repo>/contributors`, and the GitHub commit-search API for cross-referencing metta-monorepo PR titles. Of the five source repos, `Metta-AI/cogamer`, `Metta-AI/cogora`, and `Metta-AI/policies` are archived/dormant (last activity 2026-04-10, 2026-03-31, and 2026-04-29 respectively — `Metta-AI/policies` was only active for ~30 minutes total); `Metta-AI/debugger` (renamed from `cvc-debugger`) is private but its `main` branch is exactly at the collated SHA; `Metta-AI/metta` is the active monorepo and Coborg's originating PRs (#13018, #13056, #13138) are all merged there. Ongoing work has moved into the metta monorepo (`Metta-AI/metta:cogames-agents` for the broader cyborg framework, where Richard Higgins continues to be the primary author of the cog-cyborg substrate; James Boggs for the Coborg substrate that has since been externalized) and into `agent-policies` for the collated policy snapshots. The Coborg copy in `agent-policies` is **ahead** of the metta-monorepo version because uncommitted worktree updates were carried over on 2026-05-12. The Cyborg Evolution copy is **exactly at** the upstream archive snapshot — no drift in either direction.

