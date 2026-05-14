# Policy Tools

Shared policy tooling lives here.

- `eval/`: run one policy against one game target.
- `upload/`: package and upload a policy.
- `benchmark/`: run a policy across a target set and write normalized results.
- `compare/`: compare policies across the same target set.
- `research/`: reusable policy-improvement and analysis workflows.

Tools should use manifests that include both policy references and game targets.
A policy reference can be a local path, class URI, `metta://policy/...` URI,
container image, checkpoint URI, or package entrypoint. A game target should
include the game package, mission, suite, season, variant, agent count, seed set,
and max steps when applicable.

## Current Tool Sources

- `eval/cogsguard/`: eval maps, metrics, and scripted baseline reports split out
  of `cogames-agents`; importable helpers live under
  `src/agent_policies/tools/eval/cogsguard/`.
- `benchmark/cogsguard/`: legacy CogsGuard benchmark entrypoints.
- `benchmark/cogamer/`: Cogamer learnings-file metrics and variant comparison.
- `compare/cogsguard/`: parity, regression, and policy comparison scripts.
- `upload/cogsguard/`: legacy CoGames submission notes for CogsGuard policies.
- `cogbase/`: standalone prototype meta-pipeline for generating game guides and
  base-agent artifacts. It uses `agent_policies.frameworks.coborg` as the
  Cyborg runtime framework for generated adapters.
- `research/cogsguard/`: CogsGuard rollout/audit/tuning helpers and the CVC
  debugger robot optimizer.
- `research/cursor-skills/`: Cursor skills for the cyborg evolution framework.
- `research/cogames-attempts/`: training, sweep, eval, and utility scripts from
  the research-attempts repo.
- `research/cogames-rl-researcher/`: metta-local AI researcher workflow package.
