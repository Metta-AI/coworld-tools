# Meta-Pipeline And Artifacts

Cogbase builds base agents by generating a chain of game-specific artifacts.
The reusable code in this repository is the meta-pipeline. The documents,
helper tools, captured data, tests, and policy code produced for a target game
are artifacts.

## Terms

- **Meta-pipeline toolkit**: reusable generator code. `guide_v1` is the active
  canonical toolkit for game understanding; `maker_v1` is the early toolkit
  for turning guide bundles into runnable baseline agents; `eyes_v1` is a
  deprecated visual exploration prototype kept for targeted artifact
  experiments.
- **Generated artifact**: a game-specific output produced by a toolkit, such as
  a guide document, UI report, view explorer, captured frame set, fixture, test
  harness, policy scaffold, or final agent.
- **Artifact pipeline**: the downstream chain where one generated artifact
  becomes input to later generation steps.
- **Final agent**: the submitted base agent or policy package that plays the
  target cogame.

## Flow

```text
game source
  -> guide_v1
     -> understanding artifacts
        guide docs, guide_contract.json, interface contracts,
        observation/action classifications
  -> maker_v1
     -> generated helper tools
        perception parsers, view explorers, capture tools, test harnesses
     -> helper-tool outputs
        captured frames, metadata, fixtures, traces
     -> agent implementation artifacts
        perception code, action code, policy scaffold, tests
     -> final base agent
        submit-ready cogames policy/player
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

`maker_v1` is the next stage after `guide_v1`. The implemented command consumes
a guide bundle. It prefers the machine-readable `guide_contract.json` for
observation surface, primary observation encoding, candidate actions, action
wire format, and runtime notes; Markdown parsing remains a compatibility
fallback for older guide bundles. Maker produces `maker_manifest.json`,
`AGENT_BUILD_PLAN.md`, `visual_bootstrap/play_card.md`,
`visual_bootstrap/vlm_request_schema.json`, `visual_bootstrap/vlm_schema.json`,
a source-grounded `agent/perception/decoder_spec.json`,
`DECODER_GENERATION_TASK.md`, and `agent/perception/decoder.py`. For
symbolic-primary games, it also generates a starter Python agent scaffold under
`agent/`. For visual or mixed/alternate games, it generates a conservative live
visual starter when the guide proves a serializable action wire contract, plus
frame storage and mock VLM labeling tools. Generated live starters include
`agent/framework_bootstrap.py` and `agent/cyborg_agent.py`, which point the
artifact at the configured `cogames_agents.cyborg` framework and wrap the
starter policy in Cyborg percept, belief, mode, strategy, and action-resolution
boundaries. The generated visual starter can connect to a WebSocket, save
frames, decode observations when possible, choose simple movement actions, and
send only protocol-serialized actions. Maker can
also run an offline Phase 4 bootstrap over captured raw observations or image
frames, optionally decode raw observations into PNG fixtures, label them with
either mock labeling or AWS Bedrock Claude labeling, write structured labels
and run reports under `visual_bootstrap/`, and generate a label-derived
`agent/policy_from_labels.py`. Maker can also run a local smoke test against a
supplied server command or already-running server, writing reports and logs
under `smoke_tests/`. The full design still calls for automatic run-config
discovery, deterministic parser generation, and final submit-ready agent
packages.

See [maker_v1 Design](designs/maker_v1_design.md).

## Repository Rule

Keep toolkit code and generated artifacts separated:

- Toolkit roots contain reusable scripts, packages, prompt templates, and docs.
- `output/` directories contain generated game-specific artifacts.
- A generated helper tool under `output/<game>/` is an artifact, even if it has
  source code, tests, and documentation of its own.

This distinction is load-bearing for coding agents. If generated artifacts live
beside the toolkit, agents tend to confuse historical output with the generator
they should edit.
