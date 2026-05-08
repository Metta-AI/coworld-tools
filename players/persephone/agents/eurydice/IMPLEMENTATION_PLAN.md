# Eurydice -- Implementation Plan

High-level roadmap for implementing the Eurydice strategic agent as
specified in [DESIGN.md](DESIGN.md). Eurydice sits on top of the Orpheus
framework and adds a rule-based strategic reasoning layer that plays all
7 roles competently. Each stage builds on the previous; the dependency
graph at the bottom shows parallelization opportunities.

---

## Stage 0: Core Data Types & Knowledge Model

**Goal**: Define the data structures that every other component reads and
writes. No logic -- just shapes.

1. **`types.py`** -- Eurydice-specific enums and constants: `Team`,
   `Role`, `TrustLevel`, `Urgency`, `ProbeIntent`, `Phase` (extended
   from Orpheus), `TeamSource`, `RoleSource`, `Objective`. `PlayerID`
   typedef (`tuple[int, int]` for color + shape).
2. **`knowledge.py`** -- `PlayerKnowledge` frozen/mutable dataclass with
   all fields from DESIGN.md section "Player Knowledge Record." Include
   factory method for initial state (all `None`/empty).
3. **`strategic_state.py`** -- `StrategicState` dataclass with all fields
   from DESIGN.md section "Strategic State." Read-only after construction
   (rebuilt each `meta_decide` cycle).
4. **`accumulators.py`** -- `PlayerAccumulator` and `GlobalAccumulators`
   dataclasses. Include `reset_for_new_round` method on
   `PlayerAccumulator`. `WhisperRecord` for our own history.
5. **`ext_keys.py`** -- Central registry of all `belief_state.ext` keys
   with type annotations and docstrings (prevents typo collisions). From
   DESIGN.md "Belief State Extension Keys Registry" table.
6. **`whisper_state.py`** -- `WhisperModeState` and
   `WhisperExchangeState` dataclasses for the whisper FSM.
7. **`communication.py` (types only)** -- `ParsedMessage`,
   `IdentityClaim`, `LocationClaim`, `ActionRequest`, `Question`
   dataclasses.

**Exit criterion**: All dataclasses importable and constructible with
defaults. `StrategicState` and `PlayerKnowledge` can be round-tripped
through `dataclasses.asdict`. Type-checking (`mypy --strict` or
equivalent) passes on all type modules.

---

## Stage 1: Behavioral Accumulation & Inference Pipeline

**Goal**: The `post_belief_update` hook runs every tick, feeds raw
observations into accumulators, derives behavioral flags, and runs
inference rules to populate `PlayerKnowledge`.

1. **Hook registration** -- Register `eurydice_post_belief_update` as an
   agent-level `post_belief_update` hook via the Orpheus `HookRegistry`.
   Initialize `GlobalAccumulators` and `player_knowledge` dict in
   `belief_state.ext` during mode_enter or game-start detection.
2. **Position tracker** -- `update_position_tracker`: feed visible player
   positions from `belief_state.players` into per-player ring buffers.
   Track `visible_ticks_this_round`, `stationary_ticks`,
   `total_distance_this_round`, `distinct_players_approached`.
3. **Whisper tracker** -- `update_whisper_tracker`: detect whisper
   entry/exit from belief state (speech bubbles, occupant lists). Track
   `whisper_entries_this_round`, `whisper_partners_this_round`.
   Implement proximity-based partnership inference (confidence ~0.7).
4. **Exchange tracker** -- `update_exchange_tracker`: scan
   `chat_history` for system messages ("offered color", "swapped
   colors", "offered role", "shared roles", "withdrew", "showed role").
   Update per-player exchange counters and `ticks_before_first_offer`.
   Implement OCR-resilient substring matching (match on "SWAP",
   "SHARED", "OFFER" fragments).
5. **Chat tracker** -- `update_chat_tracker`: attribute incoming
   messages to senders, increment `global_messages_sent_this_round`,
   append to `message_content_log`.
6. **Leadership tracker** -- `update_leadership_tracker`: detect usurp
   votes, leadership changes from system messages.
7. **Behavioral flag derivation** -- `derive_behavioral_flags`: implement
   all flag rules from DESIGN.md ("aggressive_probing",
   "avoids_interaction", "defensive_posture", "exchange_eager",
   "refuses_role_exchange", "seeks_specific_teammate", "chatty_global",
   "relaxed_after_urgency", "whispers_with_both_teams").
8. **Hard inference rules** -- Certainty-1.0 updates: mutual role
   exchange, color exchange (with Spy-config conditional confidence),
   one-way reveals, room assignment from visibility, roster reveal,
   hostage movement.
9. **Soft inference rules** -- Probabilistic updates from behavioral
   flags with capped confidence values per DESIGN.md.
10. **Elimination rules** -- Deductive reasoning from known-identity
    counts.
11. **Round-reset logic** -- On round transition (detected from belief
    state phase change): snapshot cross-round summaries, reset per-round
    fields, handle hostage arrivals/departures.

**Exit criterion**: Unit tests with synthetic belief state sequences
verify: (a) accumulators increment correctly over multi-tick sequences,
(b) behavioral flags fire at specified thresholds, (c) hard inferences
produce correct knowledge updates from exchange events, (d) round reset
preserves cross-round fields and clears per-round fields. Tested with
at least 3 scenario sequences (cooperative probe, evasive target,
multi-round progression).

---

## Stage 2: meta_decide Engine

**Goal**: The outer-loop `meta_decide` function builds strategic state,
dispatches to role evaluators, implements hysteresis, and computes
urgency. Produces `ModeDirective` values that the inner loop consumes.

1. **`build_strategic_state`** -- Reconstruct `StrategicState` from a
   belief state snapshot each iteration. Populate all fields: identity,
   temporal (round, phase, urgency), key exchange status, room
   composition, leadership, interaction tracking, scaling parameters.
2. **Temporal mechanics** -- `RoundBudget` tracker: `ticks_remaining`,
   `can_start_full_probe`, `can_start_fast_probe`,
   `probes_remaining_estimate`. Derive `probe_cycle_cost_ticks` from
   `belief_state.round_schedule` (not hardcoded). Handle descending-
   duration configs (medium family).
3. **Urgency computation** -- `compute_urgency`: implement relative
   urgency using `rounds_remaining` and `fraction_elapsed` per DESIGN.md
   algorithm. Must work across all config presets (1-5 rounds,
   15s-300s durations).
4. **Hysteresis** -- Minimum mode duration (48 ticks unless critical
   override). Never interrupt `in_whisper`. Anti-thrash cooldown on
   re-entry. `is_critical_override` (phase change, exchange completed,
   partner discovered).
5. **Role dispatch table** -- `ROLE_EVALUATORS` dict mapping `Role` enum
   to evaluator functions. Stub evaluators that return `scout` mode for
   now (real logic in Stage 5).
6. **Mode completion protocol** -- Read `belief_state.ext["mode_complete"]`
   flag; clear after reading. Route to next priority.
7. **Phase-sensitive overrides** -- HostageSelect (leader -> hostage_select
   mode), LeaderSummit (leader -> summit_interact), HostageExchange/
   RoleReveal/RosterReveal (-> idle). These override role logic.
8. **Intro sequence behavior** -- Slow panel advancement: 48 ticks on
   RosterReveal, 24 ticks per RoleReveal panel. Output idle (0x00) to
   prevent accidental advancement. Detect panel transitions from belief
   state population (player registry complete -> advance).

**Exit criterion**: Given a mocked belief state with known role, round,
and phase, `meta_decide` produces the expected `ModeDirective` for:
(a) intro sequence pacing, (b) phase overrides (HostageSelect triggers
hostage_select mode for leaders), (c) hysteresis suppresses rapid
switching, (d) urgency correctly computes CALM/PRESSING/PANIC for
various round/config combinations.

---

## Stage 3: Basic Modes (idle, scout, probe_target, probe_systematic)

**Goal**: The agent can move through the room, find players, and approach
them for whisper initiation. These modes form the "getting to the
conversation" layer.

1. **`idle` mode** -- Returns `IdleTask()`. Monitors belief state for
   phase transitions. Absorbs perception passively.
2. **`scout` mode** -- Internal `ScoutState`. Waypoint selection
   algorithm (priority: last-known positions of unprobed players >
   unexplored regions > room center). Weighted random choice. Stuck
   detection (72-tick stale waypoint). Signals `mode_complete` +
   `found_target` when unprobed player is within interaction range.
3. **`probe_target` mode** -- Approach specific player via `MoveToTask`.
   Fall back to last-known position if target not visible. Create
   whisper (`CreateWhisperTask`) or request entry
   (`RequestEntryTask`) depending on target's whisper state.
   `max_approach_ticks` timeout. Probe failure escalation (evasive
   target marking, entry-never-granted abort, immediate-exit detection).
   2-attempt-per-round cap per target.
4. **`probe_systematic` mode** -- `score_target` algorithm: never
   re-probe fully identified, prefer unprobed (+50), team filter bonus
   (+30 / -100), proximity bonus, behavioral suspicion bonus, staleness
   penalty. Select highest-scoring target, delegate to probe_target
   behavior. Signal mode_complete when no valid targets remain.
5. **Mode registration** -- Register all four modes in `ModeRegistry`
   during agent initialization.

**Exit criterion**: In a live local match (small config, 4 players,
60s rounds), the agent: (a) leaves idle after role detection, (b) scouts
the room visiting multiple waypoints, (c) approaches visible players,
(d) successfully creates whispers with cooperative fillers (>80% of
attempts). Trace logs confirm mode transitions: idle -> scout ->
probe_target -> (whisper created). No crashes over full game.

---

## Stage 4: Whisper Interaction Protocol

**Goal**: The `in_whisper` mode FSM handles all whisper interactions --
from color exchange through role exchange to exit. This is the most
complex single mode and where the core gameplay loop lives.

1. **FSM skeleton** -- `WhisperModeState` with states: ENTER, ASSESS,
   COLOR_EXCHANGE, EVALUATE, ROLE_EXCHANGE, EXTRACT, STALL, EXIT.
   State dispatch via `match` statement.
2. **ENTER state** -- Detect whisper view. Populate occupant list.
   Select target via `select_whisper_target` (priority: key partner >
   unknown-team > same-team-unverified > enemy). Assess eavesdrop risk
   (hostile present + key_exchange protocol -> abort). Transition to
   ASSESS.
3. **ASSESS state** -- Multi-occupant eavesdrop guard (key roles abort
   if unknown/hostile witness present with >2 occupants). Route to
   protocol: key_exchange -> ROLE_EXCHANGE directly; known team -> skip
   to EVALUATE; unknown -> COLOR_EXCHANGE.
4. **COLOR_EXCHANGE state** -- Reactive path (incoming C.OFFER ->
   C.ACCPT). Proactive path (initiate C.OFFER -> wait for response).
   72-tick timeout -> EXIT. Completion detection from system messages.
   Transition to EVALUATE on success.
5. **EVALUATE state** -- `evaluate_after_color`: same-team -> ROLE_EXCHANGE
   or EXTRACT; opposite-team -> EXIT (key roles) or EXTRACT (grunts);
   Spy -> EXTRACT. Produce correct next state based on role + team +
   intent.
6. **ROLE_EXCHANGE state** -- Reactive (incoming R.OFFER -> role-dependent
   accept/decline decision table from DESIGN.md). Proactive (R.OFFER ->
   wait). Completion detection. Post-exchange knowledge update. 72-tick
   timeout -> EXIT.
7. **EXTRACT state** -- Compose probe message, send via `SendMessageTask`.
   Wait 96 ticks for response. Transition to EXIT.
8. **STALL state** -- Timed message sequence ("THINKING" at 48 ticks,
   "WHO ARE YOU" at 144 ticks, C.OFFER at 240 ticks). Exit after
   protocol timeout (288 ticks).
9. **EXIT state** -- Send EXIT via menu nav. Wait for view transition to
   overworld. Post-exit knowledge update (`post_whisper_knowledge_update`).
   Signal mode_complete.
10. **Entry request handling** -- Per-tick check: deny during sensitive
    operations; grant for probable allies; ignore for enemies/unknowns.
11. **Hostile entrant monitoring** -- Detect new occupants mid-interaction.
    Abort if hostile enters during exchange.
12. **Global timeout** -- Per-protocol-variant max duration (standard:
    240 ticks, key_exchange: 96 ticks, infiltration: 240 ticks, stall:
    288 ticks, quick_verify: 144 ticks).
13. **Forced ejection handling** -- Detect view != whisper before EXIT
    state initiated (phase transition kicked us out). Clean up, signal
    mode_complete with "forced_ejection" reason.
14. **Whisper exchange state derivation** -- Post-belief-update hook logic
    for parsing system messages into structured exchange state fields.
    Substring matching for OCR resilience. Redundant inference (offer
    sent + subsequent system message within 120 ticks). Attribution
    heuristics for multi-occupant whispers.

**Exit criterion**: In a live match with cooperative fillers: (a) agent
completes color exchanges >80% of whisper entries, (b) correctly
identifies team for exchanged players, (c) completes role exchanges with
same-team players, (d) exits within timeout bounds, (e) correctly
handles forced ejection (phase transition during whisper). (f) Handles
incoming offers reactively (accepts C.OFFER, role-appropriate R.OFFER
decision). Trace logs show full FSM path for each whisper interaction.

---

## Stage 5: Role Evaluators

**Goal**: All 7 role-specific strategy evaluators are implemented,
producing the correct priority-ordered mode directives based on
strategic state.

1. **Hades evaluator** -- P1-P6 priority chain per DESIGN.md: partner-in-
   room -> partner-other-room (seek_leadership) -> partner-unknown
   (probe_systematic Shades) -> exchange-done + persephone-unknown ->
   exchange-done + persephone-same-room (hold_position + seek_leadership)
   -> exchange-done + persephone-other-room (coordinate_cross_room self).
2. **Cerberus evaluator** -- P1-P5: partner-in-room -> partner-other-room
   (coordinate_cross_room self, mobile role) -> partner-unknown
   (probe_systematic Shades) -> exchange-done + persephone-unknown ->
   exchange-done (support_local, relay intel to Hades).
3. **Persephone evaluator** -- P1-P6 with tiebreaker nuance: partner-in-
   room -> partner-other-room (hold_position defensive) -> partner-
   unknown (probe_systematic Nymphs cautious) -> exchange-done +
   hades-here + enemy-exchange-likely (coordinate_cross_room escape) ->
   exchange-done + hades-here + enemy-exchange-unknown (hold_position) ->
   exchange-done + hades-other-room (hold_position safe).
4. **Demeter evaluator** -- P1-P5: partner-in-room -> partner-other-room
   (coordinate_cross_room, check Hades location risk) -> partner-unknown
   (probe_systematic Nymphs aggressive) -> exchange-done + hades-unknown
   (probe_systematic locate_hades) -> exchange-done (hold_position
   protect Persephone).
5. **Shade (grunt) evaluator** -- P1-P6: room-composition-unknown
   (probe_systematic map_room) -> key-roles-need-help + am_leader
   (hostage_select facilitate) -> key-roles-need-help + not_leader
   (seek_leadership or volunteer_as_hostage) -> hostile-leader
   (usurp) -> enemy-key-role-located + ally-needs-it (relay_intelligence)
   -> default (probe_systematic disrupt or time_waste).
6. **Nymph (grunt) evaluator** -- P1-P6: persephone-local (hold_position
   seek_leadership protect) -> hostile-leader-threatens-persephone
   (usurp) -> hades-unknown (probe_systematic Shades find_hades) ->
   hades-located + persephone-local (relay_intelligence) ->
   can-disrupt-shades (time_waste shades_key_role) -> default (scout
   or decoy).
7. **Spy evaluator** -- Phase 0-4: no verified ally (probe_target with
   VERIFY_SELF_AS_SPY) -> cover intact + high-value target (infiltration
   protocol) -> intel gathered + local ally (relay_intelligence) ->
   Round 3 decisive action (break_cover) -> cover blown (revert to
   grunt evaluator).
8. **P_FINAL override (all key roles)** -- Exchange-impossible endgame:
   Round 3 + partner-unreachable -> disrupt_enemy_exchange (time-waste
   enemy key roles, misdirect via global chat, use leadership to
   separate them).
9. **Phase override integration** -- Wire phase-sensitive overrides
   (HostageSelect/LeaderSummit/HostageExchange/Reveal) into
   `meta_decide` BEFORE role dispatch.

**Exit criterion**: Unit tests for each evaluator with crafted
`StrategicState` inputs verify correct mode directive for all priority
levels. Particularly: (a) Hades never produces `coordinate_cross_room`
when partner is local, (b) Persephone's P4 only fires when
`enemy_exchange_likely` is True, (c) Cerberus always volunteers for
cross-room when partner is away, (d) P_FINAL fires correctly when
partner is unreachable in Round 3 and not before. Full-game trace
analysis (5 seeds, medium config) shows role-appropriate behavior
patterns.

---

## Stage 6: Leadership, Hostage & Cross-Room Modes

**Goal**: The agent can seek/maintain leadership, make strategic hostage
selections, hold position defensively, negotiate in the leader summit,
and coordinate cross-room movement.

1. **`hold_position` mode** -- Gentle wander near room center (avoid
   `defensive_posture` flag detection). Seek leadership if param set
   (open global chat -> usurp selector). Grant whisper requests from
   probable allies. Anti-hostage sub-behavior during HostageSelect.
2. **`seek_leadership` mode** -- Open global chat view. Navigate usurp
   candidate selector. Cast vote for self or ally. Monitor for success/
   failure via system messages. Estimate majority achievability before
   attempting.
3. **`usurp` mode** -- Coordinate majority vote. Count local allies.
   Deterministic candidate selection (all Eurydice agents with same
   knowledge independently choose same candidate). Known limitation
   flag for non-Eurydice allies.
4. **`hostage_select` mode** -- Selection algorithm: (a) honor ally
   "SEND ME" volunteers (verified-team only, never send own key role
   post-exchange), (b) team-specific logic (Shades: send Nymphs, keep
   key roles; Nymphs: never send Persephone, send Hades away, send
   Shades), (c) fallback to least-valuable player. Navigate the
   hostage selection UI (grid + toggle + commit) before timer expires.
5. **`summit_interact` mode** -- Chat-only interaction: send probing
   message, tab to info screen (validate knowledge, 2-3 ticks), tab
   back to read response. Strategy varies by situation (unknown enemy
   team -> probe, confirmed enemy -> extract/misdirect, same team ->
   coordinate). Rate-limit awareness (7 messages max in 15s summit).
   Tab to shout view before summit ends to read accumulated room chat.
6. **`coordinate_cross_room` mode** -- Method assessment: am-leader
   (select target as hostage) > want-to-move (signal "SEND ME" to local
   leader via whisper or global chat) > am-leader + summit-upcoming
   (prepare negotiation strategy). Key constraint documentation: cannot
   tell other room anything, cannot influence other room directly. Mode
   only produced when agent CAN take meaningful local action.
7. **Hostage volunteering** -- "SEND ME" signaling via whisper with
   leader or global chat. Only effective with ally leader. No
   "volunteer button" exists.

**Exit criterion**: In a live multi-agent match (8 players, medium
config, 3 rounds): (a) agent successfully usurps hostile leader when
majority is available (>60% success rate across 5 seeds), (b) leader-
agent never sends own key role as hostage, (c) agent enters
hold_position when positioning is favorable and maintains it, (d) summit
chat is produced (non-empty message log during LeaderSummit), (e) cross-
room coordination produces measurable partner-proximity improvement
across rounds (trace: distance between key pair decreases over game).

---

## Stage 7: Communication Protocol

**Goal**: The agent sends strategically appropriate messages and parses
incoming messages from other players (including non-Eurydice opponents)
into actionable knowledge.

1. **Message sending (global chat)** -- Template system: "LOOKING FOR
   [color]", "MEET [direction]", "I AM [role]", "SEND ME", "SEND
   [color]", "VOTE FOR ME", "DONT SEND [color]", "[color] IS [role]".
   Priority system (1-6) with one-per-round budgeting. Rate-limit
   awareness (240-tick cooldown). Never waste slot on low-priority when
   high-priority might be needed later.
2. **Message sending (whisper chat)** -- Templates: "WHO ARE YOU",
   "FOUND [role]?", "[color] IS [team/role]", "SEND ME", "THINKING",
   "VOTE ME", summit negotiation phrases. 48-tick cooldown respect.
3. **Message parsing** -- `parse_message` function: keyword extraction
   with fuzzy matching against `ROLE_KEYWORDS`, `TEAM_KEYWORDS`,
   `ACTION_KEYWORDS` dicts. Extract identity claims, location claims,
   action requests, questions. Mark uninterpretable when nothing
   extracted. Robust to arbitrary input (non-Eurydice opponents may
   send anything).
4. **Credibility assessment** -- `assess_credibility`: base 0.3 for
   unknown, 0.85 for role-exchange-verified ally, 0.6 for color-exchange
   ally, 0.1 for known enemy. Reduce for contradictions. Reduce for
   unknown sender.
5. **Knowledge update from chat** -- Only apply claims above credibility
   threshold (0.5). Never overwrite higher-confidence sources. Track
   action requests (always noted, even from enemies -- signal value).
6. **`relay_intelligence` mode** -- Channel selection: whisper (private,
   costs probe time) vs global chat (immediate, enemies see). Identify
   target ally. Approach -> whisper -> share, or open global -> send.
   Mark intel as relayed. Fires when: enemy key role identified + local
   ally needs to know, or exchange status learned + local key role needs
   to adjust.

**Exit criterion**: (a) Parser correctly extracts intents from 20+ test
messages (including misspelled, abbreviated, and multi-word inputs).
(b) Credibility correctly downgrades enemy claims and upgrades verified
ally claims. (c) Agent sends contextually appropriate global chat
messages in live games (trace shows non-empty global messages with
correct priority for game state). (d) Agent never sends global chat
during whisper. (e) Agent never wastes cooldown on low-priority message
when high-priority situation is active.

---

## Stage 8: Deception & Spy Framework

**Goal**: The agent employs strategic deception when EV-positive, the
Spy role functions fully with cover management, and advanced modes
(time_waste, decoy) are operational.

1. **Deception state** -- `DeceptionState` dataclass: `projected_role`,
   `projected_team`, `target_audience`, `lies_told`, `cover_consistent`.
   Track what each opponent believes about us based on what we've shown/
   told them.
2. **Deception EV assessment** -- `should_deceive`: evaluate
   `P(believed) * V(belief) - P(caught) * C(exposure)`. Role-specific
   deception freedom (grunts: high, key roles: low). Never contradict
   mechanical reveals.
3. **Behavioral camouflage** -- Mode parameter variants: Persephone can
   mimic Nymph-grunt behavior (probe freely), Hades can mimic Shade-
   grunt behavior (casual exchanges), key roles act like room composition
   doesn't matter.
4. **Spy Phase 0 (verified ally)** -- Target selection for first role
   exchange: prioritize players whose observed team color matches Spy's
   FAKE team (these are real allies due to inversion). Skip color
   exchange, go straight to R.OFFER. Accept 40-65% success probability
   on first attempt.
5. **Spy cover management** -- Cover impact rules: color exchange
   reinforces, role reveal breaks, chat consistency maintains. Track
   cover status. Transition to grunt strategy when cover blown.
6. **Spy infiltration protocol** -- Whisper variant: color exchange
   (reinforces cover) -> EXTRACT (gather intel on key roles) -> EXIT.
   Never accept R.OFFER from enemies. Never reveal role.
7. **Spy decisive plays** -- Phase 3 (Round 3): break cover for impactful
   action (become enemy-supported leader, relay critical intel, feed
   false intel). Only when cover value < action value.
8. **`time_waste` mode** -- Approach enemy key role. Create/join whisper.
   Execute stall protocol: slow responses, fake interest, delayed
   exchanges. Target 8-10 seconds consumed. Exit before they extract
   value.
9. **`decoy` mode** -- Grunt impersonates key role via global chat
   ("I'M PERSEPHONE") and/or behavioral mimicry (defensive posture,
   urgent probing). Accept investigation whispers (further time waste).
   Acceptable cost: enemy eventually discovers truth, but time was
   wasted.
10. **Counter-intelligence** -- Detect inconsistent claims from other
    players (`inconsistent_claims` flag). Spy awareness rules: color
    exchange + inconsistent behavior -> Spy suspicion. Track
    `whispers_with_both_teams` flag implications.

**Exit criterion**: (a) Spy agent maintains cover through at least 2
rounds in a live match (color exchanges don't break it). (b) Spy
successfully establishes verified ally in >50% of games. (c) Spy relays
intelligence to real team at least once per game. (d) Grunt agents
running `decoy` mode draw at least one enemy interaction (measured from
traces). (e) `time_waste` mode keeps enemy in whisper for >6 seconds on
average. (f) Deception state prevents self-contradiction (no tests show
agent claiming two different roles to the same player).

---

## Stage 9: Integration Testing & Tuning

**Goal**: End-to-end validation across all configs, roles, and opponent
types. Parameter tuning from aggregate trace analysis.

1. **Config-adaptive validation** -- Run full games across all config
   families: `default` (15s), `short` (30s), `empty3` (45s), `simple`
   (60s), `debug2r` (2x60s), `medium` (180/120/60s). Verify urgency
   computation and probe budgeting adapt correctly.
2. **Role coverage matrix** -- For each role, run 5+ games per config.
   Verify role-appropriate behavior via trace analysis (see DESIGN.md
   Testing Strategy section).
3. **Key exchange success rate** -- Target: >70% of games where partner
   is reachable. Analyze failure modes (timing, target selection, entry
   failures).
4. **Win rate benchmarking** -- Eurydice vs Eurydice: approximately 50/50
   (validates balance). Eurydice vs baseline fillers: >60% win rate
   (validates competence).
5. **Safety invariants** -- Automated trace scanning: (a) never sends own
   key role as hostage post-exchange, (b) Persephone never role-exchanges
   with confirmed enemy, (c) Spy never accepts R.OFFER from enemy,
   (d) no mode persists >300 ticks without progress during Playing phase,
   (e) info-screen reconciliation detects missed exchanges.
6. **Parameter tuning** -- From aggregate traces: adjust
   `probe_cycle_cost_ticks`, target scoring weights, urgency thresholds,
   whisper timeout durations, stall timing intervals. Each adjustment
   requires re-run of validation suite.
7. **Regression harness** -- Script that runs the validation suite (10+
   seeds x 3 configs x 2 matchup types) and produces a summary report.
   Run after every significant change. Metrics compared to stored
   baseline.
8. **Edge case validation** -- Hostaged unexpectedly (verify re-plan
   fires), role detection failure (verify grunt fallback), forced whisper
   ejection (verify clean recovery), Spy targeted by enemy role exchange
   (verify cover-blown transition), Round 3 partner-unreachable (verify
   P_FINAL disruption fires).

**Exit criterion**: All safety invariants pass over 50+ game traces with
zero violations. Key exchange success >70%. Win rate vs baseline >60%.
No crashes or stuck-states across full regression suite. Trace analysis
script produces clean summary with no flagged anomalies.

---

## Dependency Graph

```
Stage 0 (data types & knowledge model)
  ├── Stage 1 (accumulation & inference pipeline)
  │     └── Stage 2 (meta_decide engine)
  │           ├── Stage 3 (basic modes: idle, scout, probe)
  │           │     └── Stage 4 (whisper interaction protocol)
  │           │           └── Stage 5 (role evaluators)
  │           │                 ├── Stage 6 (leadership, hostage, cross-room)
  │           │                 ├── Stage 7 (communication protocol)
  │           │                 └── Stage 8 (deception & spy)
  │           │                       └── Stage 9 (integration & tuning)
  │           └── (Stage 5 also depends on Stage 2 directly)
  └── (Stage 7 types used from Stage 0 onward)
```

**Parallelization opportunities:**
- Stages 6, 7, and 8 are largely independent of each other (all depend
  on Stage 5 being complete, but can be developed concurrently once
  Stage 5's evaluator interfaces are defined).
- Stage 1 items 2-6 (individual trackers) are independent and can be
  developed in parallel.
- Stage 4 sub-states (COLOR_EXCHANGE, ROLE_EXCHANGE, EXTRACT, STALL) are
  independent after the FSM skeleton (item 1) is in place.
- Stage 9 can begin incrementally as each prior stage reaches its exit
  criterion (don't wait for all prior stages to be complete before
  starting integration testing on completed components).

**Critical path:** Stage 0 -> Stage 1 -> Stage 2 -> Stage 3 -> Stage 4
-> Stage 5 -> Stage 9. Stages 6-8 are off the critical path and can
slip without blocking the core gameplay loop.

---

## Codex Delegation Notes

Lessons learned from delegating implementation to OpenAI Codex CLI:

### Timeout Management

- **Budget 600s (10 min) minimum** for any module >200 lines. Codex
  reads surrounding files for safety even when all context is inline.
- **Always capture the `thread_id`** from the `thread.started` JSONL
  event. If the command times out, the session is recoverable.
- **Resume with:** `codex exec resume <thread_id> "<instruction>" --json`
  The resumed session retains full memory of prior turns and file state.
- Resume does NOT accept `-s` or `-C` flags (inherits from initial).

### Prompt Design (What Works)

- **Inline all type definitions and API contracts** directly in the
  prompt. Even with "do NOT read files," Codex still reads for safety.
  Having the info inline means it can cross-check rather than spending
  5+ minutes on exploratory reads.
- **Provide the exact verification command** at the end of the prompt.
  Codex will run it and fix errors, saving a resume round-trip.
- **Specify field-by-field** for dataclasses. Codex faithfully reproduces
  explicit field lists but makes creative (sometimes wrong) choices when
  given vague instructions.
- **State constraints explicitly**: line count limits, "do NOT try to
  compact," import paths, which field is `.extra` vs `.ext`.

### Common Codex Pitfalls

- **Over-reading:** Codex explores broadly before writing. A 3700-line
  DESIGN.md costs 3-5 minutes of read time. Pre-digest the relevant
  sections into the prompt.
- **Refactoring loops:** Codex may delete-and-rewrite a working file to
  meet a perceived constraint (e.g., "under 300 lines"). Explicitly say
  "do NOT refactor or compact" if the first version passes tests.
- **Schema mismatches:** Codex may assume `(tick, x, y)` when the actual
  format is `(x, y, tick)`. Always include the exact field layout from
  the source file.
- **`python` vs `.venv/bin/python`:** The workspace has no bare `python`
  on PATH. All verification commands must use `.venv/bin/python`.
