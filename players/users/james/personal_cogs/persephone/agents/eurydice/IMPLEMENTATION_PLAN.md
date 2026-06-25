# Eurydice -- Source-Verified Implementation Plan

This document is the implementation roadmap for taking Eurydice from the
current partially implemented agent to the behavior described in
[`DESIGN.md`](DESIGN.md) and the role strategy documents.

Last source audit: 2026-05-12.

The important planning constraint is dependency order: a phase may only depend
on capabilities proven by earlier phases. For example, role-specific strategy
must not depend on full Spy deception until the generic whisper protocol,
knowledge updates, and evaluator parameter contracts are already working.

---

## Current Baseline

### Completed From This Plan

- **Phase 0 partial:** `scripts/analyze_eurydice_traces.py` summarizes empty,
  plain JSONL, and runner-prefixed JSONL trace output.
- **Phase 1A:** Role-reveal perception extracts the centered own-player sprite,
  and belief update populates `my_color`, `my_shape`, and `my_index`.
- **Phase 1B:** Role-reveal perception parses round schedule rows into
  `(duration_secs, hostage_count)` tuples, and belief update populates
  `round_schedule`. A live fixture covers a non-default three-round schedule.
- **Phase 1C partial:** Overworld perception exposes ordinary visible player
  sprites and visible role indicators; belief update records current-tick
  positions without requiring a speech bubble.
- **Phase 2 partial:** Eurydice consumes structured Orpheus exchange events and
  active offer fields before falling back to text, records ambiguous crowded
  exchanges without attribution, wires `chat_parser` into inbound chat updates,
  and propagates unique leader-color observations into player knowledge.
- **Phase 3 partial:** Core evaluators now emit typed params and objectives for
  partner search, target probing, leadership, positioning, and disruption;
  `meta_decide` preserves full directives during hysteresis and logs params.
- **Phase 4 partial:** Probe attempts now track target selection, started
  action, completion, and per-round failures; `probe_target` no longer joins an
  unrelated nearby whisper; failed entry attempts are capped per target/round;
  probe modes no longer initiate whispers during HostageSelect. Key roles use a
  shared `(54, 66)` rendezvous with tight 8px open/reached ranges, Hades and
  Persephone act as requesters, Cerberus and Demeter act as openers, entry
  request pulses are globally throttled to 72 ticks to avoid canceling pending
  requests, requesters sweep a small 8px radius to refresh stale partner
  positions, openers run a short blind `GRANT` window followed by a longer
  blind `R.OFFER` window, requesters blind-offer after entry requests instead
  of blind-accepting from unsafe gameplay pixels, and B-entry tasks have a
  bounded retry window.
- **Phase 5 partial:** `in_whisper` now derives protocol from the directive
  that caused whisper entry, supports stall/key-exchange/quick-verify/
  infiltration selection, applies Spy-aware incoming role-offer decisions, and
  explicitly handles hostile entrants, forced ejection, and post-whisper
  info-screen reconciliation. Exchange menu tasks persist until the menu
  sequence completes, menu-backed tasks use robust held button presses, and
  solo/key-exchange whispers grant the first or intended requester instead of
  blocking all entry during sensitive states. Hidden key-exchange whisper state
  now persists whether the local agent created the whisper, so the in-whisper
  FSM can continue blind grant/offer phases even if probe state changes or
  occupants are not parsed.
- **Phase 6 partial:** Additional role-evaluator contracts cover key partner
  cross-room behavior, Persephone escape/hold behavior, Shade leader hostage
  strategy, Spy real-team verification targeting, and final-round partner
  unreachable disruption. P_FINAL now requires a real parsed schedule and a
  positive current round.
- **LLM-readiness partial:** `llm_context.py` provides a JSON-safe v2 decision
  context and closed semantic output schema for LLM control. `llm_validator.py`
  validates model-shaped decisions and can emit compact shadow trace events.
  `llm_prompts.py`, `llm_provider.py`, `llm_shadow.py`, `llm_executor.py`, and
  `llm_action_mode.py` now provide strategic prompts, deterministic providers,
  an opt-in standard-library AWS Bedrock Claude Haiku provider, shadow-runner,
  and semantic executor. Runtime LLM control is still off by
  default, but `--llm-control shadow|targets|whispers|all` can trace decisions,
  limit authority to probe targets or whisper-local choices, or let `all`
  drive every validated executor-backed semantic action in the current view:
  probe targets, movement/open-view actions, global chat, leader-summit chat,
  leadership seeking, and hostage selection. Real-provider calls have
  cooldown/fallback safeguards; executor-backed actions fail closed after view
  changes, and validators reject false self-identity or unsupported role
  claims. Short Haiku smoke validation produced no provider errors and no
  `valid_views_mismatch` events, but default self-play still needs live
  mixed-policy/exchange-completion evaluation.
  See [`LLM_CONTROL.md`](LLM_CONTROL.md).

### Proven or Mostly Implemented

- Eurydice policy startup, mode registry, Orpheus `Pipeline`, post-belief hook,
  and `OuterLoop` wiring are implemented in `policy.py`.
- Orpheus perception parses the major views and produces structured
  `FramePerception` objects.
- Role card parsing extracts own role, team, room, room size, own sprite
  identity, round schedule rows, and role-reveal panel index for panels 1-3.
- Overworld parsing extracts speech bubbles, ordinary visible player sprites,
  minimap dots, and visible role indicators.
- Belief state stores structured whisper exchange fields:
  `active_color_offers`, `active_role_offers`, `last_exchange_event`, and
  `my_exchange_partner`.
- Eurydice initializes accumulators and player knowledge, tracks positions from
  available observations, tracks our current whisper occupants, records simple
  exchange/chat counters, derives a subset of behavioral flags, and runs basic
  hard inferences from Orpheus player registry fields.
- `meta_decide` builds a `StrategicState`, computes urgency, applies phase and
  whisper overrides, implements a 48-tick hysteresis guard, and dispatches to
  role evaluators.
- Basic movement/probing modes exist: `idle`, `scout`, `probe_target`, and
  `probe_systematic`.
- `in_whisper` is a real FSM with color exchange, role exchange, extraction,
  stall, exit, forced-ejection, and entry-request handling. Its exchange trace
  events now distinguish attempted menu sequences from server-confirmed
  exchange completions with `server_confirmed`.
- Advanced mode classes exist for leadership, hostage selection, summit,
  cross-room coordination, relay, time-waste, decoy, and info screen checks.
- Exchange-related whisper activity schedules a brief info-screen pass;
  Eurydice reconciles parsed info-screen role/color entries into mechanical
  exchange truth and repairs `my_exchange_partner` when attribution is unique.
- Chat parsing and deception helpers exist as isolated modules.

### Major Gaps Against the Design

- Perception parses role-summary membership, missing roles, echo
  substitutions, and Spy presence from synthetic fixtures plus a live
  Spy/Echo role-summary fixture. Round schedule parsing has synthetic coverage
  plus a live non-default schedule fixture. Exact duplicate role counts are not
  rendered by the game, so elimination rules still need a separate source or
  conservative constraints. Visible player
  sprite/role-indicator parsing exists but still needs live-frame validation.
- Minimap sightings are color-only and currently map to the first matching
  non-self player index, which is ambiguous when colors repeat.
- `update_whisper_tracker` only tracks occupants of our current whisper; it
  does not infer other players' whisper partnerships from nearby speech
  bubbles.
- `update_exchange_tracker` now consumes structured fields first and schedules
  info-screen reconciliation, but it still cannot identify crowded-whisper
  offers unless Orpheus provides embedded refs or an unambiguous target.
- `update_chat_tracker` now calls `chat_parser` for inbound claims and action
  requests, but outbound communication policy and message budgeting remain
  later-phase work.
- `update_leadership_tracker` handles self leadership and unique leader-color
  observations, but not detailed usurp/pass-leadership system-message parsing.
- Spy-aware color-exchange confidence is implemented from parsed
  `spy_in_game_config`; broader Spy suspicion and deception reasoning remain
  later-phase work.
- `StrategicState.current_objective` is populated for the implemented evaluator
  branches, but phase overrides and advanced-mode internals still use shallow
  intent.
- Evaluators emit typed params for core branches, but several advanced modes
  only store or lightly consume those params. They do not yet implement the
  full role-specific behaviors described in `DESIGN.md`.
- Probe rendezvous now has cooperative key-pair meeting behavior and can produce
  server-confirmed joins, but live self-play still fails to convert those joins
  into server-confirmed role exchanges. The active blocker is post-join
  requester view/perception and safe exchange completion, not just target
  selection.
- Advanced modes are intentionally shallow: hostage selection is mechanical,
  cross-room coordination only sends `SEND ME`, `hold_position` does not
  actively seek leadership, and `decoy` does not communicate a false identity.
- Deception and Spy behavior are partially wired into whisper role-offer
  decisions, but broader cover management and outbound deception policy remain
  later-phase work.
- LLM control has a stable v2 context/output contract, deterministic validator,
  prompt scaffolding, fake providers, saved-context shadow runner, semantic
  executor, and optional runtime hooks. `all` now grants broad validated
  semantic authority over target selection, movement/open-view actions, global
  and leader-summit chat, leadership seeking, hostage selection, and the
  whisper-local entry/first-message hook. It still lacks rich saved-context
  export from live traces, deeper multi-turn whisper exchange control, and
  mixed-policy evaluation.

### Latest Validation

- `PYTHONPATH=. .venv/bin/python -m pytest tests -q`:
  **615 passed, 5 skipped** on 2026-05-11 before the current rendezvous
  iteration.
- Focused post-change checks on 2026-05-13:
  `PYTHONPATH=. .venv/bin/python -m pytest tests/test_eurydice_stages.py tests/test_orpheus_stage4.py -q`
  passed with **273 passed**. Earlier in the rendezvous iteration, the broader
  Eurydice/Orpheus focused set passed with **299 passed**:
  `tests/test_eurydice_stages.py tests/test_orpheus_stage4.py tests/test_eurydice_llm_runtime.py tests/test_eurydice_knowledge.py tests/test_eurydice_directives.py tests/test_eurydice_evaluators.py`.
- Live guarded-Haiku diagnostics, 10 Eurydice agents against a local default
  Persephone server (`seed=5305`, `--llm-control all --llm-provider haiku`):
  runs `after86` through `after93` still ended in draws, but `after92` produced
  the first current-session server-confirmed key interaction:
  `/Users/jamesboggs/coding/bitworld/persephones_escape/logs/1778608290610/full.log`
  recorded `R.CRCL joined P.CROSS's whisper` at 83.8s and `P.CROSS offered role
  exchange` at 96.9s. Final server state remained `Hades/Cerberus shared:
  false, Persephone/Demeter shared: false, same room: false`.
- The unsafe blind requester-accept experiment in `after93` was reverted:
  `/Users/jamesboggs/coding/bitworld/persephones_escape/logs/1778608787558/full.log`
  showed requesters opening their own whispers (`B.SQR opened whisper`,
  `R.CRCL opened whisper`) instead of safely accepting an existing joined
  whisper. Requester role-exchange acceptance must not press menu actions from
  ordinary gameplay unless a whisper-like view or another safe server signal is
  available.
- A bounded frame-recorded `after94` diagnostic (`seed=5305`, 242 MB of frames)
  still drew. Server log
  `/Users/jamesboggs/coding/bitworld/persephones_escape/logs/1778609737606/full.log`
  showed solo opener role offers (`P.CROSS offered role exchange`, `O.STAR
  offered role exchange`) but no joins. Frame inspection around the key
  rendezvous showed local policies still saw `PLAYING` pixels while server
  whisper state was hidden, and trace timing showed requester B retries could
  cancel a pending request before the opener finished the next `GRANT` menu
  sequence. Entry retries were therefore widened to 72 ticks with a bounded
  retry window.
- Live guarded-Haiku validation after the blind-grant hold change (`after96`,
  `seed=5305`) still drew:
  `/Users/jamesboggs/coding/bitworld/persephones_escape/logs/1778611539507/full.log`
  showed `O.STAR opened whisper`, `P.CROSS opened whisper`, and a Demeter
  whisper message, but no `joined`, `shared roles`, or winner. The change
  reduced wasted solo role-offer churn, but the remaining blocker is now below
  strategy: requester B pulses near open key whispers are still not reliably
  becoming server pending-entry state that the opener can grant.
- Latest long-running seed-5305 validation after requester blind-offer and
  persisted in-whisper key state produced eight completed server logs
  (`1778630780053`, `1778637451726`, `1778661827150`, `1778686766602`,
  `1778689320983`, `1778689514089`, `1778689707094`, `1778689900090`). Every
  log ended `Winner: Draw` with `Hades/Cerberus shared: false` and
  `Persephone/Demeter shared: false`; none contained server `joined`,
  `offered role`, or `shared roles` events. Agent traces did reach
  `BlindOfferRoleExchangeTask` on key roles, so the next debugging target is
  the request/grant/menu transport path from agent-side blind role-offer tasks
  to server-confirmed whisper state.
- Live full-match validation, 10 Eurydice agents against a local default
  Persephone server (`seed=4243`): server result was **Draw** with
  `Hades/Cerberus shared: false`, `Persephone/Demeter shared: false`, and
  `same room: true`. Trace analyzer scanned 10 logs, 166,300 events, 0
  malformed lines, and no unknown event types. Agents selected 72 probe
  targets, started 41 probe attempts (`30 whisper_created`, `11
  entry_requested`), completed 6 probes, and logged 34 `initiate_timeout`
  failures. The server `full.log` recorded no `joined`, `shared roles`,
  `offered role exchange`, or `exchanged colors` events. This proves the
  remaining blocker is not random inactivity; it is failed rendezvous and
  server-confirmed interaction.
- Live full-match diagnostic, 10 Eurydice agents against a local default
  Persephone server (`seed=4242`): server result was **Draw** with no
  server-confirmed exchanges. Traces contained 43 `whisper_created`, 9
  `entry_requested`, 26 `probe_completed`, 47 `probe_failed`, and 11
  `whisper_exchange_outcome` events, but those exchange events were menu
  attempts and did not appear in the authoritative server log.
- Live strategy check, 10 Eurydice agents against a local default Persephone
  server (`seed=306`, stopped after early round-1 interaction): trace analyzer
  scanned 10 logs, 5,294 events, 0 malformed lines, and no unknown event
  types. Agents acquired role/team/round schedule, entered objectives including
  `find_key_partner` and `gather_intel`, selected 39 probe targets across 9
  unique player IDs, started 17 probe attempts, completed 3 probes, and logged
  11 `initiate_timeout` failures. This proves the agents do operate beyond
  idle/random conversation, but also makes probe-initiation reliability the
  next concrete bottleneck.
- Live smoke, 10 Eurydice agents against a local default Persephone server
  (`seed=48`, stopped after early interaction): trace analyzer scanned 10 logs,
  7,103 events, 0 malformed lines, and no unknown event types. No agent
  tracebacks or logged failure events were present, and no trace showed
  `InitiateWhisperTask` running in `hostage_select`.
- Live controlled Spy/Echo capture (`seed=101`, six-player config) produced
  `tests/fixtures/role_reveal_spy_echo_summary.npy`, which verifies Panel 2
  parsing of `Spy`, missing `Cerberus`, and
  `Echo of Cerberus -> Cerberus` against real renderer output.
- Live controlled schedule capture (`seed=102`, six-player config) produced
  `tests/fixtures/role_reveal_round_schedule_live.npy`, which verifies Panel
  3 parsing of non-default rows `[(25, 1), (40, 2), (75, 1)]` against real
  renderer output.
- A prior interrupted live run exposed an upstream server cleanup issue when
  clients with pending whisper entries are killed first
  (`Sim.tickWhispers` tried to clear `pendingWhisperEntry` on a disconnected
  player). Stopping the server before agents avoids that external cleanup bug.

---

## Validation Layers

Every phase below has two forms of validation:

1. **Pytest contracts** -- deterministic unit/integration tests that can run
   without a live server.
2. **Trace criteria** -- quantitative checks over live bot traces. These are
   required because the hardest failures are interaction failures, timing
   failures, and cross-agent coordination failures that unit tests cannot
   expose.

Recommended default command for focused Eurydice checks:

```sh
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_eurydice_stages.py \
  tests/test_eurydice_integration.py \
  tests/test_eurydice_llm_context.py \
  tests/test_eurydice_llm_validator.py \
  -q
```

The full suite should be run before large behavior merges:

```sh
PYTHONPATH=. .venv/bin/python -m pytest tests -q
```

---

## Phase 0: Documentation, Baseline Tests, and Trace Schema

**Goal:** Make the repo truthful before adding behavior. This phase does not
change agent strategy.

**Dependencies:** None.

**Implementation work:**

- [x] Update stale project docs and TODO entries so they match current source.
- [x] Add a short "Current Implementation Status" section to `DESIGN.md` or keep
  this plan as the canonical status document and link it from the README.
- Decide the canonical trace directory layout and trace event names for
  Eurydice live evaluation.
- [x] Add a trace-analysis skeleton script before depending on trace metrics in
  later phases. It may initially only validate manifests and count events.

**Pytest contracts to add or keep green:**

- `tests/test_eurydice_integration.py::test_policy_importable`
- `tests/test_eurydice_integration.py::test_all_evaluator_modes_in_registry`
- `tests/test_eurydice_integration.py::test_pipeline_survives_100_ticks_same_frame`
- `tests/test_eurydice_stages.py::test_meta_decide_logs_reason_and_strategic_change`
- Add `tests/test_eurydice_trace_schema.py::test_trace_event_names_are_known`
- Add `tests/test_eurydice_trace_schema.py::test_trace_analyzer_handles_empty_run`

**Trace criteria:**

- A 60-second small local run produces parseable JSONL logs.
- Every event has `type`, `tick` when applicable, and no non-JSON payloads.
- No crash or unhandled exception appears in agent output.

**Exit criteria:**

- Focused Eurydice tests pass.
- Documentation no longer claims missing features that source already provides.
- Trace analyzer can run on an empty or minimal trace directory.

---

## Phase 1: Perception Foundation

**Goal:** Provide the tactical layer with the observations it needs before
strategy depends on them.

**Dependencies:** Phase 0.

### 1A. Self Identity From Role Reveal

[x] Implemented with synthetic parser/belief tests. Still needs live-frame
validation once new role-card captures are available.

Extract own centered sprite color/shape from the role card and decode
`my_index`.

**Pytest contracts:**

- `tests/test_perception_unit.py::test_role_reveal_extracts_own_sprite_identity`
- `tests/test_orpheus_stage2.py::test_role_reveal_populates_self_color_shape_index`
- `tests/test_eurydice_stages.py::test_my_player_id_uses_role_reveal_identity`

**Trace criteria:**

- `my_index`, `my_color`, and `my_shape` are known before first Playing tick
  in at least 95% of role-reveal fixture/live runs.

### 1B. Round Schedule Parsing

[x] Implemented with synthetic parser/belief tests. Still needs live-frame
validation across config presets.

Parse role-reveal panel 3 into `round_schedule` as
`[(duration_secs, hostage_count), ...]`.

**Pytest contracts:**

- `tests/test_perception_unit.py::test_parse_round_schedule_rows`
- `tests/test_orpheus_stage2.py::test_role_reveal_populates_round_schedule`
- `tests/test_eurydice_stages.py::test_urgency_uses_parsed_schedule_not_default`

**Trace criteria:**

- In configs with non-default durations, `strategic_state_snapshot` reports
  urgency changes consistent with the parsed schedule.

### 1C. Plain Visible Player Sprites

[x] Implemented with synthetic parser/belief tests. Still needs live-frame
validation in obstacle/fog cases and across all shapes/colors.

Expose visible overworld player sprites even when they do not have speech
bubbles. This should include color, shape, screen/world position, and role
indicator if visible.

**Pytest contracts:**

- `tests/test_perception_unit.py::test_overworld_detects_visible_nonbubble_sprite`
- `tests/test_orpheus_stage2.py::test_overworld_updates_plain_visible_player_position`
- `tests/test_eurydice_stages.py::test_position_tracker_prefers_direct_sprite_over_minimap`

**Trace criteria:**

- During Playing, each bot has `localized: true` equivalent state from
  position perception within 200 ticks.
- Non-bubble nearby players update `PlayerInfo.position` on the current tick.
- Minimap-only identity guesses are used only when no direct sprite observation
  exists.

### 1D. Global Chat and Hostage Grid Fixtures

Capture and validate live fixtures for global messages, usurp candidate state,
hostage grid cursor, selection marks, and committed state.

**Pytest contracts:**

- `tests/test_perception_live.py::test_global_chat_message_fixture_parses_sender_and_text`
- `tests/test_perception_live.py::test_hostage_grid_fixture_parses_cursor_and_selected_slots`
- `tests/test_orpheus_stage2.py::test_global_chat_hostage_grid_updates_belief`

**Trace criteria:**

- In HostageSelect, a leader bot can see eligible hostage count and cursor.
- In GlobalChat, room messages are attributed when sender sprite is visible.

### 1E. Leader Detection

Improve leader-color inference beyond "self is leader" and usurp candidate
approximation.

**Pytest contracts:**

- `tests/test_perception_unit.py::test_overworld_detects_visible_leader_indicator`
- `tests/test_orpheus_stage2.py::test_visible_leader_updates_leader_colors`
- `tests/test_eurydice_stages.py::test_strategic_state_room_leader_from_confirmed_source`

**Trace criteria:**

- `room_leader_id` and `room_leader_team` are populated before any usurp or
  hostage strategy depends on them.

**Exit criteria for Phase 1:**

- Role, self identity, schedule, visible players, global chat, hostage grid,
  and leader fields are either populated from perception or explicitly absent
  with a trace warning.
- No later phase may depend on a perception field until its Phase 1 pytest
  contract is green.

---

## Phase 2: Knowledge and Inference Pipeline

**Goal:** Convert observations into reliable player knowledge before the
strategic layer uses it.

**Dependencies:** Phase 1A for self identity; Phase 1C for direct visible
player identity; Phase 1D for chat/hostage fields; Phase 1E for leadership.

**Implementation work:**

- Make `update_exchange_tracker` consume `last_exchange_event`,
  `active_color_offers`, `active_role_offers`, and `my_exchange_partner`
  instead of relying primarily on text-window heuristics.
- Add robust multi-occupant attribution rules: exact embedded player refs >
  target picker refs > two-person whisper > ambiguous event recorded without
  identity.
- Integrate `chat_parser.parse_message`, `assess_credibility`, and
  `update_knowledge_from_chat` in `update_chat_tracker`.
- Implement `update_leadership_tracker` from global/whisper system messages
  and confirmed leader perception.
- [x] Implement role-summary-driven match config: roles present, missing core
  roles, echo substitutions, and Spy present/absent. Exact role counts are not
  rendered by the source game panel.
- [x] Replace unconditional color-exchange confidence `1.0` with Spy-aware
  confidence.
- Defer elimination rules until exact role counts are available from a source
  other than the role-summary panel, or implement only conservative
  membership/missing-role constraints.
- [x] Add info-screen reconciliation after exchange-related whispers.
- Add info-screen reconciliation after hostage exchange if live traces show
  hostage-exchange role indicators are missed by the existing registry import.

**Pytest contracts:**

- `tests/test_eurydice_knowledge.py::test_exchange_tracker_consumes_structured_color_event`
- `tests/test_eurydice_knowledge.py::test_exchange_tracker_consumes_structured_role_event`
- `tests/test_eurydice_knowledge.py::test_ambiguous_multi_occupant_exchange_does_not_misatrribute`
- `tests/test_eurydice_knowledge.py::test_chat_parser_updates_low_priority_identity_claim`
- `tests/test_eurydice_knowledge.py::test_enemy_chat_claim_cannot_overwrite_mechanical_exchange`
- `tests/test_eurydice_knowledge.py::test_exchange_tracker_schedules_info_screen_reconciliation`
- `tests/test_eurydice_knowledge.py::test_info_screen_reconciles_full_role_exchange`
- `tests/test_eurydice_knowledge.py::test_info_screen_reconciles_color_only_without_role`
- `tests/test_perception_unit.py::TestRoleReveal::test_parse_frame_parses_role_summary_spy_missing_and_echo`
- `tests/test_orpheus_stage2.py::test_role_reveal_populates_match_config`
- `tests/test_eurydice_knowledge.py::test_color_exchange_confidence_lower_when_spy_possible`
- `tests/test_eurydice_knowledge.py::test_leadership_tracker_records_usurp_and_transfer`
- `tests/test_eurydice_knowledge.py::test_elimination_waits_for_role_counts`
  (deferred until exact counts have a source)
- `tests/test_eurydice_knowledge.py::test_round_reset_preserves_cross_round_identity`

**Trace criteria:**

- Every completed mechanical exchange produces exactly one knowledge update.
- No trace shows a lower-confidence chat claim overwriting role-exchange truth.
- Leadership changes appear in `strategic_state_change` within 24 ticks of
  being visible.
- Unknown/ambiguous multi-occupant exchange events are logged as ambiguous
  instead of attributed to the wrong player.

**Exit criteria:**

- `StrategicState` can rely on team, role, trust, room, leadership, and key
  exchange fields without reparsing chat text.
- Known information has provenance and confidence.

---

## Phase 3: Directive Parameters and Strategic Objectives

**Goal:** Make evaluator intent reach modes. This is the main architectural
blocker for the full design.

**Dependencies:** Phase 2 knowledge fields.

**Implementation work:**

- Introduce typed params for strategic modes:
  `ProbeTargetParams`, `ProbeSystematicParams`, `HoldPositionParams`,
  `CoordinateCrossRoomParams`, `SeekLeadershipParams`,
  `HostageSelectParams`, `SummitInteractParams`, `RelayIntelligenceParams`,
  `TimeWasteParams`, `DecoyParams`, and `InWhisperParams` if needed.
- Update `ModeRegistry` registrations so each mode accepts the params it
  actually uses.
- Make evaluators return params with target team, target player, objective,
  protocol, urgency posture, and safety flags.
- Populate `StrategicState.current_objective`.
- Persist the last full `ModeDirective`, not just the last mode name, so
  hysteresis preserves params.
- Add directive serialization to traces so branch decisions are auditable.

**Pytest contracts:**

- `tests/test_eurydice_directives.py::test_hades_partner_unknown_sets_find_partner_probe_params`
- `tests/test_eurydice_directives.py::test_persephone_partner_unknown_sets_cautious_probe_params`
- `tests/test_eurydice_directives.py::test_demeter_partner_unknown_sets_aggressive_probe_params`
- `tests/test_eurydice_directives.py::test_time_waste_directive_sets_stall_protocol`
- `tests/test_eurydice_directives.py::test_hysteresis_preserves_directive_params`
- `tests/test_eurydice_directives.py::test_mode_registry_param_types_accept_evaluator_directives`

**Trace criteria:**

- `meta_decide_reason` includes directive params or a compact param summary.
- No mode receives bare `ModeParams` when the evaluator branch requires intent.
- Reaffirmed directives during min-duration hold preserve the original params.

**Exit criteria:**

- All evaluator branches can express the behavior they intend.
- No later phase relies on implicit global state for behavior that belongs in
  the directive params.

---

## Phase 4: Probe and Whisper Rendezvous Reliability

**Goal:** Get agents into the same whisper reliably enough that strategic
protocols can matter.

**Dependencies:** Phase 1C visible sprites; Phase 3 directive params.

**Implementation work:**

- [x] Rework probe approach so create-vs-join is target-scoped: request entry
  only when the selected target is currently in a whisper; otherwise create or
  approach the selected target.
- [x] Track failed entry attempts per target and cap reattempts per round.
- [x] Grant the first requester into a solo whisper, and grant the intended
  target into a key-exchange whisper, even when the FSM is already in a
  sensitive exchange state.
- [ ] Add cooperative meeting-point behavior for Eurydice-vs-Eurydice games.
- [ ] Optionally use short global announcements for whisper location when safe.
- [x] Prevent probe modes from initiating new whisper actions outside Playing
  except for pending-entry cancellation.
- [x] Add trace events: `probe_target_selected`, `probe_attempt_started`,
  `whisper_created`, `entry_requested`, `entry_granted`, `probe_failed`,
  `probe_completed`.

**Pytest contracts:**

- `tests/test_eurydice_stages.py::test_probe_systematic_score_prefers_unprobed`
- `tests/test_eurydice_stages.py::test_probe_systematic_score_excludes_failed_target_this_round`
- `tests/test_eurydice_stages.py::test_probe_target_in_range_whisper_requests_entry`
- `tests/test_eurydice_stages.py::test_probe_target_does_not_join_unrelated_nearby_whisper`
- `tests/test_eurydice_stages.py::test_probe_systematic_does_not_join_fully_verified_nearby_whisper`
- `tests/test_eurydice_stages.py::test_probe_waiting_entry_timeout_cancels_and_records_failure`
- `tests/test_eurydice_stages.py::test_probe_tracker_marks_completion_when_whisper_reached`
- `tests/test_eurydice_stages.py::test_probe_systematic_does_not_initiate_in_hostage_select`

**Trace criteria:**

- In small 4-agent Eurydice-vs-Eurydice runs, at least 70% of probe attempts
  reach `View.WHISPER` within 15 seconds.
- In full 10-agent self-play, the server log should show at least one `joined`
  whisper event by round 1 and at least one server-confirmed role/color offer
  or exchange by round 2. The current 2026-05-12 runs reached the `joined`
  portion once (`after92`) and reached a server-confirmed role offer, but still
  did not complete a role/color exchange or produce a winner.
- Median time from target selection to whisper view is below one third of the
  current round duration.
- Failed attempts switch target or strategy within 96 ticks after failure.

**Exit criteria:**

- The bot can create or request target-scoped whispers without repeatedly
  hammering failed targets or initiating probe actions during phase-transition
  surfaces.
- Later role strategy can assume "probe target" often leads to an actual
  conversation, not just wandering or solo whispers.

---

## Phase 5: Whisper Protocol Semantics

**Goal:** Make the `in_whisper` FSM perform the correct protocol for the
current objective.

**Dependencies:** Phase 2 structured exchange knowledge; Phase 3 directive
params; Phase 4 rendezvous reliability.

**Implementation work:**

- [x] Wire protocol selection from directive/objective into
  `WhisperModeState`.
- [x] Preserve the last non-whisper directive so `in_whisper` can recover the
  intent that caused entry despite the phase override.
- [x] Make same-team known partners escalate to role exchange when objective is
  `FIND_KEY_PARTNER` or `COMPLETE_KEY_EXCHANGE`; same-team unknown candidates
  still require color exchange first.
- [x] Implement role-specific incoming `R.OFFER` decisions, including Spy
  behavior for verified ally, same-team panic, and enemy rejection.
- [x] Add quick-verify and infiltration protocol variants.
- [x] Add info-screen reconciliation after possible role exchange.
- [x] Make `time_waste` set stall protocol and verify `STALL` is actually
  entered.
- [x] Add explicit cleanup on forced ejection and phase transition.

**Pytest contracts:**

- `tests/test_eurydice_stages.py::test_time_waste_directive_enters_stall_protocol`
- `tests/test_eurydice_stages.py::test_probe_key_partner_directive_enters_key_exchange_protocol`
- `tests/test_eurydice_stages.py::test_key_role_exits_when_hostile_third_occupant_present`
- `tests/test_eurydice_stages.py::test_spy_rejects_enemy_role_offer`
- `tests/test_eurydice_stages.py::test_spy_accepts_verified_ally_role_offer`
- `tests/test_eurydice_stages.py::test_infiltration_extracts_from_enemy_without_role_offer`
- `tests/test_eurydice_stages.py::test_stall_protocol_sends_delayed_messages`
- `tests/test_eurydice_stages.py::test_forced_ejection_sets_mode_complete`

**Trace criteria:**

- Every whisper has a visible FSM path from `ENTER` to terminal exit reason.
- Key roles searching for partners perform role exchange with same-team
  candidates instead of exiting after color exchange.
- Role exchange completion updates `key_exchange_done` within 24 ticks.
- Standard protocol exits within configured timeout.
- Stall protocol keeps target occupied for at least 6 seconds on average.

**Exit criteria:**

- Key exchange is mechanically achievable by the runtime, not just described
  in evaluator branches.

---

## Phase 6: Full Role Evaluators

**Goal:** Implement the role strategy documents as priority-ordered evaluator
branches with typed params.

**Dependencies:** Phase 2 knowledge; Phase 3 params/objectives; Phase 5
working role-exchange protocol.

**Implementation work:**

- [ ] Implement the documented Hades, Cerberus, Persephone, Demeter, Shade,
  Nymph, and Spy priority chains end to end. Core key-role partner branches are
  now covered; grunt/Spy late-game behavior remains partial.
- [x] Add P_FINAL override for key roles when partner exchange is still
  incomplete and partner is unreachable in the final round.
- [x] Make evaluator outputs explainable: branch name, objective, target,
  confidence, and reason.
- Avoid role evaluators depending on leadership/hostage/deception features not
  yet implemented; when they need those features, they should emit modes whose
  Phase 7/8 tests are already green.

**Pytest contracts:**

- `tests/test_eurydice_directives.py::test_hades_partner_local_probe_target_has_key_exchange_params`
- `tests/test_eurydice_directives.py::test_persephone_partner_unknown_uses_cautious_same_team_probe`
- `tests/test_eurydice_directives.py::test_demeter_partner_unknown_uses_aggressive_same_team_probe`
- `tests/test_eurydice_evaluators.py::test_hades_partner_other_room_seeks_leadership`
- `tests/test_eurydice_evaluators.py::test_cerberus_partner_other_room_coordinates_cross_room`
- `tests/test_eurydice_evaluators.py::test_persephone_partner_other_room_holds_defensively`
- `tests/test_eurydice_evaluators.py::test_persephone_enemy_local_and_exchange_likely_coordinates_escape`
- `tests/test_eurydice_evaluators.py::test_shade_leader_with_key_roles_need_help_selects_hostage_strategy`
- `tests/test_eurydice_evaluators.py::test_spy_no_verified_ally_verifies_with_real_team_candidate`
- `tests/test_eurydice_evaluators.py::test_final_partner_unreachable_fires_only_final_round`

**Trace criteria:**

- Key roles spend early game mostly in partner-search objectives until exchange
  completion.
- After exchange, Hades and Persephone shift to positioning objectives.
- Grunts spend early game mapping room composition and later shift to
  protection, relay, disruption, or leadership.
- Spy first establishes a verified ally, then infiltrates or relays depending
  on cover status.

**Exit criteria:**

- Evaluator behavior matches the role strategy documents for all major
  branches in deterministic unit tests.

---

## Phase 7: Leadership, Hostage, Summit, and Cross-Room Control

**Goal:** Make room movement and leadership strategy real enough to support
late-game positioning.

**Dependencies:** Phase 1D hostage/global fixtures; Phase 1E leader detection;
Phase 3 params; Phase 6 evaluator branches that invoke these modes.

**Implementation work:**

- Refine `VoteUsurpTask` navigation so it selects the intended candidate.
- Refine `SelectHostagesTask` cursor navigation against live hostage-grid
  frames.
- Implement role-aware `HostageSelectParams`: keep own exchanged key role safe,
  move enemy key roles, honor verified ally `SEND ME`, and avoid sending
  Persephone into Hades unless strategically necessary.
- Expand `hold_position` to optionally seek leadership, grant ally entries,
  avoid hostage danger, and maintain non-suspicious movement.
- Expand `summit_interact` to probe, misdirect, tab to info, and relay relevant
  room information.
- Expand `coordinate_cross_room` to choose between self-volunteer, ally
  volunteer, leader hostage selection, or summit negotiation.

**Pytest contracts:**

- `tests/test_eurydice_leadership.py::test_vote_usurp_task_navigates_to_target_candidate`
- `tests/test_eurydice_hostage.py::test_select_hostages_task_moves_cursor_and_commits`
- `tests/test_eurydice_hostage.py::test_hostage_select_never_sends_own_exchanged_key_role`
- `tests/test_eurydice_hostage.py::test_hostage_select_honors_verified_send_me_request`
- `tests/test_eurydice_hostage.py::test_persephone_hold_position_avoids_hostage_when_at_risk`
- `tests/test_eurydice_summit.py::test_summit_sends_probe_then_tabs_info`
- `tests/test_eurydice_cross_room.py::test_coordinate_cross_room_selects_meaningful_local_action`

**Trace criteria:**

- In HostageSelect as leader, chosen hostages match the evaluator objective.
- Usurp attempts happen only when vote math makes success plausible.
- Leader summit always produces at least one strategic message and does not try
  disabled mechanical whisper actions.
- Across rounds, key-pair room distance improves when cross-room coordination
  is active.

**Exit criteria:**

- The agent can intentionally influence room composition instead of merely
  hoping hostage exchange helps.

---

## Phase 8: Communication Protocol

**Goal:** Make chat messages actionable without allowing unreliable claims to
corrupt mechanical truth.

**Dependencies:** Phase 1D global chat fixtures; Phase 2 knowledge pipeline.

**Implementation work:**

- Wire `chat_parser` into the runtime.
- Add outbound message templates with priority, cooldown, audience, and
  channel constraints.
- Add message budgeting per round.
- Implement `relay_intelligence` as real targeted behavior: choose recipient,
  choose channel, send compact intel, and mark it relayed.
- Add safeguards: no global messages while in whisper, no low-priority message
  if a high-priority message is pending, no repeated identical spam.

**Pytest contracts:**

- `tests/test_eurydice_chat.py::test_parse_identity_claim_variants`
- `tests/test_eurydice_chat.py::test_parse_action_request_send_me`
- `tests/test_eurydice_chat.py::test_verified_ally_claim_updates_chat_claim_source`
- `tests/test_eurydice_chat.py::test_enemy_claim_is_recorded_but_not_trusted`
- `tests/test_eurydice_chat.py::test_message_budget_blocks_low_priority_spam`
- `tests/test_eurydice_chat.py::test_global_message_not_sent_in_whisper`
- `tests/test_eurydice_chat.py::test_relay_intelligence_marks_intel_as_relayed`

**Trace criteria:**

- Important discovered intel is relayed to a relevant ally before it becomes
  stale.
- The agent sends few, high-value messages instead of constant chatter.
- No trace shows a chat claim overwriting mechanical exchange or info-screen
  evidence.

**Exit criteria:**

- Chat improves team coordination and inference without becoming a source of
  high-confidence falsehoods.

---

## Phase 8.5: LLM Shadow Control

**Goal:** Prepare LLM-assisted social strategy without letting the model drive
buttons or overwrite mechanical facts.

**Dependencies:** Phase 0 trace schema; Phase 2 knowledge pipeline; Phase 4
probe lifecycle events; Phase 5 whisper protocol semantics; Phase 8 message
budgets and outbound channel constraints.

**Implementation work:**

- Keep `llm_context.py` as the canonical input/output contract:
  `build_llm_context(...)` for model inputs and `llm_decision_schema()` for
  outputs.
- [x] Add a deterministic validator for model decisions: current-view legality,
  target existence, message ASCII/length, reveal constraints, and fallback
  action.
- [x] Add shadow-mode trace event support: `llm_context`, `llm_decision`,
  `llm_decision_rejected`, and `llm_decision_accepted`.
- [x] Add a saved-context runner that evaluates full context JSON/JSONL packets
  and stores aggregate model-vs-rule comparisons.
- [x] Add strategic prompt templates for probe target choice, whisper
  reveal/message choice, global room message choice, leader-summit requests,
  hostage selection, and broad semantic actions.
- [x] Add deterministic `hold` and `heuristic` providers behind explicit
  config flags.
- [x] Add an opt-in standard-library AWS Bedrock Claude Haiku provider behind
  `--llm-provider haiku|bedrock`, with SigV4 signing, AWS/container/CLI
  credential resolution, JSON parsing, timeout fallback, and call cooldowns.
- [x] Add a semantic executor and registered `llm_action` mode for accepted
  decisions that map to existing Orpheus tasks.
- [x] Add optional runtime target-selection control behind
  `--llm-control targets` / `all`.
- [x] Add the first mode-local whisper hook for pending-entry and first-message
  decisions behind `--llm-control whispers` / `all`.
- [x] Expand `--llm-control all` to every validated executor-backed semantic
  action in the current view, including global chat, leader-summit chat,
  movement/open-view actions, leadership seeking, and hostage selection.
- [ ] Add richer live context export and model-vs-rule evaluation metrics.

**Pytest contracts:**

- `tests/test_eurydice_llm_context.py::test_llm_context_is_json_serializable_and_namespaced`
- `tests/test_eurydice_llm_context.py::test_llm_context_whisper_actions_include_exchange_controls`
- `tests/test_eurydice_llm_context.py::test_llm_context_exposes_hostage_options`
- `tests/test_eurydice_llm_context.py::test_llm_decision_schema_is_closed_and_action_bounded`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_action_illegal_for_current_view`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_hostage_targets_not_matching_grid`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_wrong_hostage_target_count`
- `tests/test_eurydice_llm_validator.py::test_validator_accepts_hostage_option_even_when_player_not_visible`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_false_first_person_key_role_claim`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_false_implied_here_role_claim`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_unsupported_role_possession_claim`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_role_reveal_to_known_enemy`
- `tests/test_eurydice_llm_validator.py::test_validator_allows_role_reveal_to_enemy_for_disruption_objective`
- `tests/test_eurydice_llm_validator.py::test_validator_rejects_color_reveal_when_spy_risk_active`
- `tests/test_eurydice_llm_validator.py::test_validate_and_trace_emits_shadow_events`
- `tests/test_eurydice_llm_shadow.py`
- `tests/test_eurydice_llm_provider.py`
- `tests/test_eurydice_llm_executor.py`
- `tests/test_eurydice_llm_runtime.py`

**Trace criteria:**

- Shadow decisions parse on more than 99% of sampled contexts.
- Rejected decisions are categorized, not silently ignored.
- Probe recommendations point at known/visible targets unless the model
  explicitly chooses to scout or open global.
- Suggested messages are short, relevant to the objective, and non-spammy.
- No accepted decision violates a hard constraint.

**Exit criteria:**

- Shadow-mode LLM suggestions are measurably useful enough to test behind a
  constrained runtime flag on one control surface.

---

## Phase 9: Deception and Spy

**Goal:** Implement Spy and deception after honest communication and mechanical
exchange are reliable.

**Dependencies:** Phase 2 Spy-present config knowledge; Phase 5 whisper
protocols; Phase 6 role evaluators; Phase 8 communication. LLM control is not
required for initial deception work, but Phase 8.5 should be used before any
model-authored deception reaches runtime.

**Implementation work:**

- Store `DeceptionState` in belief extra and update it from outbound claims
  and mechanical reveals.
- Make Spy cover team/role explicit in strategic state.
- Implement Spy verified-ally phase: find a real-team candidate, role-exchange
  safely, and mark the ally verified.
- Implement infiltration protocol: reinforce cover through color exchange,
  avoid role reveal with enemies, extract intel, then exit.
- Implement decisive cover break when leadership, hostage selection, or intel
  relay is worth more than continued cover.
- Implement grunt decoy behavior and key-role camouflage only where expected
  value is positive.

**Pytest contracts:**

- `tests/test_eurydice_deception.py::test_spy_cover_team_is_opposite_visible_team`
- `tests/test_eurydice_deception.py::test_spy_verified_ally_target_uses_real_team_logic`
- `tests/test_eurydice_deception.py::test_spy_infiltration_never_accepts_enemy_role_offer`
- `tests/test_eurydice_deception.py::test_cover_blown_after_inconsistent_claim_to_same_target`
- `tests/test_eurydice_deception.py::test_decoy_records_projected_identity`
- `tests/test_eurydice_deception.py::test_deception_never_contradicts_mechanical_reveal`

**Trace criteria:**

- Spy maintains cover through at least two rounds when not forced to reveal.
- Spy establishes one verified real ally in more than 50% of reachable games.
- Spy relays at least one high-value intel item to the real team in medium
  configs.
- Decoy mode draws enemy interaction or consumes enemy time without corrupting
  allied knowledge.

**Exit criteria:**

- Spy behavior is strategically distinct from generic grunt behavior and does
  not accidentally self-reveal through the standard role-exchange path.

---

## Phase 10: End-to-End Regression and Tuning

**Goal:** Prove the whole design works across configs, roles, and seeds.

**Dependencies:** Phases 1-9, though the harness should be built
incrementally starting in Phase 0.

**Implementation work:**

- Build `scripts/analyze_eurydice_traces.py`.
- Build a reproducible run matrix over configs and seeds.
- Store aggregate summaries, not giant raw traces, in documentation.
- Tune weights and thresholds only after the trace scanner can detect
  regressions.

**Trace metrics:**

- Role detection latency.
- Self identity detection latency.
- Parsed round schedule availability.
- Probe attempts, successes, failures, median time to whisper.
- Color exchange attempts and completions.
- Role exchange attempts and completions.
- Key exchange completion rate by role and config.
- Mode time distribution by role.
- Whisper FSM terminal reasons.
- Leadership attempts, successes, and false attempts.
- Hostage selections and safety invariant violations.
- Spy cover status and cover break causes.
- Messages sent by priority/channel.
- Stuck-state count: mode active longer than limit without progress.
- Crashes or disconnects.

**Safety invariants:**

- Never send own exchanged key role as hostage.
- Persephone never role-exchanges with confirmed enemy.
- Hades never voluntarily moves away from a completed favorable
  Hades-Persephone co-location without a stronger reason.
- Spy never accepts enemy role exchange while cover is valuable.
- Chat claims never overwrite stronger mechanical knowledge.
- No mode persists more than 300 Playing ticks without progress unless it is an
  intentional hold/stall with a logged reason.
- All agents recover cleanly from forced whisper ejection.

**Run matrix:**

- Small iteration: 4 agents, 1 imposter-equivalent role mix if supported by
  config, 3 seeds, short duration.
- Default pressure: default 15-second rounds, 10 agents, 5 seeds.
- Medium strategy: medium descending rounds, 10 agents, 10 seeds.
- Baseline comparison: Eurydice team against baseline fillers, 10 seeds.
- Self-play balance: all Eurydice, 20 seeds.

**Final acceptance criteria:**

- Focused and full pytest suites pass.
- Zero safety invariant violations across the regression trace set.
- Key exchange completes in at least 70% of games where partner is reachable.
- Eurydice beats baseline fillers in more than 60% of comparable games.
- Eurydice-vs-Eurydice self-play is roughly balanced, unless config asymmetry
  explains the skew.
- Trace analyzer produces a concise report that explains failures by phase:
  perception, probe, whisper, evaluator, leadership/hostage, communication, or
  deception.

---

## Dependency Graph

```text
Phase 0: Docs, baseline tests, trace schema
  -> Phase 1: Perception foundation
      -> Phase 2: Knowledge and inference
          -> Phase 3: Directive params and objectives
              -> Phase 4: Probe/rendezvous reliability
                  -> Phase 5: Whisper protocol semantics
                      -> Phase 6: Full role evaluators
                          -> Phase 7: Leadership/hostage/cross-room
                          -> Phase 8: Communication protocol
                              -> Phase 8.5: LLM shadow control
                              -> Phase 9: Deception and Spy
                                  -> Phase 10: End-to-end regression
```

Phase 7 and Phase 8 can proceed in parallel after Phase 6 defines stable
directive interfaces. Phase 8.5 can start in shadow mode as soon as the
context contract exists, but runtime LLM control should wait for the relevant
Phase 8 communication safeguards. Phase 9 should not start until Phase 8 is
reliable, because deception depends on knowing what honest communication would
have done.

---

## Development Rule

For each phase:

1. Add or update pytest contracts first, marking future-only tests `xfail` only
   when they document a known unimplemented behavior and are not part of the
   normal green suite.
2. Implement the smallest capability needed to make the phase contracts pass.
3. Run focused tests.
4. Run a live trace scenario that exercises the new behavior.
5. Update docs in the same change if behavior diverges from `DESIGN.md`.
6. Only then let later phases depend on the new capability.
