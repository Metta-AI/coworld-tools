# cogbase

Tools and skills for faster development of base agents for [cogames](https://github.com/Metta-AI/cogames).

## What is this?

Cogbase is a brick-by-brick effort to build up tools that make developing base
agents for cogames faster, and ultimately automatic. Rather than pursuing an
end-to-end auto-coding approach, the project focuses on human-in-the-loop
pipelines that turn a game source tree into the artifacts an agent developer
needs:

- **Game guides** -- source-grounded reference docs covering rules, protocol,
  observations, actions, lifecycle, training, robustness, and starter agents
- **Perception systems** -- interpreting game observations
- **Action systems** -- mapping decisions to valid game actions
- **Other agent subsystems** as they emerge

The intended scope is general-purpose for games in the cogames ecosystem, or
for games with similarly inspectable source and agent/game protocols. Current
prototypes have been exercised on multiple games, including Among Them, Cogs vs
Clips, and Paint Arena, but the project is not meant to be specific to any one
game.

The goal: ship functional, usable cogame environments faster by reducing the
human time and effort currently required to develop competent base agents.

## Status

Early prototype. The importable `src/cogbase` package is still minimal, but
`testbed/` contains real working prototypes:

- `guide_v1/` generates a staged suite of 14 agent-developer guide documents
  plus a machine-readable `guide_contract.json` from a game source directory
  using selected Claude/Codex runner drafts, with synthesis when two runners are
  selected. Guide prompts are also given
  the generic Cyborg policy framework location so implementation guidance is
  written for the same framework Maker will use.
- `maker_v1/` implements the first four slices of the next agent-making stage.
  It consumes the guide contract first, falls back to Markdown extraction when
  needed, classifies the observation surface, extracts candidate actions,
  writes a build plan, manifest, VLM play card, and VLM request/response
  schemas, generates a source-grounded decoder spec and decoder implementation,
  generates starter Python agents for symbolic-primary games, and emits live
  visual starter agents when the guide proves a usable action wire contract.
  Generated live agents now include a `cyborg_agent.py` adapter that uses
  `cogames_agents.cyborg` from the configured Cyborg framework checkout.
  Its Phase 4 bootstrap can decode raw observations, label image frames with a
  strict mock or AWS Bedrock Claude VLM budget, cache those labels, validate
  actions, emit a label-derived starter policy, and run local smoke tests
  against a supplied game server command or already-running server.
- `eyes_v1/` is deprecated as a primary pipeline stage. Its visual-analysis and
  capture-generation code is preserved as optional experimental tooling, but
  `guide_v1` owns canonical game understanding and documentation.

Treat these tools as unstable experiments until promoted into the main package.

## Meta-Pipeline Model

Cogbase tools are artifact factories. The reusable code in this repository is
the meta-pipeline; the game-specific documents, helper tools, captured data,
tests, policy scaffolds, and final agents it produces are generated artifacts.

Generated artifacts form their own downstream pipeline: understanding artifacts
feed generated helper tools, helper tools produce fixtures and traces, and
those outputs feed the eventual base-agent implementation. Keep that boundary
clear when editing the repo: change toolkit code when improving the generator,
and treat files under `output/` directories as generated game-specific state.

See [Meta-Pipeline And Artifacts](docs/artifact_pipeline.md) for the canonical
terminology.

## Related projects

- [CoGames](https://github.com/Metta-AI/cogames) -- the game environments these agents target
- [Metta](https://github.com/Metta-AI/metta) -- the underlying Metta framework

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
# Clone and install
git clone <repo-url> && cd cogbase
uv sync
```

## Development

```sh
# Run tests
uv run pytest

# Add a dependency
uv add <package>
```

## Testbed

The `testbed/` directory contains prototype tools under active development. Each subdirectory is a self-contained tool or experiment being tested before promotion to the main library.

**All code in `testbed/` should be considered live and unstable.** Interfaces will change without notice, behavior may be incorrect, and nothing here is guaranteed to work. Agents and automation operating on this repo must treat testbed code accordingly -- do not depend on it, and expect breakage.

Current testbed entries:

- **`guide_v1/`** -- General agent-guide generator. Runs staged,
  dependency-ordered documentation tasks through selected coding-agent CLIs,
  synthesizing source-grounded guides when multiple runners are selected and
  promoting the lone draft directly when only one runner is selected. It also emits
  `guide_contract.json`, the machine-readable handoff consumed by downstream
  stages. This is the canonical front door for classifying symbolic vs visual
  observation surfaces and deciding what downstream artifacts a game needs.
  It points guide prompts at the generic Cyborg policy framework by default,
  with `--agent-framework-dir` or `COGBASE_AGENT_FRAMEWORK_DIR` for overrides.
- **`maker_v1/`** -- Early next-stage agent maker. The implemented command
  consumes `guide_v1` outputs, preferring `guide_contract.json` over
  Markdown heuristics, generates build-plan artifacts, emits source-grounded
  observation decoders, creates starter Python agent scaffolds for
  symbolic-primary games, creates live visual starter agents for visual/mixed
  games with proven action serialization, uses the configured Cyborg policy
  framework for generated live runtime adapters, can run offline VLM labeling with
  mock or AWS Bedrock providers, and can seed a starter policy from validated
  labels. It can also run local smoke tests for generated agents when given a
  server command or WebSocket URL. See
  [maker_v1 Design](docs/designs/maker_v1_design.md) for the full intended
  path toward automatic run-config discovery, deterministic parser generation,
  stronger policies, and submission packaging.
- **`eyes_v1/`** -- Deprecated visual exploration prototype. Keep it available
  for targeted/manual visual evidence work, frame fixtures, and capture-tool
  experiments after `guide_v1` identifies that a visual artifact is needed. Do
  not treat it as a competing documentation generator. See
  [eyes_v1 Deprecation Note](docs/designs/eyes_v1_deprecation.md).

## Project structure

```
cogbase/
  docs/              # Design notes and CLI runner references
  src/cogbase/       # Library source
  testbed/           # Prototype meta-pipeline tools (live, unstable)
    */output/        # Generated artifacts, not toolkit code
  tests/             # Tests (pytest)
  pyproject.toml     # Project metadata and dependencies
```
