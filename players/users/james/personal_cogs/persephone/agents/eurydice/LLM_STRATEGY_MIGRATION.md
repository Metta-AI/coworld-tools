# Eurydice LLM Strategy Migration Report

Last source audit: 2026-05-11.

This report describes how to turn Eurydice from its current mostly
deterministic strategic agent into an LLM-led social strategy agent while
preserving the Orpheus framework, Eurydice's existing modes, and the
deterministic action mechanics already built.

The goal is not to replace Eurydice. The goal is to change who owns judgment.
Deterministic code should remain the body, sensors, memory, and safety system.
The LLM should become the high-level social strategist.

---

## Executive Summary

The current Eurydice agent is no longer just randomly wandering. It perceives
game state, learns role/team/room, builds a strategic summary, selects probe
targets, creates or requests whispers, runs a whisper FSM, and records detailed
traces. It also has the first LLM boundary:

- `agents/eurydice/llm_context.py` builds a JSON-safe decision context.
- `agents/eurydice/llm_validator.py` validates model decisions and can
  trace shadow results.
- `agents/eurydice/LLM_CONTROL.md` documents the current contract.

The major problem is architectural direction. The remaining game is social,
adversarial, and mixed-policy. In tournament play, Eurydice cannot assume other
agents share its rendezvous protocol, exchange policy, message style, or
response timing. A large symbolic strategy tree will overfit to self-play and
become brittle as soon as opponents or allies behave differently.

The right split is:

- **LLM owns:** target priority, communication, reveal decisions, trust
  updates from conversation, deception timing, global-room strategy, and
  adaptation to non-cooperative players.
- **Deterministic code owns:** perception, memory, mechanical truth, legal
  actions, mode execution, button timing, cooldowns, validation, traceability,
  and fallback.

The immediate migration path is to keep Orpheus and Eurydice, add an LLM
controller behind the existing `meta_decide` and `InWhisperMode` seams, and
roll it out surface by surface:

1. Shadow decisions over saved contexts.
2. LLM target selection for `probe_systematic`.
3. LLM whisper message/reveal/exchange decisions while already in whisper.
4. LLM global-room messages and leadership requests.
5. LLM role-specific deception and hostage strategy after earlier surfaces are
   measurable and safe.

---

## Source-Verified Current State

### Orpheus Framework

Orpheus already has the right shape for LLM control:

- `orpheus/pipeline.py` runs the inner loop:
  `parse_frame -> belief_update -> hooks -> mode selection -> task -> ActCommand`.
- `orpheus/outer_loop.py` runs `meta_decide` asynchronously over copied belief
  snapshots and pushes `ModeDirective` objects through `ModeBuffer`.
- `orpheus/mode.py` defines the stable mode contract:
  `ModeDirective(mode, params)` plus per-mode `select_task`.
- `orpheus/task.py` and `orpheus/tasks/*` lower semantic tasks to button masks
  and chat packets.
- `orpheus/logging.py` already supports event, decisions, and verbose trace
  levels.

This means an LLM does not need to press buttons or handle pixels. It can
produce semantic decisions that are converted into existing mode directives or
task-level actions.

### Eurydice Runtime

Eurydice currently wires Orpheus in `agents/eurydice/policy.py`:

- `build_registry()` registers the implemented modes:
  `idle`, `scout`, `probe_target`, `probe_systematic`, `in_whisper`,
  `hold_position`, `coordinate_cross_room`, `seek_leadership`,
  `hostage_select`, `summit_interact`, `time_waste`, `relay_intelligence`,
  `decoy`, `usurp`, and `check_info_screen`.
- `eurydice_post_belief_update` is registered as a post-belief hook.
- `OuterLoop(meta_decide, ...)` is the single strategic decision loop.

The current deterministic strategic stack is:

- `pipeline.py`: accumulators, position tracking, minimap tracking, whisper
  tracker, probe tracker, exchange tracker, info-screen reconciliation, chat
  parsing, leadership tracker, and inference updates.
- `meta_decide.py`: builds `StrategicState`, applies phase/whisper overrides,
  enforces a 48-tick minimum mode duration, and dispatches to role evaluators.
- `evaluators.py`: role-specific branches choose mode directives and params.
- `modes.py`: `probe_target` and `probe_systematic` approach players and
  initiate/request whispers.
- `whisper_mode.py`: finite-state in-whisper protocol for color/role exchange,
  extraction, stalling, entry grants, and exit.
- `advanced_modes.py`: shallow leadership, hostage, summit, relay, cross-room,
  time-waste, decoy, and info-screen modes.

### Current LLM Boundary

`llm_context.py` provides `eurydice.llm_context.v2` with:

- self identity and location;
- strategy/objective/urgency;
- match config and role-summary facts;
- player knowledge records;
- recent chat messages;
- legal action names;
- runtime affordances and action preconditions;
- hard constraints.

`llm_validator.py` provides `eurydice.llm_decision.v2` validation:

- schema/action/confidence/rationale checks;
- current-view legality;
- target checks for selected actions;
- message ASCII/length checks;
- unsupported mechanical-claim rejection;
- role/color reveal safety checks;
- trace events for accepted/rejected shadow decisions.

This is enough to begin shadow evaluation. It is not enough for runtime control
yet.

### Latest Live Finding

The latest full-trace live runs showed that deterministic Eurydice selects
targets and attempts probes, but does not produce reliable server-confirmed
interactions:

- many `whisper_created` and `entry_requested` events;
- no server-confirmed `joined` events in the latest clean run;
- no server-confirmed `shared roles` or `exchanged colors`;
- little to no chat;
- draw result with neither key pair exchanged.

That finding supports the migration. The remaining problem is not "add more
symbolic branches"; it is "make semantic actions reliable, then let a model
choose among them with evidence."

---

## What To Preserve

Do not restart from scratch. The following pieces should remain central:

1. **Perception and belief update.** The model should not inspect raw frames.
   It should receive structured context from `build_llm_context`.
2. **Mode registry and Orpheus outer loop.** The model should ultimately return
   decisions that become `ModeDirective` objects or mode-local semantic actions.
3. **Existing movement and menu tasks.** Button timing, menu navigation, chat
   transport, and view management should stay deterministic.
4. **Knowledge provenance.** Mechanical exchanges must outrank chat claims.
   The LLM can reason about claims, but cannot overwrite stronger evidence.
5. **Role evaluators as fallback.** The current evaluator stack should remain
   the default fallback and a source of baseline suggestions.
6. **Trace-first development.** Every LLM context, model decision, validator
   result, fallback, and executed action must be traceable.

---

## Key Gaps In The Current LLM Contract

These were source-observed gaps that had to be fixed before broad runtime
control. The items below now describe the implemented contract.

### Missing Or Misnamed Actions

Initial finding: the schema had `join_whisper`, but not `grant_entry`, even
though accepting another player's request to enter our whisper is a distinct
mechanical action.

Current implementation:

- `grant_entry` and `deny_entry` are explicit actions.
- `join_whisper` is reserved for requesting entry to someone else's existing
  whisper from the overworld.
- In-whisper pending entries expose `grant_entry`/`deny_entry`, not
  `join_whisper`.

### Incomplete Action Payloads

Initial finding: `move_to` existed as an action but the decision shape only had
`target` as a `PlayerID`. `select_hostage` also had no hostage list payload.

Current implementation:

- `destination: [x, y] | null` drives movement.
- `hostage_targets: [[color, shape], ...]` drives hostage selection.
- Hostage contexts include parsed grid options, required remaining count, and
  selected positions when perception provides them.
- `target` remains the player-target field for probe, whisper-entry, and
  exchange actions.

### Exchange Target Validation Is Too Loose

Initial finding: the validator required targets for some player actions but not
for exchange actions.

Current implementation:

- The validator requires a target for all exchange actions unless there is exactly one
  non-self current whisper occupant and the context explicitly marks that as
  the implicit target.
- `accept_*` must correspond to an active offer from that target.
- `offer_*` targets must be in the current whisper.

### Whisper Control Is Not Reachable Through `meta_decide` Alone

`meta_decide` currently returns `in_whisper` whenever `belief_state.view is
View.WHISPER`. That is correct for mechanical safety, but it means a top-level
LLM directive cannot directly choose whisper actions unless:

- `InWhisperMode` itself consults an LLM decision, or
- `meta_decide` passes typed params into `in_whisper`, and `InWhisperMode`
  consumes those params.

Required fix:

- Treat whisper strategy as a mode-local LLM control surface.
- Keep `InWhisperMode` as the executor/FSM, but let it ask the LLM at selected
  decision points: entry request, first assessment, incoming offer, message
  response, reveal/exchange decision, and exit/stall decision.

### Context Lacks Executor Readiness Details

The current context says which actions are broadly legal for a view. It does
not fully explain whether an action is actually executable now.

Needed context additions:

- current mode and current task;
- action cooldowns, especially chat cooldown;
- pending entry requester;
- active color/role offerers;
- current whisper occupants and whether each is confirmed, claimed, or
  unknown;
- recent probe failures by target and reason;
- target scores and the deterministic fallback target;
- action affordances with preconditions, not just action names;
- whether an exchange event was server-confirmed or only attempted;
- recent model decisions and whether they were accepted, rejected, executed, or
  stale.

---

## Target Architecture

### High-Level Flow

The future runtime should look like this:

```text
frame
  -> Orpheus perception
  -> belief update
  -> Eurydice accumulators/inference
  -> build strategic state
  -> build LLM context
  -> deterministic fallback directive
  -> optional LLM decision
  -> validator
  -> semantic executor / mode directive translator
  -> Orpheus mode/task execution
  -> trace outcome
```

The fallback directive should always be computed. The LLM is allowed to improve
or replace it only after validation and freshness checks.

### Components To Add

#### `llm_controller.py`

Provider-independent orchestration:

- decide whether this tick is an LLM decision point;
- build context;
- ask the provider or shadow source;
- validate the response;
- convert accepted responses to a control result;
- return fallback when disabled, invalid, stale, or timed out;
- trace context hash, decision id, latency, source, result, and fallback.

#### `llm_prompts.py`

Prompt templates for separate surfaces:

- probe target selection;
- in-whisper social decision;
- global room communication;
- leadership/hostage decisions later.

The prompt should use the JSON context as primary evidence and should not ask
the model to infer hidden state from prose.

#### `llm_provider.py`

Small provider adapter interface behind explicit configuration:

- deterministic `hold` and `heuristic` providers for tests and plumbing;
- opt-in AWS Bedrock Claude Haiku provider behind `--llm-provider haiku` or
  `--llm-provider bedrock`;
- no third-party SDK dependency required for Bedrock; the adapter signs
  InvokeModel requests with standard-library SigV4 code;
- environment or CLI flag required to enable live model calls;
- timeout budget and per-provider cooldown;
- parse JSON response and keep malformed semantic output visible to the
  validator;
- no persistent model memory;
- deterministic fallback on failure.

#### `llm_executor.py`

Maps validated semantic decisions into existing modes/tasks:

- `probe_player` -> `ModeDirective("probe_target", ProbeTargetParams(...))`
- `open_global` -> `ModeDirective("llm_action", LLMActionParams(...))`
- `open_info` -> `ModeDirective("llm_action", LLMActionParams(...))`
- `send_global` -> `ModeDirective("llm_action", LLMActionParams(...))`
- `send_whisper` during leader-summit or whisper-local control -> task-backed
  semantic action
- `move_to` -> `ModeDirective("llm_action", LLMActionParams(...))`
- `seek_leadership` -> `SeekLeadershipMode`
- `select_hostage` -> `HostageSelectMode` with `HostageSelectParams.move`
- whisper decisions -> consumed inside `InWhisperMode`

Do not let the executor invent modes dynamically. It should only emit
registered modes or known task-backed action modes.

#### `llm_shadow_runner.py`

Offline runner over saved contexts/traces:

- sample decision contexts from live JSONL traces and/or frame recordings;
- call the prompt/provider;
- validate decisions;
- compare against deterministic fallback;
- write aggregate metrics and per-context artifacts.

---

## Control Surfaces

### Surface 1: Probe Target Selection

This is the safest first runtime surface.

Why first:

- It maps cleanly to existing `ProbeTargetParams`.
- It happens outside fragile menu navigation.
- Bad choices are recoverable through fallback and timeouts.
- It tests whether the LLM uses evidence better than score heuristics.

LLM input needs:

- visible/known players;
- known team/role/source/confidence;
- last seen position;
- distance;
- recent failed attempts;
- current objective;
- urgency;
- deterministic fallback target and score reason.

Allowed outputs:

- `probe_player(target)`
- `hold`
- `open_global`
- `move_to(destination)` only after coordinate support exists.

Exit criteria:

- accepted decisions exceed 95%;
- target exists and has known/visible position;
- repeated failed targets drop in priority;
- probe completion rate does not regress versus deterministic fallback.

### Surface 2: In-Whisper Social Decisions

This is strategically important but should come second because mechanics and
state are more fragile.

Decision points:

- entering a whisper with one or more occupants;
- receiving an entry request;
- receiving a role/color offer;
- deciding whether to offer role, offer color, ask a question, stall, or exit;
- deciding how to respond to a claim or question.

Allowed outputs:

- `send_whisper(message)`
- `offer_color(target)`
- `accept_color(target)`
- `offer_role(target)`
- `accept_role(target)`
- `grant_entry(target)`
- `deny_entry(target)`
- `exit_whisper`
- `hold`

Implementation approach:

- Keep `InWhisperMode` as the owning mode.
- Replace selected branches in `_assess_task`, `_color_exchange_task`,
  `_role_exchange_task`, `_extract_task`, `_stall_task`, and
  `_entry_request_task` with "ask LLM if enabled; otherwise use existing
  deterministic branch."
- Preserve protocol timeouts and forced-exit safety.

Exit criteria:

- no accepted exchange action without a current occupant target;
- no accepted role reveal to a known enemy unless objective permits it;
- useful whisper message rate increases;
- server-confirmed role/color exchange count improves.

### Surface 3: Global Room Communication

This should follow whisper control because message quality depends on the same
claim/evidence discipline.

Decision points:

- start of round after role/team known;
- after discovering key partner/enemy key;
- after failed repeated probes;
- before hostage selection;
- urgent final-round state.

Allowed outputs:

- `open_global`
- `send_global(message)`
- `seek_leadership`
- `open_info`
- `hold`

Message policy:

- short;
- actionable;
- no unsupported mechanical claims;
- no assumption that listeners are our policy;
- prefer requests and facts with provenance: "HAVE HADES?", "I NEED DEMETER",
  "ROLE SHARE?", "SEND ME", "WHO HAS LEAD".

Exit criteria:

- messages are sparse and useful;
- no global spam loops;
- global messages correlate with improved probe/meeting/hostage outcomes.

### Surface 4: Role-Specific High-Level Strategy

Only after surfaces 1-3 work should the LLM choose broader plans:

- whether key roles reveal or hide;
- whether grunts support leadership or probe;
- whether Spy maintains cover or defects into direct team play;
- whether to seek leadership;
- which hostages to pick or request.

The existing role evaluators should remain as fallback and as prompt context.

---

## Decision Cadence

The LLM should not run every tick. It should run on meaningful decision points:

- role/team/room becomes known;
- round starts or urgency band changes;
- current mode completes or fails;
- selected target disappears or failed recently;
- entering a whisper;
- occupant joins/leaves whisper;
- entry request appears;
- incoming offer appears;
- new chat message parses into claim/question/action request;
- chat cooldown becomes available and there is something worth saying;
- hostage selection starts;
- outer-loop heartbeat every 48-96 ticks when nothing else changes.

Every LLM decision must have:

- context hash;
- decision id;
- consumed tick;
- current tick when applied;
- staleness;
- fallback directive/action;
- validator result;
- executor result.

Stale decisions should be rejected when:

- view changed;
- phase changed;
- target no longer exists or moved out of action feasibility;
- current whisper occupants changed in a way that invalidates the target;
- pending offer/request disappeared;
- decision age exceeds the surface-specific budget.

---

## Prompt Principles

The prompt should explicitly tell the model:

- Other agents may use unknown policies. Do not assume they follow our
  protocol.
- Chat claims are not truth. Mechanical exchanges and info-screen evidence are
  stronger.
- Role exchange is the only win-condition exchange.
- You choose semantic actions only. You never choose button presses.
- Prefer actions that still make sense if the target ignores you.
- Keep messages short and game-actionable.
- Do not reveal true role/color when validator constraints say it is unsafe.
- Explain the decision in a short rationale for trace review.

Prompt variants should be small and surface-specific. Do not use one giant
prompt for every context.

---

## Phased Implementation Plan

### Phase 0: Stabilize The Contract

Goal: make the current LLM boundary honest enough to build on.

Work:

- Add schema v2 fields: `destination`, `hostage_targets`, `decision_kind` or
  `surface`, and explicit `grant_entry` / `deny_entry`.
- Make target requirements action-specific and strict.
- Add executor-readiness details to context.
- Add current mode/task/cooldown/pending-offer/pending-entry/probe-failure
  context.
- Add deterministic fallback recommendation to context.

Tests:

- context includes current mode/task/cooldowns;
- context includes pending entry and active offers;
- validator rejects `offer_role` without target in crowded whisper;
- validator accepts implicit target only with exactly one non-self occupant;
- validator rejects `accept_role` when no active role offer exists;
- validator rejects stale decision context hashes.

### Phase 1: Shadow Runner

Goal: evaluate model outputs without changing live behavior.

Work:

- Add saved-context export from live traces.
- Add `scripts/evaluate_eurydice_llm_shadow.py`.
- Add provider-independent sample loader.
- Add prompt templates for probe, whisper, and global surfaces.
- Record model output, validator result, fallback, and comparison.

Tests:

- runner works with a fake provider;
- malformed provider output is categorized;
- accepted/rejected events are parseable by the trace analyzer;
- shadow mode never changes selected runtime directive.

Evaluation:

- parse rate >99%;
- validator acceptance rate tracked by surface;
- rejection reasons bucketed;
- rationale mentions current objective/phase;
- no accepted hard-constraint violations.

### Phase 2: One-Shot Semantic Executor

Goal: make accepted decisions executable through Orpheus before trusting a real
provider broadly.

Work:

- Add `llm_executor.py`.
- Add one-shot action params/mode if existing modes are too coarse:
  `LLMActionParams` and `LLMActionMode`, or smaller explicit modes such as
  `MoveToMode` and `SendGlobalMode`.
- Map accepted decisions to existing mode directives where possible.
- Trace `llm_action_executed` / `llm_action_failed`.

Tests:

- every allowed action maps to either a registered mode or a mode-local
  whisper action;
- invalid mappings fall back;
- no executor emits raw button masks;
- provider-disabled runtime is byte-for-byte behaviorally equivalent at the
  directive level where practical.

### Phase 3: Runtime Target Selection

Goal: let the LLM choose probe targets while existing modes execute movement
and whisper initiation.

Work:

- Add a config flag such as `--llm-control=shadow|targets|off`.
- In `meta_decide`, compute deterministic fallback, ask LLM on target-selection
  decision points, validate, then translate accepted `probe_player` to
  `ProbeTargetParams`.
- Keep role evaluators as fallback.

Tests:

- fake provider can choose a visible target and `meta_decide` emits
  `probe_target`;
- bad provider target falls back to deterministic evaluator;
- stale target decision is rejected after view/phase change;
- repeated failed target appears in context and can be avoided.

Live criteria:

- no increase in idle/no-op ratio;
- target repetition after failure decreases;
- probe completion rate improves or stays neutral;
- no crash on provider timeout.

### Phase 4: Runtime Whisper Control

Goal: let the LLM choose social actions after Eurydice is already in a whisper.

Work:

- Add a mode-local controller call inside `InWhisperMode`.
- Keep deterministic timeouts, hostile-entry exits, and menu tasks.
- Use LLM decisions for entry grant/deny, messages, offer/accept choices, and
  exits.
- Record whether accepted decisions were mechanically completed and
  server-confirmed.

Tests:

- fake provider grants a pending entry and `GrantEntryTask` is selected;
- fake provider sends a whisper and cooldown prevents spam;
- fake provider accepts an active role offer only from a valid occupant;
- known-enemy role reveal is rejected;
- crowded-whisper unknown role offer is rejected or requires explicit target.

Live criteria:

- server logs show actual joined whispers;
- useful whisper messages appear;
- server-confirmed exchange count increases;
- no unsupported mechanical claims in chat.

### Phase 5: Runtime Global Communication

Goal: let the LLM send sparse, useful global-room messages.

Work:

- Add global prompt surface.
- Add message budget and duplicate suppression.
- Let LLM ask for help, identify needs, request leadership, or announce
  mechanically confirmed intel.

Tests:

- fake provider sends valid global message only when legal/cooldown allows;
- duplicate message rejected or suppressed;
- unsupported "verified" claims rejected;
- provider-disabled fallback still works.

Live criteria:

- messages per round stay bounded;
- message usefulness rubric improves;
- global messages correlate with more completed probes or leader action.

Current implementation note: the prompt surface, validator path, and
`LLMActionMode` execution path exist. `--llm-control all` can accept validated
`send_global`, `open_global`, and `open_info` decisions. Rich duplicate
suppression and usefulness evaluation remain future work.

### Phase 6: Role-Specific LLM Strategy

Goal: let the LLM choose broader role plans after tactical surfaces work.

Work:

- Add role-specific prompt briefs generated from `StrategicState`.
- Keep current evaluator branch as fallback and as prompt evidence.
- Add Spy/deception state to context.
- Add leadership and hostage action payloads.

Tests:

- Hades/Cerberus/Persephone/Demeter prompts prioritize partner exchange;
- grunts do not role-reveal unnecessarily;
- Spy maintains consistent cover unless objective permits break;
- hostage decisions only select eligible targets.

Live criteria:

- key pair role exchange happens more often;
- hostage requests/selections are coherent;
- model does not regress mechanical safety metrics.

Current implementation note: `--llm-control all` now grants broad semantic
authority across normal evaluator output and eligible phase overrides. It can
select hostage targets from parsed grid options, send leader-summit chat, seek
leadership, move/open views, and use the whisper-local entry/first-message hook.
Role-specific prompt tuning and the Bedrock Haiku provider are now wired. Short
Haiku smoke validation on May 11, 2026 accepted hostage selections and produced
no provider errors or valid-view mismatches after stale-action guards were
added. Default self-play still drew with no completed key-pair role exchange,
so live mixed-policy and exchange-completion evaluation are still pending.

### Phase 7: Mixed-Policy Evaluation

Goal: prove the strategy generalizes beyond self-play.

Work:

- Run Eurydice against mixtures of baseline, filler, passive, random,
  cooperative, and adversarial policies.
- Add fixtures/traces for uncooperative targets and misleading chat.
- Score behavior by outcome and by evidence quality, not just win rate.

Evaluation:

- does not assume other agents follow Eurydice protocol;
- recovers from ignored whispers;
- does not overtrust chat;
- seeks mechanical truth when possible;
- uses global chat to make robust requests;
- exits unproductive interactions quickly;
- improves win-condition progress in mixed-policy lobbies.

---

## Evaluation Rubric

### Mechanical Reliability

- accepted LLM action maps to legal executor;
- executor emits non-noop command when appropriate;
- no valid-view mismatches caused by LLM handoff;
- no provider timeout crashes;
- no stale decision applied after view/phase/target invalidation.

### Evidence Discipline

- mechanical exchange truth outranks chat;
- chat claims retain provenance and confidence;
- unsupported mechanical claims rejected;
- role/color reveal constraints enforced;
- Spy color risk handled explicitly.

### Social Usefulness

- messages are short, relevant, and non-duplicative;
- target choice accounts for failure history and distance;
- agent does not keep waiting for non-cooperative players indefinitely;
- LLM uses global chat when private contact fails;
- entry grant/deny choices are explainable from evidence.

### Strategic Progress

- key roles find or narrow partner candidates;
- role exchanges with true partners increase;
- grunts support information gathering and leadership;
- Spy behavior remains cover-consistent or intentionally breaks cover;
- final-round actions prioritize win condition over exploration.

### Mixed-Policy Robustness

- no reliance on other agents sharing Eurydice-specific protocols;
- graceful fallback when ignored;
- no endless loops around one unresponsive target;
- avoids treating silence as cooperation;
- adapts to noisy, lying, or incoherent opponents.

---

## Recommended Immediate Next Step

Do not add more symbolic social strategy branches right now. The next concrete
engineering step should be Phase 0 of this migration:

1. Add LLM decision schema v2 with `grant_entry`, `deny_entry`,
   `destination`, and hostage payload support. **Done.**
2. Expand `build_llm_context` with executor-readiness state:
   current mode/task, cooldowns, pending entry, active offers, and recent probe
   failures. **Mostly done.** Deterministic fallback recommendation still needs
   richer source scoring.
3. Tighten validator target requirements for exchange and entry actions.
   **Done.**
4. Add tests proving the contract rejects ambiguous or mechanically impossible
   decisions. **Done.**

The shadow runner, deterministic fake providers, Bedrock Haiku provider,
semantic executor, and first runtime hooks now exist. The next major step is
richer live context export plus mixed-policy evaluation focused on whether
agents join whispers and complete role exchanges.

This sequence keeps the value of the existing Eurydice work while moving the
strategic center of gravity from brittle symbolic policy to model-guided social
judgment.
