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
