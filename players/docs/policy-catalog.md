# Policy Catalog

This repo is the policy experimentation workspace for Metta-AI projects.

Policy projects are organized by behavior:

- `policies/symbolic/`: deterministic scripted policies.
- `policies/cyborg/`: fast symbolic/action loops with slower LLM, memory,
  coaching, or self-improvement loops.
- `policies/neural/`: trainable policy experiments, checkpoint wrappers,
  policy-specific recipes, and teacher experiments.
- `users/<handle>/<project>/`: contributor-owned policy repos mounted as Git
  submodules when they remain actively edited by their owner.

Language is metadata rather than a top-level folder. Python, Nim, CUDA, and
container-image policies should live next to the policy they implement.

## Initial Entries

| Policy Project | Family | Source | Targets | Notes |
| --- | --- | --- | --- | --- |
| `cogames_agents.policy.scripted_agent` | symbolic | `src/cogames_agents/policy/scripted_agent` | CogsGuard/CvC | Existing Python scripted policies from the former Metta monorepo package. |
| `cogames_agents.policy.nim_agents` | symbolic | `src/cogames_agents/policy/nim_agents` | CogsGuard/CvC | Nim-backed policies remain colocated with the package they implement. |
| `cogames_agents.cyborg` | cyborg | `src/cogames_agents/cyborg` | CoGames/BitWorld agents | Reusable fast-loop/slow-loop agent runtime. |
| `relh/co-gas` | symbolic/cyborg | `users/relh/co-gas` | CvC, Coworld, BitWorld | Contributor-owned policy repo mounted as a submodule. |

Future catalog work should move this table to a machine-readable manifest that
records owner, status, policy reference, target game, eval command, upload
command, benchmark command, and compare command for every serious policy.
