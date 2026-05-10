# TODO

Known issues and planned work for the persephone project.

## Perception Module

### DONE: Shape detection implemented + outline_is_black fix

- **Status**: Complete (commit `93cf58f`)
- Shape classifier matches 7x7 pixel patterns against 12 templates.
  Works for overworld (shadow-aware) and HUD contexts (outline_is_black=True).
  Game renders outlines as color 0 (black), not color 1 — the
  `outline_is_black` parameter handles this for speech bubbles, pending
  entry sprites, and whisper header occupants.

### DONE: Test imports fixed after perception move

- **Status**: Complete
- Tests now import perception through `orpheus.perception`. The legacy
  script imports in `scripts/capture.py` and `scripts/extract_fixture.py`
  were also updated to the current package path.

### waiting_entry not testable with current capture setup

- **Status**: No fixture captured
- **Impact**: The `waiting_entry` detection logic exists and matches
  the TS parser, but we cannot generate a test fixture because the
  winner_bot fillers always initiate whispers directly (no opportunity
  for our bot to be the one requesting entry).
- **Fix**: Use less-aggressive filler bots or a two-bot choreography
  where one bot creates a whisper and the other requests entry.

### DONE: Shape classification in chatroom header sprites

- **Status**: Complete (commit `93cf58f`)
- `scan_sprite_row_with_shapes` now used with `outline_is_black=True`.
  Header position updated to x=66 (current renderer), falls back to
  x=22 for legacy fixtures. Returns `(color, shape)` pairs.

### Global chat parser: messages and hostage grid not validated

- **Status**: Partial
- **Impact**: Room name, usurp candidate, and bottom bar are now
  validated. But message parsing, hostage grid parsing (for leaders),
  and committed state detection have not been validated against live
  frames because no fixture exists with those elements active.
- **Fix**: Capture global chat frames with messages visible and with
  the leader hostage-grid active.

## Orpheus Framework

Stages 0-9 are implemented (commits `4808ccb` … `25dc995`). The follow-ups
below are deferred work flagged with `# TODO Stage N follow-up:` /
`# TODO Stage N perception gap:` markers in the source.

### Stage 2: belief update — perception gaps

The belief update pipeline integrates everything perception currently
produces, but several DESIGN.md fields rely on perception data that is
not yet extracted. Each is marked in `orpheus/belief_update.py`:

- **DONE: `round_schedule` from RoleReveal**:
  `RoleRevealPerception.round_schedule` now carries parsed
  `(duration_secs, hostage_count)` rows from the schedule panel, and
  `_apply_role_reveal` populates `belief_state.round_schedule`. Remaining
  work: validate against live frames from all config presets.
- **DONE: Self color/shape/index from RoleReveal**:
  Perception now surfaces the centered own-sprite from the role card as
  `self_color` and `self_shape`; `_apply_role_reveal` decodes
  `my_color`, `my_shape`, and `my_index`. Remaining work: validate against
  live role-card captures for all player shapes.
- **Other-room leader colors** (line ~282):
  Only the self-leader color is set when `is_leader and my_room` are
  known. Cross-room leader detection requires perception support that
  doesn't yet exist (the overworld view only shows our own room).
- **DONE, needs live validation: Visible-player overworld sprites and role
  indicators**:
  `OverworldPerception.visible_players` now surfaces ordinary visible sprites
  without speech bubbles, including role indicators when visible. Belief
  update records current-tick positions without marking those players as in a
  whisper. Remaining work: validate against live fog/obstacle frames and tune
  false-positive suppression if needed.
- **Whisper `my_exchange_partner` detection** (line ~428):
  Best-effort regex on a "shared roles" system message text. Full
  detection requires identifying the two participant sprites in the
  perception output, which is not yet exposed.
- **Global-chat leader colors** (line ~516):
  Currently approximates "leader == current usurp candidate when no
  usurp is active." Real disambiguation needs more perception state.

### Structured whisper system messages: attribution still incomplete

- **Status**: Partial
- **What works**: `BeliefState` now includes `active_color_offers`,
  `active_role_offers`, `last_exchange_event`, and `my_exchange_partner`.
  `orpheus/belief_update.py` updates these fields from whisper system
  messages including offered color/role, swapped colors, shared roles,
  withdrawals, and leadership offers. Eurydice now consumes these structured
  fields before falling back to `chat_history`, de-duplicates repeated active
  offers/events, and logs ambiguous crowded-whisper completions without
  assigning them to the wrong player.
- **Remaining impact**: Multi-occupant attribution is still incomplete when the
  source perception does not expose embedded refs or target-picker identity.
  Agents need to know:
  - Whether an incoming color/role offer is active (and FROM WHOM when
    multiple occupants are present -- the bottom-bar "R!"/"C!" indicator
    does not identify the offerer)
  - Whether a completed exchange can be attributed without relying on the
    "single other occupant" heuristic
  - Whether a leadership offer can be tied to a specific player in crowded
    whispers
- **Fix**: Extend perception/system-message parsing for the remaining crowded
  cases. Post-whisper info-screen reconciliation is now wired for parsed
  role/color entries; live traces should confirm whether hostage-exchange
  surfaces need a separate reconciliation trigger.
- **Ref**: Eurydice implementation plan Phase 2.

### Eurydice strategic params: partial runtime wiring

- **Status**: Partial
- **What works**: Core role evaluators now emit typed params/objectives for
  partner search, target probing, leadership, positioning, and disruption.
  `meta_decide` stores full directives during hysteresis so params are not
  erased, stores the last non-whisper directive for protocol recovery, and
  `InWhisperMode` can select stall, key-exchange, quick-verify, and
  infiltration behavior from that context. Probe modes now track lifecycle
  state, cap failed target attempts per round, and avoid initiating whispers
  during HostageSelect. Additional evaluator contracts cover cross-room key
  partner behavior, Shade leader hostage strategy, Spy real-team verification
  targeting, and the final-round partner-unreachable override.
- **Remaining impact**: Advanced modes still consume only a subset of these
  params. Hostage selection, summit behavior, cross-room coordination, decoy,
  relay, and broader deception behavior remain shallow relative to the full
  design.
- **Fix**: Continue Eurydice implementation plan Phases 4-8 with live trace
  validation after each phase.

### Intro panel sequence: live validation still incomplete

- **Status**: Partial
- **Impact**: The perception detector classifies the 4-panel intro
  sequence into `ROSTER_REVEAL` (Panel 0) and `ROLE_REVEAL` panels 1-3.
  `RoleRevealPerception.panel_index` now distinguishes panel 1 (role
  card), panel 2 (role summary), and panel 3 (round schedule) when OCR
  markers are visible. Remaining gaps:
  - Panel 2 (role summary) now parses unique match roles, missing core roles,
    echo substitutions, and `spy_in_game_config` from synthetic fixtures and
    a live Spy/Echo fixture. The source game does not render exact duplicate
    role counts on this panel. Remaining work is broader live-frame validation
    across config presets.
  - Panel 3 schedule rows are parsed into `belief_state.round_schedule`,
    with a live fixture for a custom non-default three-round schedule.
    Remaining work is broader live-frame validation across config presets.
- **Fix**: Capture broader live intro-panel fixtures across config presets,
  then tune OCR if those frames drift from synthetic and existing live tests.
- **Ref**: Eurydice implementation plan Phase 1B.

### Stage 4: task `select_action` approximations

Four tasks ship with simplified `select_action` implementations that
need refinement against a live game. Each is marked
`# TODO Stage 4 follow-up:` in source. The framework contracts (frozen
dataclass shape, `valid_views`, structural equality) are correct for
all 24 tasks — only the per-tick action sequencing needs work.

- **`MenuNavigator` direction-cycling** (`orpheus/tasks/_menu_nav.py:13-16`):
  Always presses Right/Down to advance category/item, never Left/Up.
  Works as long as the menu wraps cyclically; needs validation against
  the actual menu order. Target-picker matching against perceived
  `target_colors` is also heuristic.
- **`WanderTask` exploration bias** (`orpheus/tasks/movement.py:225`):
  Picks blind random `(x, y)` waypoints inside the room. Should bias
  toward known-FREE unvisited cells once the occupancy grid has data.
- **`VoteUsurpTask` candidate selector** (`orpheus/tasks/leadership.py:54`):
  Emits a rising-edge A press only; does not yet navigate the L/R
  candidate selector to the target candidate. Assumes the desired
  candidate is already focused (or that the agent ran an
  approximation-pass first).
- **`SelectHostagesTask` cursor navigation** (`orpheus/tasks/hostage.py:25`):
  Tracks remaining indices in action memory and emits A toggles, but
  does not yet drive the U/D/L/R cursor movement onto each target color
  in the grid.

### DONE: Stage 7 outer-loop `staleness` computed when tick provider exists

`OuterLoop` now accepts an optional `tick_provider` and records
`staleness = current_tick - consumed_tick` when available. Existing tests
cover both the no-provider `None` case and the computed case.

### DONE: Stage 8 verbose-level log categories

`orpheus/pipeline.py` now emits the verbose entries listed in DESIGN.md:
`belief_diff`, `cooldown_change`, `minimap_sighting`, `grid_change`, and
`action_memory_mutation`, in addition to full perception and act-command
logging.

### DONE: `BeliefState.reset()` clears ad-hoc attributes

`BeliefState.reset()` now restores declared dataclass fields and deletes
attributes outside the schema. Flexible per-game data should still live in
`belief_state.extra`.

### LOW PRIO: Mutable action mask in post_act hooks

- **Status**: Future direction
- **Impact**: Currently action_mask is read-only in all hooks. Allowing
  post_act hooks to modify the action mask would enable safety overrides
  or emergency interrupts at the hook level.
- **Decision**: Blanket read-only for now. Revisit if a concrete use case
  emerges.

### LOW PRIO: Hook dependency ordering

- **Status**: Future direction
- **Impact**: Hooks at the same point currently fire in FIFO registration
  order. If hooks develop complex interdependencies, a dependency-aware
  ordering system (e.g., "run after hook X") could be added to the
  registration method.
- **Decision**: FIFO is sufficient for now. Revisit if hook count grows
  large or ordering bugs emerge.

## Eurydice Agent — Whisper Interaction

### LLM control is schema-ready but not runtime-ready

- **Status**: New foundation only
- **What works**: `agents/eurydice/llm_context.py` builds a JSON-safe context
  packet for future model calls and exposes a closed semantic decision schema.
  `agents/eurydice/LLM_CONTROL.md` documents the intended staged rollout.
- **Impact**: We can now shadow-test model choices for probe targeting,
  whisper/global messages, and reveal decisions without changing live control.
  Runtime Eurydice still uses deterministic evaluators and modes.
- **Fix**: Add a deterministic LLM-decision validator, shadow trace events, a
  saved-context runner, prompt templates, and finally a provider adapter behind
  an explicit feature flag.

### Probe initiation reliability remains the next live bottleneck

- **Status**: Partially fixed
- **What works**: Agents now learn roles, parse round schedules, enter
  role-driven objectives, select probe targets, and complete some probes in
  live traces.
- **Impact**: A 10-agent live run on `seed=306` selected 39 targets across 9
  unique player IDs and completed 3 probes, but logged 11
  `initiate_timeout` failures. The issue is no longer basic strategy
  activation; it is rendezvous/interaction reliability.
- **Fix**: Improve approach positioning, bubble-visible-range behavior,
  meeting-point logic, global "come to me" announcements, and entry timeout
  handling before relying on richer LLM social strategy.

### Agents can't join each other's whispers (fog-of-war visibility)

- **Status**: Partially fixed — all mechanical pieces work, spatial
  coordination doesn't
- **Impact**: Agents create solo whispers and wait (up to 15s). Other
  agents try to join but can only see speech bubbles within fog-of-war
  range (~30-40px). By the time an agent walks close enough to see a
  bubble, the whisper creator may have already timed out.
- **What works**: Whisper creation (A-press), view detection (WHISP at
  42,2), speech bubble detection (100% shape accuracy), entry request
  (B-press → waiting_entry), pending entry detection (WANTS IN at y=111),
  entry grant (GrantEntryTask fixed button sequence). Full chain proven
  with recorded frames.
- **What doesn't**: Spatial coordination. Agents approach via minimap
  (which doesn't show whisper status), so they don't prioritize whisper
  players until within visual range.
- **Fix options**:
  1. Have agents approach to ~30px before deciding create vs join (get
     within bubble-visible range first, then check for bubbles)
  2. Use global chat to announce "I have a whisper" with a position
  3. Designate a meeting point (e.g. room center) where agents cluster
     before initiating whispers
  4. Increase whisper wait timeout further (30+ seconds)
  5. Track "last known whisper position" from minimap + timing heuristic
     (player stopped moving → likely in whisper)

### Remove `_find_player_by_color` fallback

- **Status**: Can be cleaned up
- **Impact**: The color-only fallback in `belief_update.py` is no longer
  needed now that `outline_is_black=True` gives 100% shape detection on
  HUD sprites. The fallback still handles edge cases (players 8-9 with
  shared colors), but with proper shape detection those should resolve
  correctly.
- **Fix**: Remove `_find_player_by_color` and the fallback paths in
  `_apply_overworld_speech_bubbles` and the pending_entry section.
  Verify no regression in shape detection coverage first.

### DONE, needs live validation: Visible-player overworld sprites (non-bubble)

- **Status**: Implemented against synthetic tests; live validation pending.
- Plain visible sprites now update precise positions and full color/shape
  identity through `OverworldPerception.visible_players`.
- **Follow-up**: Capture live obstacle/fog frames with non-bubble players and
  verify no false positives in HUD, minimap, floor, or role-indicator areas.
