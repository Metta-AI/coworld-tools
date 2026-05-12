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

- `symbolic/cogsguard/cogames-agents/`: Python and Nim CogsGuard/CvC scripted
  policies split out of the former `cogames-agents` package.
- `symbolic/bitworld/`: copied BitWorld player-policy projects by game.
- `cyborg/coborg/`: Coborg runtime/framework pieces, including the former
  `cogames_agents.cyborg` runtime and the standalone cyborg policy framework.
- `cyborg/cogamer/`: Cogamer/Coglet program-table and generated-policy source
  snapshots.
- `cyborg/bitworld/among-them/`: BitWorld Among Them policies that include LLM
  or slow-loop behavior.
- `neural/cogames-attempts/`: trainable policy and teacher-research snapshots
  from the `cogames-attempts` research repo.
