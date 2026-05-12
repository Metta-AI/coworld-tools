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
  of `cogames-agents`.
- `benchmark/cogsguard/`: legacy CogsGuard benchmark entrypoints.
- `compare/cogsguard/`: parity, regression, and policy comparison scripts.
- `upload/cogsguard/`: legacy CoGames submission notes for CogsGuard policies.
- `research/cogsguard/`: CogsGuard rollout/audit/tuning helpers.
- `research/coborg/`: cyborg policy framework skills and CVC debugger optimizer
  tools.
- `research/cogames-attempts/`: training, sweep, eval, and utility scripts from
  the research-attempts repo.
- `research/cogames-rl-researcher/`: metta-local AI researcher workflow package.
- `packaging/cogames-agents-legacy/`: old `cogames-agents` build scaffolding,
  retained only until a new package boundary exists.
