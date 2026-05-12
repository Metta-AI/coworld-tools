# Policies

The curated shared policy library is split by behavior:

- `symbolic/`: deterministic scripted policies.
- `cyborg/`: symbolic runtime plus slower LLM, memory, coaching, or
  self-improvement loops.
- `neural/`: trainable policy experiments and checkpoint-oriented policy
  projects.

Contributor-owned active projects should stay under `users/<handle>/<project>`
as submodules until code is intentionally promoted into this curated tree.

## Current Families

- Importable CogsGuard scripted policies now live under
  `src/agent_policies/policies/scripted/cogsguard/`.
- `symbolic/bitworld/`: copied BitWorld player-policy projects by game.
- Importable Coborg, Cogamer, and cyborg-evolution frameworks now live under
  `src/agent_policies/frameworks/`.
- `cyborg/cogamer/`: generated-policy source snapshots.
- `cyborg/bitworld/among-them/`: BitWorld Among Them policies that include LLM
  or slow-loop behavior but are not yet normalized into importable modules.
- `neural/cogames-attempts/`: trainable policy and teacher-research snapshots
  from the `cogames-attempts` research repo.
