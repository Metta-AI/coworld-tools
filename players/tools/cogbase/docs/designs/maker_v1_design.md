# maker_v1: Agent Generation And VLM Visual Bootstrap Design

## Status

Design plus partial implementation. Phase 1 plan artifacts, Phase 2 symbolic
agent scaffolds, Phase 3 visual starter agents/VLM contract tooling, and Phase
4 offline visual bootstrap are implemented under `testbed/maker_v1/`. Visual
and mixed games now receive a live `run_agent.py` when the guide proves a
serializable action wire contract, such as binary button-mask packets. The
generated live runners use `agent/cyborg_agent.py` to wrap starter policies in
the generic Cyborg framework from the configured `coborg_framework` checkout.
Phase 4
can label image fixtures through either the deterministic mock adapter or AWS
Bedrock Claude. Maker also generates source-grounded decoder implementations
and label-derived starter policies. Maker can run local smoke tests against a
supplied server command or already-running server. Automatic run-config
discovery, deterministic parser generation, and submission packaging are not
implemented yet.

## Summary

`maker_v1` is the next meta-pipeline toolkit after `guide_v1`.
`guide_v1` turns a game source tree into source-grounded understanding
artifacts, including a machine-readable `guide_contract.json`. `maker_v1`
consumes that contract first, uses Markdown extraction only as a compatibility
fallback, and generates a runnable baseline agent artifact.

The key design challenge is perception. Some games expose symbolic player
observations, some expose pixels or render packets, and some expose mixed or
alternate channels. `maker_v1` should handle all three without reviving the
`eyes_v1` problem of trying to build a complete visual explorer before any
perception system exists.

For visual games, `maker_v1` uses a vision-language model (VLM) as a slow,
schema-bound bootstrap oracle. The VLM helps classify frames, identify UI
states, label fixtures, and recommend safe next actions while deterministic
parsers and controllers are still weak. Over time, generated perception code,
fixtures, and tests should replace VLM calls. The final submitted agent should
prefer deterministic code and should not depend on an external VLM unless the
target environment explicitly allows that.

## Goals

- Generate a working baseline agent from a `guide_v1` guide bundle.
- Support symbolic, visual, and mixed observation interfaces.
- Standardize VLM usage so outputs are predictable, cacheable, testable, and
  safe to compile into deterministic perception artifacts.
- Use the VLM less over time as frame fixtures, parsers, and control policies
  improve.
- Keep all generated game-specific code and data under an artifact directory.
- Produce an agent that can be run, tested, iterated, and eventually submitted
  through the target cogames/co-games contract.

## Non-Goals

- Do not replace `guide_v1` as the source of game understanding.
- Do not make the VLM the final policy for normal play.
- Do not trust VLM claims about hidden state, rules, rewards, or source behavior
  unless those claims are backed by guide/source evidence or visible frame
  evidence.
- Do not require complete automatic visual exploration before agent generation
  begins.
- Do not treat generated parsers, fixtures, or agents as toolkit code.

## Pipeline Position

```text
game source
  -> guide_v1
     -> guide bundle
        guide_contract.json
        README.md
        INTERFACE_CONTRACT.md
        OBSERVATION_DECODING.md
        ACTION_SEMANTICS_AND_CONTROL.md
        ...
  -> maker_v1
     -> agent build plan
     -> runnable control shell
     -> perception artifacts
     -> baseline policy
     -> tests and fixtures
     -> submit-ready agent package
```

`maker_v1` should start from `guide_v1/output/<game>/`, not directly from an
unstructured source tree. It may inspect source files when needed, but its
first input is the guide bundle, and its preferred machine input is
`guide_contract.json`.

## Inputs

Required for the full design:

- `guide_dir`: generated `guide_v1` artifact bundle.
- `guide_contract.json`: preferred machine-readable contract inside
  `guide_dir`, schema version `guide.contract.v1`.
- `agent_framework`: path/package handoff from the guide contract or
  `--agent-framework-dir`; defaults to the generic Cyborg framework checkout.
- `game_source`: target game source directory.
- `output_dir`: artifact directory for generated agent work.
- `run_config`: command or environment details for starting the game locally.

Current generation requires only `guide_dir`. `output_dir` is optional and
defaults to `./output/<guide-dir-name>`; `game_source` is optional metadata
recorded in the manifest. `agent_framework` is optional because Maker can read
it from the guide contract or resolve it from `COGBASE_AGENT_FRAMEWORK_DIR`,
`~/metta/cogames-agents/coborg_framework`, or
`~/coding/metta/cogames-agents/coborg_framework`, or
`~/coding/metta2/metta/cogames-agents/coborg_framework`. If
`guide_contract.json` is present, Maker uses it for observation classification,
observation-decoder hints, action candidates, action wire serialization,
runtime notes, and framework handoff; if it is missing, Maker falls back to
Markdown extraction and records that fallback in the manifest. For runnable
symbolic or visual scaffolds, Maker validates the selected Cyborg package before
writing output artifacts. The
offline Phase 4 bootstrap additionally requires `--visual-bootstrap
--frames-dir <dir>`. Local smoke testing accepts an explicit `--agent-url` and
may start a user-supplied `--server-command`, but automatic `run_config`
discovery is not implemented yet.

Optional:

- Known season/cogames upload contract.
- Existing player templates.
- Existing frame fixtures or replays.
- Human seed instructions for rare visual states.
- VLM provider config.

## Outputs

One generated game artifact bundle:

```text
output/<game_slug>/
  maker_manifest.json
  AGENT_BUILD_PLAN.md
  agent/
    README.md
    framework_bootstrap.py
    cyborg_agent.py
    run_agent.*
    policy.*
    policy_from_labels.py
    connection.*
    control.*
    perception/
      decoder_spec.json
      DECODER_GENERATION_TASK.md
      decoder.py
    tests/
  visual_bootstrap/
    play_card.md
    vlm_request_schema.json
    vlm_schema.json
    prompts/
    frames/
    labels/
    cache/
    parser_tasks/
  smoke_tests/
    runs/
    logs/
    live_runs/
  runs/
    exploration_*/
    eval_*/
  submit/
    ...
```

The exact language and package layout should follow the target game's existing
agent conventions where possible.

`framework_bootstrap.py` points generated artifacts at the configured
`cogames_agents.cyborg` package. `cyborg_agent.py` is the generated adapter
that defines game-specific percept, belief, mode, strategy, and action
resolution functions for `AgentRuntime`; `policy.py` and `protocol.py` remain
small helpers for policy iteration and serialization tests.

## Observation-Surface Branching

`maker_v1` begins by loading `guide_contract.json` when available, then writes
an `AGENT_BUILD_PLAN.md` from the contract plus the guide Markdown. Older guide
bundles without a contract are still supported by Markdown extraction, but the
contract is the intended stable API between Guide and Maker.

### Symbolic Primary

If the player receives symbolic JSON, token arrays, game-state objects, or
another structured non-pixel observation:

1. Generate a typed observation decoder.
2. Generate a minimal valid action loop.
3. Generate rule-based baseline policy logic from the guide bundle.
4. Add unit tests for schemas and action validation.
5. Run integration smoke tests.

No VLM is required.

### Visual Primary

If the player receives pixels, packed framebuffers, screenshots, or render
packets:

1. Generate a connection/control shell.
2. Generate a conservative macro-action library from
   `ACTION_SEMANTICS_AND_CONTROL.md`.
3. Start with a minimal deterministic parser for frame shape, basic phase
   signatures, and known static UI locations.
4. Use the VLM only when the deterministic parser is uncertain, a frame appears
   novel, or a guided exploration task needs visual interpretation.
5. Save VLM-labeled frames as fixtures.
6. Generate deterministic parser tests from those labels.
7. Generate and refine parser code until known frames no longer require VLM
   calls.

### Mixed Or Alternate

If the primary interface is visual but source exposes a structured player path,
native observation array, replay/global viewer, or other side channel:

1. Prefer admissible player-facing structured data when it is part of the
   actual agent contract.
2. Use replay/global/native data as build-time supervision only when it would
   not be available to the submitted agent.
3. Record which data sources are online-admissible, build-time-only, or
   debugging-only in `maker_manifest.json`.

## Architecture

### Components

`MakerController`

- Owns the build loop.
- Reads guide artifacts.
- Produces `AGENT_BUILD_PLAN.md`.
- Dispatches code generation, runtime exploration, VLM labeling, and tests.

`GuideIndexer`

- Loads `guide_contract.json` when present and treats it as the preferred
  machine-readable guide API.
- Parses Markdown into small, retrievable facts when the contract is absent or
  a field is missing.
- Extracts action names, observation schema, view names, phase names,
  invariants, lifecycle rules, and known failure modes.
- Builds the compact per-game VLM context card.

`RuntimeHarness`

- Starts and stops the game.
- Connects generated agents.
- Captures raw observations, actions, logs, rewards, and terminal status.
- Supports deterministic seeds and replay when the game allows it.

`ObservationRouter`

- Receives raw observations.
- Sends symbolic observations to typed decoders.
- Sends visual observations to deterministic parsers first.
- Escalates only selected visual frames to the VLM.

`DeterministicPerception`

- Game-specific generated code.
- Classifies known views.
- Extracts stable visual fields.
- Computes confidence and uncertainty.
- Should grow over time and reduce VLM usage.

`VlmOracle`

- Provider-adapter layer around one or more VLMs.
- Accepts a standardized request.
- Returns a strict schema.
- Never directly writes agent state or sends actions.

`ActionController`

- Converts policy decisions or VLM recommendations into valid primitive
  packets or semantic actions.
- Rejects invalid actions.
- Applies timing, debounce, action-repeat, and safe fallback rules.

`ArtifactStore`

- Stores frames, labels, prompt contexts, response JSON, parser tasks, caches,
  test fixtures, and run summaries.
- Version-stamps every artifact.

`ParserBuilder`

- Turns accumulated labeled frames into parser tasks, tests, and code changes.
- Measures parser coverage against fixtures.

`Evaluator`

- Runs smoke tests, fixture tests, and local episodes.
- Reports VLM-call rate, parser confidence, survival/completion, invalid
  action rate, and coverage.

## VLM Role

The VLM is a build-time and exploration-time oracle. It answers narrow
questions about a current visual observation. It should not be given authority
over the whole agent.

Allowed VLM jobs:

- Classify the current view or phase.
- Read visible text.
- Identify visible entities, UI elements, markers, menus, cursors, and
  affordances.
- Estimate coordinates or regions for visible objects.
- Decide whether a frame is new, a variant, or known.
- Recommend the next safe action from an allowed action list.
- Explain uncertainty and propose parser targets.

Disallowed VLM jobs:

- Assert hidden roles, hidden cards, hidden map state, or unseen inventory as
  fact.
- Invent actions not in the guide-derived action registry.
- Modify code.
- Write persistent memory directly.
- Override controller safety checks.
- Decide that source or guide facts are wrong without source evidence.

## VLM Standardization

### Prompt Layers

Every VLM call has the same layers:

1. **Static system contract**
   - You are a visual observation parser for a game agent.
   - Return only JSON matching the schema.
   - Separate observed facts from inferences.
   - Never infer hidden state as fact.
   - Choose actions only from the supplied action registry.

2. **Per-game play card**
   - Compact context generated from the guide bundle.
   - Stable for a guide version.
   - Small enough to include in every VLM call.

3. **Current run context**
   - Current frame id and timestamp.
   - Recent view/action history.
   - Current deterministic parser output and uncertainties.
   - Current exploration objective.

4. **Image payload**
   - Current frame.
   - Optional cropped regions selected by the parser/controller.

5. **Response schema**
   - Strict JSON schema.
   - No freeform prose outside schema fields.

### Per-Game Play Card

The play card is generated once per guide version:

```text
Game: <name>
Observation contract: <visual primary | symbolic primary | mixed>
Frame format: <shape, encoding, palette, known coordinate system>
View ids: <short list from STATE_AND_VIEW_MODEL>
Action registry: <primitive actions and macro actions>
Important UI conventions: <short bullets>
Hidden information rules: <short bullets>
Objective summary: <short bullets>
Do not assume: <hidden state, debug-only channels, etc.>
```

The play card should be small. It is not a copy of the guide bundle. If more
context is needed, `GuideIndexer` retrieves a short targeted snippet and records
the snippet id in the VLM request.

### VLM Response Schema

All VLM responses should conform to a versioned schema like this:

```json
{
  "schema_version": "maker.vlm_frame.v1",
  "request_id": "string",
  "frame_id": "string",
  "view": {
    "id": "string",
    "confidence": 0.0,
    "evidence": ["string"]
  },
  "phase": {
    "id": "string",
    "confidence": 0.0,
    "evidence": ["string"]
  },
  "visible_text": [
    {
      "text": "string",
      "region": {"x": 0, "y": 0, "w": 0, "h": 0},
      "confidence": 0.0
    }
  ],
  "ui_elements": [
    {
      "kind": "button|menu|cursor|timer|score|chat|label|unknown",
      "label": "string",
      "region": {"x": 0, "y": 0, "w": 0, "h": 0},
      "state": "active|inactive|selected|disabled|unknown",
      "confidence": 0.0
    }
  ],
  "entities": [
    {
      "kind": "self|player|opponent|item|body|hazard|objective|unknown",
      "label": "string",
      "region": {"x": 0, "y": 0, "w": 0, "h": 0},
      "attributes": {},
      "confidence": 0.0
    }
  ],
  "state_observations": [
    {
      "key": "string",
      "value": "string|number|boolean|null",
      "status": "observed|inferred|guide_prior",
      "confidence": 0.0,
      "evidence": ["string"]
    }
  ],
  "available_actions": [
    {
      "action_id": "string",
      "confidence": 0.0,
      "evidence": ["string"]
    }
  ],
  "recommended_action": {
    "action_id": "string",
    "parameters": {},
    "confidence": 0.0,
    "rationale": "string",
    "fallback_action_id": "string"
  },
  "novelty": {
    "status": "known|variant|new|uncertain",
    "save_frame": true,
    "reason": "string"
  },
  "parser_targets": [
    {
      "target": "string",
      "why": "string",
      "suggested_test": "string"
    }
  ],
  "memory_updates": [
    {
      "key": "string",
      "value": "string|number|boolean|null",
      "status": "candidate",
      "confidence": 0.0,
      "evidence": ["string"]
    }
  ],
  "uncertainty": [
    {
      "field": "string",
      "reason": "string",
      "needed_next": "string"
    }
  ]
}
```

Rules:

- `view.id`, `phase.id`, and `action_id` must come from controlled
  vocabularies, with `unknown` allowed.
- Coordinates use frame pixels with origin at top-left.
- Confidence is always `0.0` to `1.0`.
- `state_observations.status` must distinguish visible facts from inference.
- `memory_updates` are proposals. The controller decides whether to commit.
- `recommended_action.action_id` must be validated by `ActionController`.

### Request Record

Each VLM call writes a request record:

```json
{
  "schema_version": "maker.vlm_request.v1",
  "request_id": "string",
  "guide_bundle_hash": "string",
  "play_card_hash": "string",
  "frame_id": "string",
  "run_id": "string",
  "objective": "string",
  "allowed_views": ["string"],
  "allowed_actions": ["string"],
  "recent_history": [
    {"view": "string", "action_id": "string", "outcome": "string"}
  ],
  "parser_summary": {},
  "retrieved_context_ids": ["string"]
}
```

This makes VLM outputs reproducible enough to audit, cache, and compare across
prompt versions.

### Provider Adapter Requirements

The VLM adapter should:

- Support strict JSON mode when available.
- Validate every response against the schema.
- Retry malformed responses with a repair prompt at most once.
- Cache by image hash, play-card hash, request objective, and schema version.
- Record model id, provider id, temperature, max tokens, and response latency.
- Expose a deterministic interface to the rest of `maker_v1`.

## VLM Context Budgeting

The VLM should receive enough context to be useful, not the full guide bundle.

Default context:

- Static VLM system contract.
- Per-game play card.
- Current objective.
- Last 5 to 20 compact history events, depending on game pace.
- Deterministic parser summary.
- Current frame.

Optional retrieved context:

- One short excerpt from `INTERFACE_CONTRACT.md` if action/observation schema is
  relevant.
- One short excerpt from `STATE_AND_VIEW_MODEL.md` if view classification is
  uncertain.
- One short excerpt from `ACTION_SEMANTICS_AND_CONTROL.md` if action choice is
  uncertain.

Avoid:

- Full guide documents.
- Full source files.
- Long strategic policy text.
- Prior raw VLM transcripts except as summarized memory.

## Exploration Loop

```text
start run
  -> receive observation
  -> deterministic parser attempts decode
  -> if symbolic or parser confidence high:
       policy/controller chooses action
     else if frame is novel or objective needs visual interpretation:
       VLM labels frame and recommends action
       controller validates recommendation
       artifact store saves frame + label
     else:
       use safe fallback action
  -> send action
  -> update run memory
  -> periodically build parser tasks from labels
  -> generate parser tests/code
  -> rerun fixtures and episodes
  -> reduce VLM gate as parser coverage grows
```

## VLM Call Gating

The controller decides whether to call the VLM. It should call only when at
least one condition is true:

- View classifier confidence is below threshold.
- A frame has a novel perceptual hash or new UI text/layout signature.
- The current view is known but a critical field is unknown.
- The agent is stuck and deterministic recovery failed.
- A planned parser test needs a label.
- A human/operator requested annotation.

The controller should not call the VLM when:

- Symbolic decoding is complete.
- The frame matches a known fixture with high confidence.
- The action is a simple timed wait or repeated movement with no new visual
  decision.
- The VLM budget for the run is exhausted.

## Reducing VLM Usage Over Time

`maker_v1` should track VLM dependence as a first-class metric:

- VLM calls per episode.
- VLM calls per minute.
- Percentage of frames handled by deterministic parser.
- Number of unique view signatures known.
- Number of parser fields covered by tests.
- Number of action decisions made without VLM.

Reduction mechanisms:

- Cache repeated VLM calls.
- Generate parser tests from every saved label.
- Promote stable VLM labels into deterministic fixtures only after validation.
- Add parser code for high-frequency uncertain fields first.
- Use confidence thresholds that get stricter over iterations.
- Use VLM only for unknown or low-confidence states once the baseline is
  functional.

Graduation target for a visual MVP:

- Agent can complete a local smoke episode without VLM calls on known seeds.
- VLM is needed only for novel/rare states or explicit annotation runs.
- Fixture tests cover every view needed for the MVP path.
- Invalid action rate is near zero.

## Action Control

The VLM should recommend actions from an action registry, not raw arbitrary
instructions.

The action registry is generated from the guide bundle:

```json
{
  "primitive_actions": [
    {"id": "noop", "wire": "..."},
    {"id": "up", "wire": "..."},
    {"id": "down", "wire": "..."},
    {"id": "interact", "wire": "..."}
  ],
  "macro_actions": [
    {
      "id": "open_menu",
      "preconditions": ["view:playing"],
      "steps": [{"action_id": "select", "ticks": 1}]
    }
  ]
}
```

The controller validates:

- action id exists;
- action is allowed in the current view;
- parameters are valid;
- timing/debounce constraints are satisfied;
- a fallback action exists.

If validation fails, the controller records the failure and uses a safe fallback
such as `noop`, `wait`, or a guide-derived recovery macro.

## Memory Model

The controller owns memory. The VLM receives a compact memory summary and may
propose updates, but it cannot commit them directly.

Memory categories:

- `episode`: current phase, recent actions, current objective, local counters.
- `belief`: uncertain inferences with confidence and evidence.
- `map`: discovered static layout or known visual landmarks.
- `ui`: known view signatures and parser confidence.
- `fixtures`: saved frames and labels.

Every belief update should include:

- source: parser, VLM, guide prior, or human;
- confidence;
- evidence;
- timestamp/frame id;
- expiry or invalidation condition when relevant.

## Parser Build Loop

VLM labels are not the end product. They feed deterministic parser generation.

Loop:

1. Group saved frames by view id, novelty, and parser target.
2. Generate fixture expectations from validated labels.
3. Write parser tests first.
4. Generate or update parser code.
5. Run fixture tests.
6. Run local episodes.
7. Compare parser output to VLM/human labels.
8. Lower VLM call rate for covered fields.

Parser code should prefer simple deterministic methods before complex models:

- frame dimensions and packet decoding;
- exact color/palette checks;
- template matching for stable UI elements;
- OCR only where text is necessary and stable enough;
- sprite/object record parsing when available;
- small learned classifiers only when deterministic methods are inadequate.

## Artifact Versioning

Every visual artifact should carry:

- game slug;
- guide bundle hash;
- maker version;
- VLM schema version;
- prompt version;
- model/provider id;
- frame hash;
- source run id;
- parser version that consumed it.

This prevents stale VLM labels from silently contaminating newer parser work.

## Validation

Minimum validation for `maker_v1` itself:

- Contract ingestion tests proving `guide_contract.json` wins over stale or
  contradictory Markdown.
- Unit tests for guide indexing and play-card generation.
- Schema validation tests for VLM requests and responses.
- VLM mock tests with malformed JSON, unknown actions, low confidence, and
  hidden-state hallucinations.
- Action-controller tests for invalid action rejection and safe fallback.
- Fixture-store tests for frame hashing, cache keys, and version stamps.

Minimum validation for a generated agent:

- Decoder/parser unit tests.
- Action serialization tests.
- Local connection smoke test.
- One short local episode or deterministic replay test.
- No unvalidated VLM action reaches the wire.
- For visual games, known fixture frames do not require VLM calls.

## Safety And Trust Boundaries

- The guide bundle is project truth unless contradicted by source evidence.
- `guide_contract.json` is the preferred machine API for the guide bundle;
  Markdown is the richer human reference and a compatibility fallback.
- The VLM is a fallible observation labeler.
- VLM outputs are evidence, not code and not committed memory.
- The action controller is the only component allowed to send actions.
- Debug/global/replay channels must be marked as online-admissible,
  build-time-only, or forbidden.
- The final submitted agent should not require external network calls unless the
  target environment explicitly allows them.

## Failure Modes And Mitigations

| Failure Mode | Mitigation |
|---|---|
| VLM hallucinates hidden state | Require `observed/inferred/guide_prior`; reject hidden facts without visible evidence |
| VLM emits invalid action | Validate against action registry; use fallback |
| VLM labels are inconsistent | Cache, schema validation, fixture tests, optional human review for promoted labels |
| VLM latency stalls live play | Use offline annotation, local slow-mode runs, action repeats, or safe wait macros |
| Context is too large | Use play card plus targeted retrieved snippets only |
| Rare views never appear | Use guide-derived scenario plans, source instrumentation, replays, or human seed captures |
| Parser overfits one frame | Require multiple fixtures per view/variant before promotion |
| Generated code treats artifacts as toolkit | Keep all outputs under `output/<game>/` and mark them as generated |

## CLI

```bash
# Current implementation: build plan artifacts and symbolic scaffolds
python generate_agent.py \
  ../guide_v1/output/persephones_escape \
  --game-source /path/to/persephones_escape \
  --output-dir ./output/persephones_escape \
  --plan-only

# Current implementation: decode raw observations, label frames, and seed policy rules
python generate_agent.py \
  ../guide_v1/output/persephones_escape \
  --output-dir ./output/persephones_escape \
  --visual-bootstrap \
  --frames-dir ./seed_frames/persephones_escape \
  --decode-observations \
  --vlm-provider bedrock \
  --build-policy-from-labels \
  --vlm-budget 50

# Future: iterate parser generation from saved labels
python generate_agent.py \
  ../guide_v1/output/persephones_escape \
  --output-dir ./output/persephones_escape \
  --update-parsers

# Current implementation: run the generated agent against a local server
python generate_agent.py \
  ../guide_v1/output/persephones_escape \
  --output-dir ./output/persephones_escape \
  --smoke-test \
  --server-command 'python path/to/server.py --port 2000' \
  --server-cwd /path/to/game \
  --health-url http://127.0.0.1:2000/healthz \
  --agent-url 'ws://127.0.0.1:2000/player?name=maker_smoke'
```

`--visual-bootstrap` currently labels files from `--frames-dir` using
`--vlm-provider mock` or `--vlm-provider bedrock`. The Bedrock provider uses
`boto3` and the local AWS credential chain to call AWS Bedrock Converse with a
Claude model. `MAKER_V1_BEDROCK_MODEL_ID` overrides the default model, and
`MAKER_V1_BEDROCK_REGION` overrides `AWS_REGION`/`AWS_DEFAULT_REGION`. The
default model/profile id is `us.anthropic.claude-sonnet-4-20250514-v1:0`.
Bedrock labeling requires PNG, JPEG, GIF, or WebP image bytes. If `--frames-dir`
contains raw observations, `--decode-observations` runs the generated
`agent/perception/decoder.py` before spending VLM budget.
`--build-policy-from-labels` reads schema-valid labels and writes
`agent/policy_from_labels.py` plus `agent/POLICY_BOOTSTRAP.md`. From a clean
checkout, Bedrock commands should run through `uv run python` so the `boto3`
dependency is available. Direct `--vlm-provider openai` and
`--vlm-provider anthropic` adapters remain future work. `--update-parsers`
belongs to a later implementation phase and still fails fast.

`--smoke-test` runs the generated `agent/run_agent.py` in a subprocess. It can
connect to an already-running server via `--agent-url`, or start a server first
with `--server-command`, optionally in `--server-cwd` and gated by
`--health-url`. Reports are written to `smoke_tests/runs/`; server logs go under
`smoke_tests/logs/`; generated visual-agent live captures go under
`smoke_tests/live_runs/`. This validates that the generated runner starts,
connects, sends serialized actions, and exits under the configured timeout. It
does not yet infer how to start arbitrary games automatically.

## Proposed Directory Layout

```text
testbed/maker_v1/
  README.md
  generate_agent.py
  maker_v1/
    __init__.py
    cli.py
    guide_index.py
    build_plan.py
    action_control.py
    artifacts.py
    bootstrap.py
    decoder_spec.py
    policy_builder.py
    smoke.py
    symbolic_agent.py
    visual_agent.py
    runtime.py                  # future automatic run-config discovery
    action_registry.py          # future richer action model
    vlm/
      schema.py
      adapter.py
      cache.py
      validation.py
      prompts.py                # future prompt/module split
    parser_builder.py           # future
    evaluator.py                # future
  output/
    README.md
```

## Implementation Phases

### Phase 1: Plan-Only Maker

- Read guide bundle, preferring `guide_contract.json` over Markdown
  heuristics.
- Produce `AGENT_BUILD_PLAN.md`.
- Classify observation surface.
- Extract action registry and runtime assumptions.
- No VLM calls yet.

Current status: implemented. Maker records `guide_contract_hash` and
`guide_contract_schema_version` in `maker_manifest.json`, marks
`guide_contract_ingestion` when a contract is present, and falls back to
`markdown_contract_fallback` for older bundles.

### Phase 2: Symbolic MVP

- Generate runnable baseline agents for symbolic games.
- Add decoder/action tests.
- Run local smoke tests.

Current status: scaffold generation and action-serialization tests are
implemented. Generated agents include a WebSocket runner, guide-derived action
serialization, and a conservative starter policy. The toolkit smoke harness can
run generated agents against a supplied local server or already-running
WebSocket URL.

### Phase 3: Visual Shell And VLM Schema

- Generate visual-game connection/control shell.
- Implement VLM request/response schema, validator, cache, and mock adapter.
- Generate play card from the guide contract plus guide docs.
- Store frames and labels.

Current status: visual starter agents are generated for visual-primary and
mixed/alternate games. Maker infers action serialization from guide/source
evidence when possible, including binary `[0x00, mask]` button-mask protocols,
and emits `agent/protocol.py`, `agent/policy.py`, and a live `run_agent.py`.
The generated live runner connects to a WebSocket, sends an initial noop,
records incoming frames/messages, decodes raw observations when the generated
decoder can do so, chooses a conservative movement action, and sends only
protocol-serialized actions. Toolkit-level VLM request/response validation,
cache, and mock adapter are implemented. Generated visual artifacts can also
save binary or JSON observations, build schema-shaped VLM requests, and write
mock labels. The toolkit-level Phase 4 runner can call AWS Bedrock Claude for
image fixtures. Generated live starters still do not perform runtime server
orchestration from guide docs or deterministic parser-driven stateful play.

Every guide bundle now also gets `agent/perception/decoder_spec.json` and
`agent/perception/DECODER_GENERATION_TASK.md`, plus a generated
`agent/perception/decoder.py` and decoder tests. These artifacts are generated
from the guide bundle's observation and interface docs. They state whether the
game needs a typed symbolic decoder, can pass through already encoded image
bytes, or needs game-specific raw-observation-to-image decoding before VLM
labeling. The spec deliberately forbids reusing another game's framebuffer,
palette, dimensions, transport, or schema assumptions unless the current game
docs or source rediscover them. When docs expose enough concrete raw-visual
facts, Maker emits a working decoder; otherwise the decoder fails before VLM
spend and tells the operator to improve guide/source evidence.

### Phase 4: VLM-Assisted Exploration

- Run local exploration with a strict VLM budget.
- Save novel frames and structured labels.
- Validate action recommendations through controller.

Current status: offline visual bootstrap over a directory of captured image
frames or raw observations is implemented. The runner can copy already-decoded
frames into `visual_bootstrap/frames` or run raw observations through the
generated decoder into `visual_bootstrap/decoded_frames`. It then builds
schema-validated VLM requests, labels them through either the mock adapter or
AWS Bedrock Claude, writes structured labels under `visual_bootstrap/labels`,
validates the recommended action against the guide-derived action registry, and
writes a run report under `visual_bootstrap/runs`. Live game driving now exists
inside the generated starter agent when the action protocol is known, and the
toolkit smoke harness can execute that agent against a supplied server.
Automatic exploration and automatic local server run-config discovery are still
future work.

### Phase 5: Parser Generation Loop

- Convert labels to parser tests.
- Generate deterministic parser code.
- Track VLM-call reduction metrics.

Current status: a first label-to-policy artifact exists.
`--build-policy-from-labels` reads validated labels and emits
`agent/policy_from_labels.py`, `agent/POLICY_BOOTSTRAP.md`, and tests. This is
a starter policy seed; deterministic parser generation and policy refinement
are still future work.

### Phase 6: Packaging

- Generate submit-ready policy/player package.
- Produce runbook and validation report.
- Ensure generated artifacts are separate from toolkit code.

## Open Questions

- Which VLM providers and local/offline models should be supported first?
- Should `maker_v1` call coding agents directly for parser/code generation, or
  should it emit tasks for Codex/Claude to execute externally?
- What is the minimum local runtime contract each game must expose for
  exploration?
- How much human review should be required before a VLM label becomes a parser
  fixture?
- Which final-agent environments permit external VLM calls, if any?

## Design Principle

The VLM should make unknown visual states legible just long enough for
`maker_v1` to turn them into deterministic artifacts. If VLM usage does not
decrease over iterations, the loop is failing.
