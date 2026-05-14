# Orpheus — Implementation Plan

High-level roadmap for implementing the Orpheus framework as specified in
[DESIGN.md](DESIGN.md). Each stage builds on the previous; the dependency
graph at the bottom shows parallelization opportunities.

---

## Stage 0: Core Data Types and Interfaces

**Goal**: Define the type contracts everything else depends on.

1. **`types.py`** — Framework-wide enums and constants: `View` enum (if not
   already in perception), `ActionMask` typedef, player color/shape lookups,
   room identifiers.
2. **`mode.py`** — `Mode` ABC with `select_task`, `mode_enter`,
   `mode_switch_cleanup`. `ModeParams` base dataclass, `ModeDirective` frozen
   dataclass. `ModeRegistry` (dict-backed, keyed by string).
3. **`task.py`** — `Task` ABC with
   `select_action(belief_state, action_memory) -> ActCommand`. `valid_views`
   class attribute. `ActCommand` frozen dataclass (`buttons`, `chat_text`,
   `reset_input`).
4. **`action_memory.py`** — `ActionMemory` class with standard fields
   (`ticks_active`, `commands_sent`, `last_command`, `command_history` ring
   buffer). Rising-edge sequencing state. Clear method for task-change resets.
5. **`belief_state.py`** — `BeliefState` class with the full required-fields
   schema. Player registry sub-structure. `inferences` namespace.
   Initialization/reset methods.

**Exit criterion**: All ABCs importable, dataclasses constructible,
`BeliefState` instantiable with defaults.

---

## Stage 1: Inner Loop Skeleton (No Real Logic)

**Goal**: The four-phase pipeline runs end-to-end with stubs, producing a
no-op each tick.

1. **`pipeline.py`** — The inner loop tick function: calls perception →
   belief_update → (consume mode buffer) → decide → act, in sequence.
   Accepts a `frame` and the live state objects.
2. **Perception integration** — Wire the existing `perception/` module as the
   perception phase. Map its output type (`FramePerception` or equivalent)
   into the pipeline's expected input to belief_update.
3. **Belief update stub** — Sets `tick`, `view`, `in_whisper` (universal
   updates only). All per-view updates are no-ops.
4. **Decide stub** — Calls active mode's `select_task`; compares returned
   task to previous by identity; clears `ActionMemory` on change.
5. **Act stub** — Calls active task's `select_action`; packages result into
   `ActCommand`. Implements `send_act_command` (lowers to protocol packets).
6. **`idle` task and `idle` mode** — Built-in defaults.
   `IdleTask.select_action` returns `ActCommand()`. `IdleMode.select_task`
   returns `IdleTask()`.

**Exit criterion**: Given a sequence of frames and a WebSocket mock, the
pipeline ticks without error, sending `0x00` input packets each tick.

---

## Stage 2: Belief Update Pipeline

**Goal**: Perception output is correctly integrated into `BeliefState` each
tick for all view types.

1. **Universal updates** — `tick` increment, `view` set, `in_whisper`
   derivation, whisper-exit clearing, cooldown tick-down.
2. **Lobby** — Reset logic (clear on Lobby after non-Lobby), `player_count`.
3. **RosterReveal** — Populate player registry with color/shape/room for all
   visible players.
4. **RoleReveal** — Set `my_role`, `my_team`, `my_room`, `room_size`,
   `round_schedule`, initialize `occupancy_grid`, decode `my_index`.
5. **Overworld family** — Position, room, round, timer, player registry
   positions (viewport sprites), `minimap_sightings`, `last_seen_in_whisper`,
   role indicators, occupancy grid updates (viewport + minimap + movement
   confirmation), `is_leader`, `leader_colors`, shout to `chat_history`.
6. **Whisper** — `whisper_occupants`, `chat_history` (with occupant tagging),
   `my_exchange_partner` on "shared roles", `pending_offers`,
   `pending_entry`, `menu_state`.
7. **Global Chat** — `chat_history`, `leader_colors`, `hostage_selections`.
8. **Info Screen** — Player registry role/team updates from known-players
   list.
9. **Exchange** — Player registry role/team + room reassignments for
   departing/arriving hostages.
10. **Reveal/GameOver** — `winner`.

**Exit criterion**: Unit tests with canned `FramePerception` objects → assert
belief state fields are correctly populated for each view type.

---

## Stage 3: Occupancy Grid and A* Pathfinding

**Goal**: Spatial reasoning works — the agent can path to any reachable
coordinate.

1. **Occupancy grid** — 2:1 resolution grid class. Cell states
   (UNKNOWN/FREE/WALL). Viewport-confirmed flag. Initialization from
   room_size (border walls).
2. **Grid update from viewport** — Per-tick scan of viewport pixels for
   color-5 walls and floor-color free cells. Camera position derivation from
   self-position.
3. **Grid update from minimap obstacles** — Decode minimap dots to
   approximate world coords, mark 4x4 cell WALL regions in UNKNOWN cells
   only.
4. **Movement confirmation** — 7x7 bounding box FREE marking on position
   change.
5. **A* implementation** — 8-directional, configuration-space expansion
   (walls expanded by player half-width). UNKNOWN = traversable (optimistic).
6. **Re-pathing on stuck** — Interface for tasks to request a new path when
   ActionMemory detects no progress.

**Exit criterion**: Given a partially-explored grid, A* produces valid paths
that avoid known walls and respect the player footprint.

---

## Stage 4: Task Implementations

**Goal**: All 24 tasks from the catalogue produce correct `ActCommand`
sequences.

Build in dependency order (later tasks reuse infrastructure from earlier
ones):

1. **`IdleTask`** — Already exists from Stage 1.
2. **Movement tasks** — `MoveToTask` (A* + directional masks), `FollowTask`
   (re-pathing on target movement, stop_distance), `WanderTask` (random
   waypoint selection).
3. **Rising-edge button sequencing infra** — Shared press/release state in
   ActionMemory. 2-tick minimum cycle.
4. **View management tasks** — `OpenGlobalChatTask`, `OpenInfoScreenTask`,
   `CloseViewTask` (single button press with rising-edge).
5. **Whisper menu navigation infra** — Shared logic: open menu (B) →
   category (L/R) → item (U/D) → confirm (A) → optional target picker
   (L/R) → confirm (A). Used by all exchange/leadership tasks.
6. **Chatroom lifecycle tasks** — `CreateWhisperTask`, `RequestEntryTask`
   (approach + precondition gate + A-press), `CancelEntryTask`,
   `ExitWhisperTask`, `GrantEntryTask`.
7. **Information exchange tasks** — `OfferColorExchangeTask`,
   `AcceptColorExchangeTask`, `WithdrawColorOfferTask`,
   `OfferRoleExchangeTask`, `AcceptRoleExchangeTask`,
   `WithdrawRoleOfferTask`, `RevealRoleTask`.
8. **Leadership tasks** — `PassLeadershipTask`, `TakeLeadershipTask`,
   `VoteUsurpTask`.
9. **Hostage selection task** — `SelectHostagesTask` (grid navigation +
   toggle + commit).
10. **Communication task** — `SendMessageTask` (chat cooldown respect,
    channel assertion).

**Exit criterion**: Each task, given appropriate belief state and action
memory, produces the expected sequence of `ActCommand` values over multiple
ticks. Tested in isolation with mocked belief state.

---

## Stage 5: Hook System

**Goal**: Agent-defined callbacks fire at all phase boundaries with correct
semantics.

1. **Hook registry** — `register_hook(hook_point, callback, modes=None)`.
   Storage by hook point, partitioned into agent-level and mode-level.
2. **Hook dispatch** — At each hook point: deep-copy belief state, call
   agent-level hooks (FIFO), then mode-level hooks (FIFO). On exception:
   rollback to snapshot, log, continue.
3. **Integration into pipeline** — Wire all 8 hook points
   (`pre_perception` through `post_act`) into the Stage 1 pipeline skeleton.
4. **`pre_perception` special case** — Returns frame (modified or original).

**Exit criterion**: Hooks registered for specific modes fire only when that
mode is active. A crashing hook rolls back belief state and doesn't halt the
pipeline.

---

## Stage 6: Mode Switching

**Goal**: The full mode-switch lifecycle works correctly.

1. **Mode buffer consumption** — Inner loop checks mode buffer between
   post_belief_update and pre_decide. Non-blocking consume.
2. **Directive validation** — Mode exists in registry + params type matches.
   Invalid → log + discard.
3. **Reaffirmation check** — Structural equality on `ModeDirective`. Same →
   no-op.
4. **Mode-switch callbacks** — Fire in order (agent-level, then
   old-mode-level). Callback may return override `ModeDirective` (validated
   before acceptance).
5. **Cleanup + activate + enter** — Old mode's `mode_switch_cleanup`,
   framework swaps active mode, new mode's `mode_enter`.
6. **ActionMemory preservation** — Not cleared on mode switch; only on task
   change.
7. **Inferences update** — `belief_state.inferences` replaced wholesale from
   mode buffer entry dict (if non-None).

**Exit criterion**: Mode switches, reaffirmations, callback overrides, and
invalid-directive rejection all work as specified. Tested with a sequence of
directives injected into the mode buffer.

---

## Stage 7: Outer Loop and Buffers

**Goal**: The async outer loop runs alongside the inner loop, producing mode
directives.

1. **Consume-on-read buffers** — Thread-safe size-1 buffer. Write overwrites
   unconsumed. Read consumes (empties). Non-blocking read, blocking read (for
   outer loop).
2. **Belief buffer push** — Inner loop pushes
   `deepcopy(belief_state, action_memory)` after post_belief_update hooks.
3. **Mode buffer push** — Outer loop pushes
   `(ModeDirective, inferences_dict | None)` after `meta_decide` returns.
4. **Outer loop thread** — Blocks on belief buffer, calls agent-defined
   `meta_decide`, pushes to mode buffer, loops.
5. **Watchdog** — Track `ticks_since_last_mode_directive`. On threshold
   breach (default 120 ticks), activate fallback mode. Fires once per
   drought.
6. **Outer loop restart** — Monitor thread; on unexpected termination,
   restart and log.

**Exit criterion**: Inner loop ticks independently at full speed while outer
loop runs async. Outer loop crash → restart. Watchdog fires fallback mode
after timeout.

---

## Stage 8: Logging and Tracing

**Goal**: Structured JSONL logging at all specified granularity levels.

1. **Logger setup** — Per-agent log file. Configurable level (`off`,
   `events`, `decisions`, `verbose`).
2. **Metadata injection** — Every entry carries tick, wall-clock, active
   mode, current task, current view.
3. **Events-level entries** — Mode transitions, task changes, outer loop
   cycles, hook failures, view transitions, game phase changes, watchdog
   activations, outer loop restarts.
4. **Decisions-level entries** — `select_task` returns, `meta_decide` I/O
   summaries, `mode_enter`/`mode_switch_cleanup` calls, valid_views
   mismatches.
5. **Verbose-level entries** — Full perception output, belief state diffs,
   action memory mutations, `ActCommand` per tick, cooldowns, minimap
   sightings, grid cell changes.
6. **`log_event` API** — For hooks/modes to emit custom entries at a
   specified level.

**Exit criterion**: Running the test agent produces JSONL logs at each level.
Logs are parseable and filterable by type/tick/mode.

---

## Stage 9: Test Agent and Integration Testing

**Goal**: End-to-end validation against a real Persephone's Escape server.

1. **Test agent** — A few trivial modes (idle, wander,
   approach-nearest-player). Rule-based `meta_decide` (no LLM). Fallback
   mode = idle.
2. **Unit tests** — Tasks in isolation (mocked belief state). Belief update
   per view type (canned FramePerception). Mode switch sequences. Hook
   dispatch + rollback. Buffer semantics.
3. **Integration tests** — Full pipeline with mocked perception (replay
   canned frames). Verify belief state evolution, task sequencing, mode
   transitions.
4. **Live end-to-end test** — Connect test agent to a real server (fixed
   seed). Verify the pipeline doesn't crash, logs are produced, the agent
   ticks at server rate and produces non-trivial behavior (wanders, detects
   views).

**Exit criterion**: All unit/integration tests pass. Live test completes a
full game without crash.

---

## Dependency Graph

```
Stage 0 (types/interfaces)
  └── Stage 1 (inner loop skeleton)
        ├── Stage 2 (belief update)
        │     └── Stage 3 (occupancy grid + A*)
        │           └── Stage 4 (tasks)
        ├── Stage 5 (hooks)
        └── Stage 6 (mode switching)
              └── Stage 7 (outer loop + buffers)
                    └── Stage 8 (logging)
                          └── Stage 9 (test agent + integration)
```

Stages 2-5 are largely parallelizable (hooks and belief update are
independent; tasks depend on A* but can be stubbed early). Stages 6-7 form a
dependency chain. Stage 8 can be incrementally wired in during any stage.
Stage 9 ties everything together.
