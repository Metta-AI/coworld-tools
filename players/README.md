# agent-policies

Importable policy and agent-framework workspace for Metta-AI projects.

There are two installable Python packages:

- `agent_policies` (under `src/agent_policies/`): the Coborg agent framework
  plus importable tooling helpers (eval metrics, eval definitions).
- `players` (top-level): concrete importable policies, organized by target
  game (`among_them/`, `cogsguard/`, `paintarena/`, `infinite_blocks/`).

Other top-level directories:

- `tools/cogbase/`: standalone base-agent meta-pipeline toolkit (its own
  pyproject; not part of the `agent-policies` distribution).
- `users/`: contributor-owned active projects, in-tree or as submodules.
- `validation/agent-policies-tests/`: pytest suite that exercises the saved
  framework and policies.
- `docs/`: workspace-level documentation. Tool-specific docs live with the
  tool (e.g. `tools/cogbase/docs/`).

## Working Rules

- Put reusable agent frameworks under `src/agent_policies/frameworks/`.
- Put importable eval/tooling helpers under `src/agent_policies/tools/`.
- Put concrete importable policies under the top-level `players/` tree.
- Put shared execution or analysis workflows under `tools/`.
- Keep Cogbase under `tools/cogbase/`; it is a standalone prototype toolkit
  for generating game guides and base-agent artifacts.
- Keep active personal projects under `users/<handle>/<project>` until code
  is intentionally promoted into the shared policy tree.
- Keep language next to the policy it implements (Nim, Python, etc.).
- Keep game/runtime package code in its owning repo unless the file is
  genuinely policy source.
