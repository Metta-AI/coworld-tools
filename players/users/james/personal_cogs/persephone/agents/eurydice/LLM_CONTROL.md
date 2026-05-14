# Eurydice LLM Control Plan

This document defines how Eurydice should move from mostly rule-based
strategy to LLM-assisted control without giving up deterministic safety
contracts, traceability, or pytest coverage.

For the comprehensive source-verified migration report and phased rollout,
see [`LLM_STRATEGY_MIGRATION.md`](LLM_STRATEGY_MIGRATION.md). This file is the
shorter contract reference for the current LLM boundary.

Current status: `agents/eurydice/llm_context.py` builds a JSON-safe v2 context
packet and exposes a closed v2 decision schema. `agents/eurydice/llm_validator.py`
validates model-shaped decisions against that packet and can emit compact
shadow trace events. `llm_prompts.py`, `llm_provider.py`, `llm_shadow.py`,
`llm_executor.py`, and `llm_action_mode.py` now provide strategic prompts,
deterministic providers, a standard-library AWS Bedrock Haiku provider,
offline shadow runs, semantic execution, and model-call cooldowns. Eurydice can
optionally use provider output at runtime: `targets` only permits probe-target
overrides, `whispers` only permits the mode-local whisper hook, and `all`
permits every validated executor-backed semantic action in the current view,
including global chat, leader-summit chat, movement/open-view actions,
leadership seeking, and hostage selection. External model calls remain opt-in;
`hold` is still the default provider.

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
schema version `eurydice.llm_context.v2`.

The context includes:

- self identity: role, team, room, leader status, position, visual player ID;
- strategic state: objective, urgency, partner/enemy-key facts, probe coverage;
- match config: round schedule, role-summary data, Spy-in-game flag;
- player records: known team/role, confidence, sources, position, whisper state,
  exchanges with us, behavioral flags, interaction counts;
- recent messages: bounded chat history from whisper/global;
- legal actions for the current view;
- runtime affordances: current mode/task, cooldowns, pending entry, active
  offers, current whisper occupants, last exchange event, hostage-grid options,
  active probe state, and recent probe failures;
- action affordances describing target/message/destination/offer preconditions;
- hard constraints the model must obey.

The packet intentionally avoids raw frame data, large traces, and Python enum
objects. The prompt layer cites this context as structured data instead of
asking the model to infer game state from prose.

### Provider Configuration

Runtime provider choices:

- `hold`: deterministic no-op provider, default.
- `heuristic`: deterministic fake provider for plumbing tests and trace audits.
- `haiku`, `bedrock-haiku`, or `bedrock`: real AWS Bedrock Claude Haiku
  provider.

The Bedrock provider uses standard-library HTTPS plus SigV4 signing, so it does
not require `anthropic` or `boto3`. Credential resolution order is:

1. `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / optional
   `AWS_SESSION_TOKEN`;
2. ECS/container credentials via `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` or
   `AWS_CONTAINER_CREDENTIALS_FULL_URI`;
3. local AWS CLI export through
   `aws configure export-credentials --format env-no-export`.

Model/config environment variables:

- `EURYDICE_LLM_MODEL` or `EURYDICE_BEDROCK_MODEL` override the model;
- `COGAMES_LLM_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL`, and `ANTHROPIC_MODEL` are
  also honored as compatibility fallbacks;
- default model is `us.anthropic.claude-haiku-4-5-20251001-v1:0`;
- `AWS_REGION` / `AWS_DEFAULT_REGION` select the Bedrock region, default
  `us-east-1`;
- `EURYDICE_LLM_MAX_TOKENS` defaults to `512`;
- `EURYDICE_LLM_TEMPERATURE` defaults to `0.2`;
- `EURYDICE_LLM_TIMEOUT_MS` defaults to `12000`;
- `EURYDICE_LLM_COOLDOWN_TICKS` defaults to `48` so live runs do not call the
  model every frame.

Local example:

```sh
PYTHONPATH=. .venv/bin/python run_agents.py eurydice:10 \
  --llm-control all \
  --llm-provider haiku \
  --log-level decisions
```

For tournament upload, request platform Bedrock credentials with cogames'
`--use-bedrock` option and pass Eurydice's own runtime provider flag in the
agent command/config as usual.

### Output

`llm_decision_schema()` returns the closed response contract with schema version
`eurydice.llm_decision.v2`.

Allowed actions are:

- `hold`
- `probe_player`
- `create_whisper`
- `join_whisper`
- `grant_entry`
- `deny_entry`
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

Every decision must include confidence and a short rationale. Optional
`target` uses `PlayerID` as `[color, shape]`. `move_to` uses
`destination: [x, y]`. `select_hostage` uses `hostage_targets`. Optional
message text is capped at 48 ASCII characters before runtime use.

### Validation

`validate_llm_decision(decision, context)` is the deterministic gate that every
future model output must pass before any executor sees it. It rejects:

- malformed schema versions, unknown fields, unknown actions, and invalid
  confidence/rationale values;
- actions not legal in the current view;
- missing, unknown, or self targets for target-required actions;
- probe targets that are neither visible nor position-known;
- exchange actions without a target unless exactly one non-self whisper
  occupant exists;
- accept actions when there is no active offer from that target;
- grant/deny entry actions that do not match the pending requester;
- move actions without destination or outside the known room bounds;
- hostage selection without hostage targets, with duplicate targets, with the
  wrong required target count, or with targets absent from the parsed hostage
  grid when grid options are available;
- exchange actions against players outside the current whisper;
- non-ASCII, overlong, or unsupported mechanical-claim messages;
- false first-person role/team claims such as `I AM PERSEPHONE`, unless the
  current objective explicitly permits deception or cover;
- implied false self-claims such as `DEMETER HERE`; questions such as
  `HADES HERE?` remain allowed;
- unsupported role-possession claims such as `I HAVE CERBERUS` unless self or
  a player has that role from mechanical role evidence;
- role reveals to known enemies unless the current objective is explicitly
  disruptive or cover-maintaining;
- color reveals while Spy risk is active unless the current objective explicitly
  permits disruption or cover maintenance.

### Executor Safeguards

Validated model decisions still execute through deterministic tasks and modes.
`LLMActionMode`, `HostageSelectMode`, and `HoldPositionMode` complete into idle
when the live view has moved past the surface where the action was legal. This
prevents stale Bedrock responses from sending whisper text in global chat,
continuing movement during hostage exchange, or repeatedly logging
`valid_views_mismatch` after a phase transition. `SendMessageTask` treats
`View.LEADER_SUMMIT` as whisper-like and no-ops if a whisper-channel message is
attempted outside whisper/summit.

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

Current implementation: `scripts/evaluate_eurydice_llm_shadow.py` can evaluate
saved context JSON/JSONL packets with deterministic `hold` or `heuristic`
providers.

### Stage 2: Advisory Runtime

Call the LLM live, validate its decision, and let deterministic policy decide
whether to use or ignore it. The fallback rule directive must remain available.

Trace metrics:

- LLM latency budget does not cause staleness spikes;
- accepted LLM actions improve probe completion or useful message rate;
- rejected decisions are categorized by validator reason;
- fallback frequency trends down as prompts improve.

Current implementation: `--llm-control shadow` calls the provider live and
traces validation results without replacing the deterministic directive.

### Stage 3: Constrained Control

Let the LLM choose among a small set of executor-backed actions in selected
contexts:

- whisper message/reveal choices while already in whisper;
- global message/open-info decisions while in room chat;
- probe target selection during `probe_systematic`.

Current implementation: `--llm-control targets` can replace deterministic
`probe_systematic` with a validated `probe_target`; `whispers` enables a
mode-local hook for pending-entry and first-message decisions. Providers are
`hold`, `heuristic`, and opt-in Bedrock Haiku aliases.

### Stage 4: Broad Semantic Control

Use LLM control for cross-room coordination, deception, leader requests,
hostage picks, movement/open-view actions, and global room planning, with
deterministic safety filters still enforcing the contract.

Current implementation: `--llm-control all` routes normal evaluator outputs and
eligible phase overrides through the LLM controller. Accepted non-`hold`
decisions may replace the deterministic directive with any registered
executor-backed mode/action: `probe_target`, `llm_action`, `seek_leadership`,
or `hostage_select`. `hold` deliberately keeps the deterministic fallback so
the model can decline control without causing mode churn. Raw button presses,
dynamic mode creation, unsupported exchange facts, illegal view actions, and
invalid hostage targets remain blocked by deterministic code.

Live validation on May 11, 2026:

- default three-round Haiku self-play still drew with no completed key-pair
  role exchanges;
- after executor and validator hardening, a short Haiku smoke run accepted
  `select_hostage` actions, produced no provider errors, and produced
  `valid_views_mismatch=0`;
- the remaining strategic blocker is getting agents to join whispers and
  complete role exchanges, not basic semantic action legality.

---

## Immediate Engineering Tasks

1. [x] Add trace event names and a helper for `llm_context`, `llm_decision`,
   `llm_decision_rejected`, and `llm_decision_accepted`.
2. [x] Add a deterministic validator that checks action legality, target
   presence, message length/ASCII, and reveal constraints.
3. [x] Add a shadow-mode runner over saved contexts.
4. [x] Add prompt templates for the three first control surfaces:
   `probe_player`, `send_whisper`, and `send_global`.
5. [x] Add a semantic executor and deterministic runtime flags for target
   selection plus first whisper decisions.
6. [x] Expand `--llm-control all` to every validated scaffolded semantic
   action, including global chat, leader-summit chat, movement/open-view
   actions, leadership seeking, and hostage selection.
7. [ ] Add richer evaluation scripts for useful-message rate, probe completion
   rate, illegal-action rate, and strategic consistency.
8. [x] Add a real LLM provider adapter behind the existing explicit
   configuration flag.
9. [x] Add model-call cooldowns so live Bedrock control cannot call once per
   frame.
10. [ ] Add richer live context export and model-vs-rule evaluation metrics.

---

## Safety Constraints

- Never let the LLM press buttons directly. It chooses semantic actions; tasks
  execute mechanics.
- Never let the LLM create unsupported modes at runtime.
- Never let the LLM overwrite stronger mechanical knowledge with chat claims.
- Never rely on LLM memory across ticks; all state must be in the context.
- Always trace context hash, action, confidence, rationale, validator result,
  and fallback action.
