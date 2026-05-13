# eyes_v1

Deprecated prototype tools for visual analysis and frame-capture artifact
experiments.

## Deprecation Status

`eyes_v1` is deprecated as a primary Cogbase pipeline stage. Do not start new
game-understanding work here, and do not treat `eyes_v1` reports as canonical
documentation.

Use `testbed/guide_v1/` first. `guide_v1` owns the source-grounded guide bundle,
including the player interface contract, observation decoding, state/view model,
and the classification of a game's observation surface as symbolic, visual, or
mixed.

`eyes_v1` may still be useful after that classification, when a guide or human
operator identifies a concrete visual-perception need:

- targeted frame fixtures for known views or phases;
- parser experiments for visual-only observations;
- replay/global-view captures for debugging;
- manually seeded or source-instrumented capture tools.

`eyes_v1` itself is the meta-pipeline toolkit. Game-specific reports, generated
explorer tools, captured frames, and capture metadata are artifacts and belong
under `output/`.

See `../../docs/designs/eyes_v1_deprecation.md` for the rationale.

## Historical Purpose

When building a perception system for a base agent, you need:

1. **What can the agent see?** -- Every UI view and graphical element.
2. **How does the agent get there?** -- The complete state machine and navigation flow.
3. **How do we capture training data?** -- A view-exploring agent design for frame capture.

This toolset attempted to automate all three by running structured analysis
prompts through multiple coding agents and synthesizing their outputs. Later
stages could ask agents to design and implement a game-specific view explorer.

The approach is no longer recommended as a first-stage pipeline because the
capture/explorer stages can become circular in visual-only games: an explorer
may need the perception and navigation capabilities that the pipeline is trying
to help build.

## Pipeline

The main script (`generate_flow_report.py`) still runs the historical
multi-stage pipeline:

```
Stage 1: UI/Visual Analysis
  - 3 runners (opencode, codex, claude) generate independent UI reports
  - opencode synthesizes them into a validated, merged report

Stage 2: State Machine / Flow Analysis
  - 3 runners generate independent flow/state-machine reports
  - opencode synthesizes them into a validated, merged report

Stage 3: Agent Design
  - opencode uses both synthesized reports to produce a detailed design
    document for a view-exploring agent system

Stage 4: Implementation
  - codex writes an implementation plan
  - opencode reviews the plan
  - codex implements the game-specific explorer under the output directory

Stage 5: Capture
  - opencode generates a capture checklist and drives the explorer to capture
    frames and metadata
```

## Usage For Legacy/Targeted Runs

Prefer `guide_v1` for new games. Use these commands only for legacy
regeneration or a targeted visual-artifact experiment whose scope is already
known.

```sh
# Run the full pipeline
python generate_flow_report.py /path/to/game/source --output-dir ./output/my_game

# Run only the analysis stages
python generate_flow_report.py /path/to/game/source --stage ui flow

# Run later stages from existing reports
python generate_flow_report.py /path/to/game/source --stage design implement \
    --ui-report ./output/my_game/ui_report_synthesized_20260507.md \
    --flow-report ./output/my_game/flow_report_synthesized_20260507.md

# Use specific runners only
python generate_flow_report.py /path/to/game/source --runners claude codex

# Custom timeout (seconds per runner)
python generate_flow_report.py /path/to/game/source --timeout 2400
```

`source` may be a local directory or a URL-like source location. Local
directories are used as the runner working directory.

## Output Files

Each run produces timestamped files:

```
output/<game_or_run>/
  ui_report_<runner>_<timestamp>.md         # Individual UI analyses
  ui_report_synthesized_<timestamp>.md      # Merged + validated UI report
  flow_report_<runner>_<timestamp>.md       # Individual flow analyses
  flow_report_synthesized_<timestamp>.md    # Merged + validated flow report
  agent_design_<timestamp>.md               # View-exploring agent design doc
  implementation_plan_<timestamp>.md        # Generated implementation plan
  implementation_review_<timestamp>.md      # Review of the implementation plan
  implementation_log_<timestamp>.md         # Implementation transcript
  capture_checklist_<timestamp>.json        # Views and capture commands
  capture_results_<timestamp>.md            # Capture run summary
  explore_views/                            # Generated explorer artifact
  captured_frames/                          # Captured PNGs and metadata
```

This repository currently contains a historical Among Them artifact bundle at
`output/among_them/`. Its generated `explore_views/` README documents the
concrete targets, WebSocket protocol assumptions, and capture output layout for
that game.

## Legacy Script

`generate_report.py` is the original standalone UI report generator. Its
functionality is now incorporated into the historical pipeline's UI stage. It is
also deprecated for canonical documentation work.

## Requirements

One or more of these CLI tools must be installed and authenticated:

- `opencode` -- OpenCode CLI (`opencode run`)
- `codex` -- OpenAI Codex CLI (`codex exec`)
- `claude` -- Anthropic Claude Code CLI (`claude --print`)

The synthesis and design stages use `opencode`. The implementation stage uses
Codex for planning/implementation and OpenCode for review. The capture stage
uses OpenCode to operate the generated explorer.

## Status

Deprecated prototype. Keep for reference and targeted visual-artifact work only.
Do not extend it into a competing documentation pipeline.

## Toolkit vs Artifacts

Files in this directory are the reusable `eyes_v1` toolkit:

- `generate_flow_report.py`
- `generate_report.py`
- prompt templates embedded in those scripts
- this README

Files under `output/` are generated artifacts. They may include source code,
tests, documentation, and captured data, but they are still outputs of the
meta-pipeline. Future agents should not treat `output/<game>/explore_views/` as
part of the reusable `eyes_v1` implementation.
