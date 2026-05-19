# agent-policies

Importable policy and agent-framework workspace for Metta-AI projects.

There are two installable Python packages:

- `agent_policies` (under `src/agent_policies/`): the Coborg agent framework
  plus importable tooling helpers (eval metrics, eval definitions).
- `policies` (top-level): concrete importable policies, organized by policy
  style (`scripted/`, `cyborg/`) and target game/system.

Other top-level directories:

- `tools/`: eval, upload, benchmark, and compare scripts for the in-tree
  policies, plus `tools/cogbase/` as a standalone base-agent toolkit.
- `users/`: contributor-owned active projects, in-tree or as submodules.

## Working Rules

- Put reusable agent frameworks under `src/agent_policies/frameworks/`.
- Put importable eval/tooling helpers under `src/agent_policies/tools/`.
- Put concrete importable policies under the top-level `policies/` tree.
- Put shared execution or analysis workflows under `tools/`.
- Keep Cogbase under `tools/cogbase/`; it is a standalone prototype toolkit
  for generating game guides and base-agent artifacts.
- Keep active personal projects under `users/<handle>/<project>` until code
  is intentionally promoted into the shared policy tree.
- Keep language next to the policy it implements (Nim, Python, etc.).
- Keep game/runtime package code in its owning repo unless the file is
  genuinely policy source.
