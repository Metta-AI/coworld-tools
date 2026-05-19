# cogbase

Tools and skills for faster development of base agents for
[Coworld](https://github.com/Metta-AI/metta/tree/main/packages/coworld) games.

## What is this?

Cogbase is a brick-by-brick effort to build up tools that make developing base
agents for Coworld games faster, and ultimately automatic. Rather than pursuing
an end-to-end auto-coding approach, the project focuses on human-in-the-loop
pipelines that turn a game source tree (or a downloaded Coworld package) into
the artifacts an agent developer needs:

- **Game guides** -- source-grounded reference docs covering rules, protocol,
  observations, actions, lifecycle, training, robustness, and starter agents
- **Perception systems** -- interpreting game observations
- **Action systems** -- mapping decisions to valid game actions
- **Coworld-compatible player packaging** -- Dockerfile and runtime contract
  wiring so the generated agent can be run with `coworld run-episode` and
  submitted with `coworld upload-policy` / `coworld submit`
- **Other agent subsystems** as they emerge

The intended scope is general-purpose for games in the Coworld ecosystem, or
for games with similarly inspectable source and player/game protocols. Current
prototypes have been exercised on multiple games, including Among Them, Cogs
vs Clips, and Paint Arena, but the project is not meant to be specific to any
one game.

The goal: ship functional, usable Coworld players faster by reducing the human
time and effort currently required to develop competent base agents.

## Status

Early prototype. The importable `src/cogbase` package is still minimal, but
`testbed/` contains real working prototypes:

- `guide_v1/` generates a staged suite of 14 agent-developer guide documents
  plus a machine-readable `guide_contract.json` from a game source directory
  using selected Claude/Codex runner drafts, with synthesis when two runners are
  selected. Guide prompts are also given
  the in-repo `players_lib.coborg` framework location so
  implementation guidance is written for the same framework Maker will use.
- `maker_v2/` is the canonical next agent-making stage, currently a fresh
  scaffold. Its CLI exists but generation is not yet implemented. It is the
  intended successor to `maker_v1` and is designed to be contract-first,
  composable, and to lean on agent-driven generation instead of hand-coded
  Python derivers. See [maker_v2 Design](docs/designs/maker_v2_design.md).
- `maker_v1/` is the deprecated first-generation agent-making toolkit. It
  still runs for short-term continuity but is not receiving new features, and
  every entry point emits a deprecation warning. See
  [maker_v1 Deprecation Note](docs/designs/maker_v1_deprecation.md) for the
  rationale and [maker_v1 Design](docs/designs/maker_v1_design.md) for the
  historical implementation notes.
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

- [Coworld](https://github.com/Metta-AI/metta/tree/main/packages/coworld) -- the
  v2 tournament platform: CLI, manifest format, and player/game runtime
  contract these agents target
- [Metta](https://github.com/Metta-AI/metta) -- the underlying Metta framework
  (BitWorld engine, mettagrid, Coworld)

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
  It points guide prompts at `players_lib.coborg` by default;
  `--agent-framework-dir` is available only for explicit experiments with a
  compatible framework checkout.
- **`maker_v2/`** -- Canonical next-stage agent maker (fresh scaffold). CLI is
  in place but no generation is implemented yet. Intended to replace the
  deprecated `maker_v1` with a contract-first, composable pipeline that uses
  agent-driven generation instead of large amounts of hand-coded Python
  extraction. See [maker_v2 Design](docs/designs/maker_v2_design.md).
- **`maker_v1/`** -- Deprecated first-generation agent maker. Preserved for
  short-term continuity. The implemented command consumes `guide_v1` outputs,
  preferring `guide_contract.json` over Markdown heuristics, generates
  build-plan artifacts, emits source-grounded observation decoders, creates
  starter Python agent scaffolds for symbolic-primary games, creates live
  visual starter agents for visual/mixed games with proven action
  serialization, uses the configured Cyborg policy framework for generated
  live runtime adapters, can run offline VLM labeling with mock or AWS
  Bedrock providers, and can seed a starter policy from validated labels. It
  can also run local smoke tests for generated agents when given a server
  command or WebSocket URL. Every entry point now emits a deprecation
  warning. See
  [maker_v1 Deprecation Note](docs/designs/maker_v1_deprecation.md) and
  [maker_v1 Design](docs/designs/maker_v1_design.md).
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
