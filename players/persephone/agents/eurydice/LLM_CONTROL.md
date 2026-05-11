# Eurydice LLM Control Plan

This document defines how Eurydice should move from mostly rule-based
strategy to LLM-assisted control without giving up deterministic safety
contracts, traceability, or pytest coverage.

Current status: `agents/eurydice/llm_context.py` builds a JSON-safe context
packet and exposes a closed decision schema. `agents/eurydice/llm_validator.py`
validates future model decisions against that packet and can emit compact
shadow trace events. Eurydice still does not call an LLM, does not import a
provider, and is not wired to let model decisions affect runtime actions.

---

## Why LLM Control

The remaining hard problems are social and adversarial:

- deciding who to probe when information is incomplete;
- deciding whether to reveal role, color, both, or neither;
- deciding what to say in whispers and global chat;
- coordinating room-level action through short messages;
- handling deception, Spy risk, and partial trust;
- adapting when other agents do unexpected things.

Pure local rules can cover mechanical invariants, but they become brittle when
the right move depends on conversation context, opponent intent, or a changing
coalition of uncertain claims. The LLM should own high-level social judgment,
while deterministic code keeps ownership of perception, mechanics, safety
guards, and action execution.

---

## Contract

### Input

`build_llm_context(belief_state, strategic_state)` returns a JSON-safe dict with
schema version `eurydice.llm_context.v1`.

The context includes:

- self identity: role, team, room, leader status, position, visual player ID;
- strategic state: objective, urgency, partner/enemy-key facts, probe coverage;
- match config: round schedule, role-summary data, Spy-in-game flag;
- player records: known team/role, confidence, sources, position, whisper state,
  exchanges with us, behavioral flags, interaction counts;
- recent messages: bounded chat history from whisper/global;
- legal actions for the current view;
- hard constraints the model must obey.

The packet intentionally avoids raw frame data, large traces, and Python enum
objects. The future prompt layer should cite this context as structured data,
not ask the model to infer game state from prose.

### Output

`llm_decision_schema()` returns the closed response contract with schema version
`eurydice.llm_decision.v1`.

Allowed actions are:

- `hold`
- `probe_player`
- `create_whisper`
- `join_whisper`
- `send_whisper`
- `send_global`
- `open_global`
- `open_info`
- `accept_color`
- `accept_role`
- `offer_color`
- `offer_role`
- `reject_offer`
- `exit_whisper`
- `seek_leadership`
- `select_hostage`
- `move_to`

Every decision must include confidence and a short rationale. Optional target
uses `PlayerID` as `[color, shape]`. Optional message text is capped at 48 ASCII
characters before runtime use.

### Validation

`validate_llm_decision(decision, context)` is the deterministic gate that every
future model output must pass before any executor sees it. It rejects:

- malformed schema versions, unknown fields, unknown actions, and invalid
  confidence/rationale values;
- actions not legal in the current view;
- missing, unknown, or self targets for target-required actions;
- probe targets that are neither visible nor position-known;
- exchange actions against players outside the current whisper;
- non-ASCII, overlong, or unsupported mechanical-claim messages;
- role reveals to known enemies unless the current objective is explicitly
  disruptive or cover-maintaining;
- color reveals while Spy risk is active unless the current objective explicitly
  permits disruption or cover maintenance.

`validate_and_trace_llm_decision(...)` wraps validation and emits
`llm_context`, `llm_decision`, and either `llm_decision_accepted` or
`llm_decision_rejected` at decision trace level. The trace records a stable
context hash so saved contexts, model outputs, and fallback behavior can be
correlated without logging raw frame data.

---

## Division Of Labor

Deterministic code remains responsible for:

- frame parsing and belief updates;
- menu navigation, button timing, and task execution;
- hard mechanical invariants, including phase/view legality;
- never inventing mechanical exchange facts;
- refusing illegal actions in the current view;
- trace logging and post-run metrics.

The LLM should eventually be responsible for:

- choosing probe priority among plausible targets;
- selecting whisper protocol intent;
- deciding whether to reveal color or role;
- writing concise whisper/global messages;
- deciding when to ask the room for leadership, hostage movement, or help;
- deciding when to stall, withhold, or deceive as Spy or enemy-facing roles.

---

## Rollout

### Stage 1: Shadow Evaluation

Run the LLM on recorded contexts only. It returns decisions, but the rule stack
still controls the bot.

Trace metrics:

- parseable LLM decision for every sampled context;
- zero illegal actions after deterministic validation;
- decision rationale names the same objective/phase present in context;
- suggested target is visible or known unless action is `hold`/`open_global`;
- no suggestion to reveal true role to known enemy outside deception/disruption.

### Stage 2: Advisory Runtime

Call the LLM live, validate its decision, and let deterministic policy decide
whether to use or ignore it. The fallback rule directive must remain available.

Trace metrics:

- LLM latency budget does not cause staleness spikes;
- accepted LLM actions improve probe completion or useful message rate;
- rejected decisions are categorized by validator reason;
- fallback frequency trends down as prompts improve.

### Stage 3: Constrained Control

Let the LLM choose among a small set of executor-backed actions in selected
contexts:

- whisper message/reveal choices while already in whisper;
- global message/open-info decisions while in room chat;
- probe target selection during `probe_systematic`.

Do not hand over hostage selection, menu/button mechanics, or phase overrides
until earlier stages are stable.

### Stage 4: Full Social Strategy

Use LLM control for cross-room coordination, deception, leader requests, and
global room planning, with deterministic safety filters still enforcing the
contract.

---

## Immediate Engineering Tasks

1. [x] Add trace event names and a helper for `llm_context`, `llm_decision`,
   `llm_decision_rejected`, and `llm_decision_accepted`.
2. [x] Add a deterministic validator that checks action legality, target
   presence, message length/ASCII, and reveal constraints.
3. [ ] Add a shadow-mode runner over saved traces and frame recordings.
4. [ ] Add prompt templates for the three first control surfaces:
   `probe_player`, `send_whisper`, and `send_global`.
5. [ ] Add evaluation scripts for useful-message rate, probe completion rate,
   illegal-action rate, and strategic consistency.
6. [ ] Only then add an LLM provider adapter behind an explicit configuration
   flag.

---

## Safety Constraints

- Never let the LLM press buttons directly. It chooses semantic actions; tasks
  execute mechanics.
- Never let the LLM create unsupported modes at runtime.
- Never let the LLM overwrite stronger mechanical knowledge with chat claims.
- Never rely on LLM memory across ticks; all state must be in the context.
- Always trace context hash, action, confidence, rationale, validator result,
  and fallback action.
