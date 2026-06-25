# Meta-Pipeline And Artifacts

Cogbase builds base agents by generating a chain of game-specific artifacts.
The reusable code in this repository is the meta-pipeline. The documents,
helper tools, captured data, tests, and policy code produced for a target game
are artifacts.

## Terms

- **Meta-pipeline toolkit**: reusable generator code. `guide_v1` is the active
  canonical toolkit for game understanding; `maker_v2` is the canonical (but
  early-scaffold) toolkit for turning guide bundles into runnable baseline
  agents; `maker_v1` is the deprecated first-generation maker, preserved for
  short-term continuity; `eyes_v1` is a deprecated visual exploration
  prototype kept for targeted artifact experiments.
- **Generated artifact**: a game-specific output produced by a toolkit, such as
  a guide document, UI report, view explorer, captured frame set, fixture, test
  harness, policy scaffold, or final agent.
- **Artifact pipeline**: the downstream chain where one generated artifact
  becomes input to later generation steps.
- **Final agent**: the submitted base agent that plays the target Coworld
  game. Generated as a Coworld-compatible player image — a Docker container
  whose entrypoint reads `COGAMES_ENGINE_WS_URL` from the runner's env and
  speaks the game's player websocket protocol.

## Flow

```text
game source (or downloaded Coworld package)
  -> guide_v1
     -> understanding artifacts
        guide docs, guide_contract.json, interface contracts,
        observation/action classifications
  -> maker_v2  (canonical, early scaffold; replaces deprecated maker_v1)
     -> generated helper tools
        perception parsers, view explorers, capture tools, test harnesses
     -> helper-tool outputs
        captured frames, metadata, fixtures, traces
     -> agent implementation artifacts
        perception code, action code, policy scaffold, tests
     -> coworld packaging
        Dockerfile, .dockerignore, agent/run_agent.py entrypoint
     -> final base agent
        submit-ready Coworld player image
        (coworld upload-policy + coworld submit)
```

The generated artifacts form their own pipeline. They are not just reports to
read; they are structured inputs that make later auto-coding steps cheaper and
more reliable.

## Canonical Entry Point

`guide_v1` is the canonical entry point for a new game. It should first answer:

- What observation interfaces does the agent actually receive?
- Are those observations symbolic, visual, or mixed?
- Are visual artifacts needed, and if so, which frames, fixtures, or parser
  experiments should be generated downstream?

Deprecated `eyes_v1` output may still be useful as downstream visual evidence,
but it is not canonical project truth. Its reports, generated explorers, and
captured frames are artifacts to be produced only when a guide or a human
operator has identified a concrete visual-perception need.

## Agent-Making Stage

The canonical agent-making stage is `maker_v2`, a fresh scaffold under
`testbed/maker_v2/`. It is intended to replace the deprecated `maker_v1`
prototype with a contract-first, more composable pipeline that leans on
agent-driven generation instead of large amounts of hand-coded Python
extraction logic. See [maker_v2 Design](designs/maker_v2_design.md).

`maker_v2` is early; its CLI exists but generation is not yet implemented.
While `maker_v2` is filling in, the deprecated `maker_v1` toolkit remains
available for short-term continuity. Its historical capabilities, status, and
generated artifact set are documented in
[maker_v1 Design](designs/maker_v1_design.md), and its retirement is recorded
in [maker_v1 Deprecation Note](designs/maker_v1_deprecation.md). New games
and new pipeline work should target `maker_v2`; falling back to `maker_v1`
should be treated as a temporary measure, and any gap that forces such a
fallback should be filed as a `maker_v2` requirement rather than a new
`maker_v1` feature.

## Repository Rule

Keep toolkit code and generated artifacts separated:

- Toolkit roots contain reusable scripts, packages, prompt templates, and docs.
- `output/` directories contain generated game-specific artifacts.
- A generated helper tool under `output/<game>/` is an artifact, even if it has
  source code, tests, and documentation of its own.

This distinction is load-bearing for coding agents. If generated artifacts live
beside the toolkit, agents tend to confuse historical output with the generator
they should edit.
