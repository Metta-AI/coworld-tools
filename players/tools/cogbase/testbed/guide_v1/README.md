# guide_v1

Automated generation of comprehensive game guide documents for AI agent
development. Analyzes a game's source code and produces a structured library
of markdown references covering everything needed to go from "never seen this
game" to "working agent that connects, perceives, decides, and acts."

`guide_v1` is intended to be a general-purpose pipeline for Coworld games and
nearby agent/game frameworks. It is not an Among Them-specific tool. The
source directory is an input, the runners inspect that source directly, and
the output documents should describe whatever game, protocol, observations,
actions, and training surfaces the source actually exposes.

`guide_v1` itself is the meta-pipeline toolkit. Generated guide bundles are
artifacts and belong under `output/`. A guide bundle contains human-readable
Markdown plus a machine-readable `guide_contract.json` that downstream
toolkits can consume without depending on prose formatting.

The current implementation accepts local source directories. URL inputs are a
design goal, not part of the implemented CLI yet.

`guide_v1` is now the canonical first stage for new games. It should establish
the player interface contract, classify observations as symbolic, visual, or
mixed, and decide what downstream artifacts are needed before any visual capture
or explorer work begins. Deprecated `eyes_v1` artifacts can still be useful for
targeted visual evidence, but they should be generated only after `guide_v1` or
a human operator identifies a concrete perception need.

The next stage is `maker_v1`, described in
`../../docs/designs/maker_v1_design.md`. It consumes `guide_contract.json`
first, falls back to Markdown when a contract is unavailable, generates
agent-build planning artifacts, and now emits starter symbolic agents for
symbolic-primary games plus capture-only visual shells for visual or
mixed/alternate games. It can also run offline visual bootstrap over captured
image frames using either mock labels or AWS Bedrock Claude labels.

## Design Philosophy

The document suite is organized around four principles:

1. **Contract-first**: The formal observation/action/timing contract is the
   most important technical document and is centralized in one place.

2. **Non-overlapping jurisdiction**: Every fact lives in exactly one document.
   No duplication, no ambiguity about which doc is authoritative.

3. **Layered depth**: Documents are ordered from orientation → operational →
   understanding → architecture → expertise. Developers can stop at any layer
   and have a working (if limited) agent.

4. **Game-agnostic generality**: The structure is designed to work across
   real-time action, turn-based strategy, social deduction, card games,
   platformers, puzzles, and other Coworld-style agent environments.

## Document Suite

### Layer 1: Orientation

| Document | Purpose |
|----------|---------|
| `README.md` | Guide map, reading order, MVP path, document routing |
| `GAME_OVERVIEW.md` | What the game is, classification, entities, vocabulary |

### Layer 2: Agent Contract and Operation

| Document | Purpose |
|----------|---------|
| `INTERFACE_CONTRACT.md` | Formal Gym-style observation/action/reward/timing contract |
| `CONNECTION_AND_EPISODE_LIFECYCLE.md` | Cold-start sequence, protocol, reset, shutdown |
| `MINIMUM_VIABLE_AGENT.md` | Shortest path to a working baseline agent |

### Layer 3: Game Understanding

| Document | Purpose |
|----------|---------|
| `RULES_AND_MECHANICS.md` | Logical game rules independent of encoding |
| `STATE_AND_VIEW_MODEL.md` | Complete state/view graph with transitions |
| `OBSERVATION_DECODING.md` | Raw observations → semantic state bridge |
| `ACTION_SEMANTICS_AND_CONTROL.md` | What actions do (physics, timing, legality) |

### Layer 4: Agent Architecture

| Document | Purpose |
|----------|---------|
| `MEMORY_AND_HIDDEN_INFORMATION.md` | Partial observability, belief tracking, recurrence needs |
| `REWARDS_AND_PROGRESS_SIGNALS.md` | Rewards, shaping candidates, evaluation metrics |
| `TRAINING_AND_EVALUATION.md` | Parallelism, headless, determinism, replay, benchmarking |

### Layer 5: Reliability and Expertise

| Document | Purpose |
|----------|---------|
| `ERROR_RECOVERY_AND_ROBUSTNESS.md` | Failure detection, recovery, stuck-loop handling |
| `STRATEGY_AND_POLICY_GUIDE.md` | Heuristics, tactics, architecture recommendations |
| `IMPLEMENTATION_NOTES.md` | Source-code internals for debugging/validation |

## Reading Paths

### MVP Critical Path (get a working agent fast)

1. `README.md`
2. `GAME_OVERVIEW.md`
3. `INTERFACE_CONTRACT.md`
4. `CONNECTION_AND_EPISODE_LIFECYCLE.md`
5. `MINIMUM_VIABLE_AGENT.md`

### Expert Path (build a strong agent)

1. MVP path, then:
2. `RULES_AND_MECHANICS.md`
3. `STATE_AND_VIEW_MODEL.md`
4. `OBSERVATION_DECODING.md`
5. `ACTION_SEMANTICS_AND_CONTROL.md`
6. `MEMORY_AND_HIDDEN_INFORMATION.md`
7. `REWARDS_AND_PROGRESS_SIGNALS.md`
8. `TRAINING_AND_EVALUATION.md`
9. `STRATEGY_AND_POLICY_GUIDE.md`

### Robustness/Debugging Path

1. `INTERFACE_CONTRACT.md`
2. `CONNECTION_AND_EPISODE_LIFECYCLE.md`
3. `STATE_AND_VIEW_MODEL.md`
4. `OBSERVATION_DECODING.md`
5. `ERROR_RECOVERY_AND_ROBUSTNESS.md`
6. `IMPLEMENTATION_NOTES.md`

## Document Dependency Graph

```
Stage 1
  GAME_OVERVIEW

Stage 2
  RULES_AND_MECHANICS        depends on GAME_OVERVIEW
  INTERFACE_CONTRACT         depends on GAME_OVERVIEW

Stage 3
  STATE_AND_VIEW_MODEL       depends on RULES_AND_MECHANICS
  CONNECTION_AND_EPISODE_LIFECYCLE
                             depends on INTERFACE_CONTRACT
  TRAINING_AND_EVALUATION    depends on INTERFACE_CONTRACT

Stage 4
  OBSERVATION_DECODING       depends on INTERFACE_CONTRACT, STATE_AND_VIEW_MODEL
  ACTION_SEMANTICS_AND_CONTROL
                             depends on INTERFACE_CONTRACT, STATE_AND_VIEW_MODEL
  MEMORY_AND_HIDDEN_INFORMATION
                             depends on STATE_AND_VIEW_MODEL
  REWARDS_AND_PROGRESS_SIGNALS
                             depends on STATE_AND_VIEW_MODEL
  MINIMUM_VIABLE_AGENT       depends on CONNECTION_AND_EPISODE_LIFECYCLE

Stage 5
  ERROR_RECOVERY_AND_ROBUSTNESS
                             depends on INTERFACE_CONTRACT, STATE_AND_VIEW_MODEL
  STRATEGY_AND_POLICY_GUIDE  depends on RULES_AND_MECHANICS, STATE_AND_VIEW_MODEL

Stage 6
  IMPLEMENTATION_NOTES       depends on all Stage 1-5 documents

Stage 7
  README                     depends on all prior documents
```

## Document Jurisdictions

Each document has exclusive ownership over its concerns. Key boundary rules:

- **INTERFACE_CONTRACT** owns observation/action schemas. No other doc duplicates tensor shapes or action IDs.
- **RULES_AND_MECHANICS** owns logical game rules. No other doc re-explains win conditions or action legality at the rules level.
- **STATE_AND_VIEW_MODEL** owns the state graph. No other doc lists states or transitions authoritatively.
- **OBSERVATION_DECODING** owns the perception-to-state bridge. INTERFACE_CONTRACT defines what you receive; this doc explains how to interpret it.
- **ACTION_SEMANTICS_AND_CONTROL** owns action effects and timing. INTERFACE_CONTRACT defines what you send; this doc explains what happens.
- **MEMORY_AND_HIDDEN_INFORMATION** owns partial observability. Other docs may note "hidden" but this doc defines what, why, and how to track it.
- **IMPLEMENTATION_NOTES** is explicitly non-contractual. Agent developers should not depend on its contents for correctness.

## Coverage Matrix

| Concern | Primary Document | Supporting |
|---------|-----------------|------------|
| What game is this? | GAME_OVERVIEW | README |
| What are my inputs? | INTERFACE_CONTRACT | OBSERVATION_DECODING |
| What are my outputs? | INTERFACE_CONTRACT | ACTION_SEMANTICS_AND_CONTROL |
| How do I connect? | CONNECTION_AND_EPISODE_LIFECYCLE | INTERFACE_CONTRACT |
| How do I parse observations? | OBSERVATION_DECODING | INTERFACE_CONTRACT |
| Is this symbolic, visual, or mixed? | INTERFACE_CONTRACT | OBSERVATION_DECODING |
| What visual artifacts are needed? | OBSERVATION_DECODING | TRAINING_AND_EVALUATION |
| What state am I in? | OBSERVATION_DECODING | STATE_AND_VIEW_MODEL |
| What should I do? | STRATEGY_AND_POLICY_GUIDE | RULES_AND_MECHANICS |
| Am I doing well? | REWARDS_AND_PROGRESS_SIGNALS | RULES_AND_MECHANICS |
| What must I remember? | MEMORY_AND_HIDDEN_INFORMATION | STATE_AND_VIEW_MODEL |
| How do I recover from errors? | ERROR_RECOVERY_AND_ROBUSTNESS | CONNECTION_AND_EPISODE_LIFECYCLE |
| How do I train/iterate? | TRAINING_AND_EVALUATION | REWARDS_AND_PROGRESS_SIGNALS |
| What does each action do? | ACTION_SEMANTICS_AND_CONTROL | RULES_AND_MECHANICS |
| Where is this implemented? | IMPLEMENTATION_NOTES | All |

## Pipeline Implementation

The generation script (`generate_guides.py`) currently:

1. Accepts a local game source directory as input.
2. Selects documents with `--only` or `--through-stage`.
3. Runs documents in dependency-ordered stages. Multiple documents within the
   same stage can run concurrently via `--max-parallel`.
4. For each document, asks the selected coding-agent runners to independently
   inspect the game source and write draft markdown files under `.drafts/`.
5. Gives each runner and synthesizer access to the configured generic Cyborg
   policy framework so implementation guidance can target the framework that
   Maker will use.
6. Runs a Claude synthesis pass when two runners are selected. If exactly one
   runner is selected, that runner's draft is promoted directly to the final
   document and synthesis is skipped.
7. Retries each document once on failure. If a dependency fails or is missing,
   downstream documents are skipped instead of generated from a weak foundation.
8. Writes `guide_contract.json` from the generated guide bundle. The contract
   summarizes the observation surface, primary observation channel/encoding,
   action candidates, action wire format, runtime endpoints, evidence, document
   hashes, framework handoff, and missing document lists in a stable JSON shape
   for downstream tools.
9. Supports `--skip-existing` for incremental runs.

Each document is generated as a standalone reference that can be consumed
independently, while cross-links enable navigation for deeper investigation.

Runner selection defaults to Claude + Codex. Use `--runner` to choose one or
both coding-agent CLIs; `claude`/`clod` select Claude and `codex`/`codec` select
Codex. Model names can be overridden with `--claude-model` and `--codex-model`.

## Visual Artifact Handoff

Some games have symbolic player observations, some are visual-only, and some
provide mixed or alternate observation surfaces. `guide_v1` should classify the
actual player contract before any capture tooling is generated.

If the guide bundle shows that visual artifacts are needed, downstream work
should be scoped to specific needs, such as:

- frame fixtures for known phases or UI states;
- parser tests for pixel/sprite decoding;
- replay or global-view captures for debugging;
- manually seeded or source-instrumented capture harnesses.

Do not start a new game by asking an automated explorer to discover every view.
For visual-only games, that can require the perception and navigation system
that the pipeline is supposed to help build.

`maker_v1` should handle this handoff by using VLMs as constrained visual
bootstrap or fallback oracles, saving labeled frames as fixtures, and replacing
VLM calls with deterministic perception over time.

## Usage

```bash
# From this directory:
# cd testbed/guide_v1

# Generate all guide documents
python generate_guides.py <path_to_game_source> --output-dir ./output/my_game

# Explicitly override the Cyborg framework for a compatibility experiment
python generate_guides.py <path_to_game_source> \
  --agent-framework-dir /path/to/compatible/coborg

# Generate specific documents
python generate_guides.py <path_to_game_source> --only interface-contract
python generate_guides.py <path_to_game_source> --only game-overview rules-and-mechanics

# Generate through a dependency stage
python generate_guides.py <path_to_game_source> --through-stage 3

# Show the plan without running LLMs
python generate_guides.py <path_to_game_source> --output-dir ./output/my_game --dry-run

# Reuse existing completed documents and limit stage concurrency
python generate_guides.py <path_to_game_source> --skip-existing --max-parallel 2

# Override runner models
python generate_guides.py <path_to_game_source> --claude-model sonnet --codex-model gpt-5.5

# Run only Claude drafts and skip synthesis
python generate_guides.py <path_to_game_source> --runner clod

# Run both runners explicitly; synthesis is enabled
python generate_guides.py <path_to_game_source> --runner claude --runner codex
```

If `--agent-framework-dir` is omitted, Guide uses
`src/agent_policies/frameworks/coborg` from this repository. It does not
search external framework checkouts.

The output directory contains the final Markdown suite, `guide_contract.json`,
and `.drafts/` subdirectories with whichever runner drafts were selected. When
only one runner is selected, the final Markdown file is a direct copy of that
runner draft. Use `output/<game_slug>/` for generated guide bundles so they stay
separate from the toolkit code.

## Status

Live prototype. The script and `guide_v1/` package are implemented and have
produced guide suites for multiple games. Interfaces, prompt templates, output
quality, and failure handling are still expected to change.

## Toolkit vs Artifacts

Files in this directory are the reusable `guide_v1` toolkit:

- `generate_guides.py`
- `guide_v1/`
- `prompts/`
- this README

Files under `output/` are generated artifacts. They are game-specific guide
bundles, `guide_contract.json` files, and draft records produced by the
meta-pipeline. Future agents should not treat `output/<game>/` as part of the
reusable `guide_v1` implementation.
