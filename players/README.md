# agent-policies

Importable policy and agent-framework workspace for Metta-AI projects.

The canonical Python package is `agent_policies`. It assimilates the useful
parts of the old `cogames-agents` source together with Coborg, Cogamer, and
other policy/framework code:

- `src/agent_policies/frameworks/`: reusable agent frameworks such as Coborg,
  Cogamer, and the cyborg evolution framework.
- `src/agent_policies/policies/`: concrete importable policies, separated by
  policy style and target game/system.
- `src/agent_policies/tools/`: importable tooling helpers such as eval metrics
  and eval definitions.
- `policies/`: copied policy projects that are not yet normalized into the
  importable package, including generated snapshots and non-Python players.
- `tools/`: eval, upload, benchmark, compare, Cogbase, and research tooling.
- `users/`: contributor-owned active repos mounted as submodules.
- `docs/`: policy catalog, provenance, migrations, tutorials, and experiment
  records.

## Current State

The repo now has a root `pyproject.toml` for the `agent-policies` distribution.
Canonical imports use `agent_policies.*`. Historical import roots such as
`cogames_agents`, `cogamer`, `framework`, and `robot` are not packaged.

The repo now contains copied source snapshots from the high-signal policy
sources identified in the consolidation plan, `tools/cogbase` as the base-agent
meta-pipeline toolkit, plus `users/relh/co-gas` as a submodule. See
`docs/source-provenance.md` for source commits and copy targets.

## Working Rules

- Put importable shared Python source under `src/agent_policies/`.
- Put reusable agent frameworks under `src/agent_policies/frameworks/`.
- Put concrete importable policies under `src/agent_policies/policies/`.
- Put runnable non-importable policy snapshots under `policies/<family>/`.
- Put shared execution or analysis workflows under `tools/`.
- Keep Cogbase under `tools/cogbase/`; it is a standalone prototype toolkit for
  generating game guides and base-agent artifacts.
- Keep active personal projects under `users/<handle>/<project>` as submodules
  until code is intentionally promoted into the shared policy tree.
- Keep language next to the policy it implements. Nim, Python, Go, CUDA, and
  container files should not get top-level language buckets.
- Keep game/runtime package code in its owning repo unless the file is
  genuinely policy source.
