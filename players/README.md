# agent-policies

Policy experimentation workspace for Metta-AI projects.

This repo is organized by policy behavior rather than by the historical repo or
package that first produced the code:

- `policies/symbolic/`: deterministic scripted policies and player projects.
- `policies/cyborg/`: fast symbolic loops combined with slower LLM, memory,
  coaching, or self-improvement loops.
- `policies/neural/`: trainable policy experiments, checkpoint wrappers,
  recipes, and teacher-policy research.
- `tools/`: eval, upload, benchmark, compare, packaging, and research tooling.
- `users/`: contributor-owned active repos mounted as submodules.
- `docs/`: policy catalog, provenance, migrations, tutorials, and experiment
  records.

## Current State

This is a source collation, not a finished package-normalization pass. The old
`cogames-agents` root package was split across `policies/` and `tools/`; its
legacy build files are preserved under `tools/packaging/cogames-agents-legacy/`
until a new package boundary is designed.

The repo now contains copied source snapshots from the high-signal policy
sources identified in the consolidation plan, plus `users/relh/co-gas` as a
submodule. See `docs/source-provenance.md` for source commits and copy targets.

## Working Rules

- Put runnable policy source under `policies/<family>/<game-or-system>/`.
- Put shared execution or analysis workflows under `tools/`.
- Keep active personal projects under `users/<handle>/<project>` as submodules
  until code is intentionally promoted into the shared policy tree.
- Keep language next to the policy it implements. Nim, Python, Go, CUDA, and
  container files should not get top-level language buckets.
- Keep game/runtime package code in its owning repo unless the file is
  genuinely policy source.
