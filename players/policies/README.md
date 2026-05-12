# Policies

The curated shared policy library is split by behavior:

- `symbolic/`: deterministic scripted policies.
- `cyborg/`: symbolic runtime plus slower LLM, memory, coaching, or
  self-improvement loops.
- `neural/`: trainable policy experiments and checkpoint-oriented policy
  projects.

Contributor-owned active projects should stay under `users/<handle>/<project>`
as submodules until code is intentionally promoted into this curated tree.
