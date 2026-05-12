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

Language is metadata rather than a top-level folder. Python, Nim, Go, CUDA, and
container-image policies should live next to the policy they implement.

## Catalog

| Project | Family | Path | Source | Targets | Notes |
| --- | --- | --- | --- | --- | --- |
| CogsGuard scripted agents | symbolic | `policies/symbolic/cogsguard/cogames-agents/scripted_agent` | metta `cogames-agents` | CogsGuard/CvC | Python scripted policies split out of the old `cogames_agents` package. |
| CogsGuard Nim agents | symbolic | `policies/symbolic/cogsguard/cogames-agents/nim_agents` | metta `cogames-agents` | CogsGuard/CvC | Nim lives with the policy family, not in a standalone language bucket. |
| CogsGuard evolution helpers | symbolic | `policies/symbolic/cogsguard/cogames-agents/evolution` | metta `cogames-agents` | CogsGuard/CvC | Role/policy evolution code kept with the CogsGuard symbolic family for now. |
| Coborg runtime | cyborg | `policies/cyborg/coborg/cogames_agents_runtime` | metta `cogames-agents` | CoGames/BitWorld agents | Former `cogames_agents.cyborg` fast-loop/slow-loop runtime. |
| Coborg framework docs/examples | cyborg | `policies/cyborg/coborg/framework` | metta `cogames-agents` | CoGames/Coworld agents | Former `coborg_framework` source and docs. |
| Cyborg policy framework | cyborg | `policies/cyborg/coborg/cyborg-policy-framework` | `Metta-AI/policies` | Game-pluggable agents | Self-improving policy framework copied from the standalone policies repo. |
| CVC debugger robot | cyborg | `policies/cyborg/coborg/cvc-debugger-robot` | `Metta-AI/cvc-debugger` | CogsGuard/CvC | Robot policy and tests extracted without the debugger web UI. |
| Cogamer core | cyborg | `policies/cyborg/cogamer/core` | `Metta-AI/cogamer` | CogsGuard/CvC | Program-table/LLM policy core and skills, excluding API/control-plane code. |
| Cogamer CVC generated policy | cyborg | `policies/cyborg/cogamer/generated/cvc-policy` | `Metta-AI/cogamer-policy-cvc` | CogsGuard/CvC | Generated product artifact preserved as a runnable source snapshot. |
| Cogamer Cogony generated policy | cyborg | `policies/cyborg/cogamer/generated/cogony-policy` | `Metta-AI/cogamer-policy-cogony` | Cogony | Generated product artifact preserved as a runnable source snapshot. |
| Cogora CVC player cog | cyborg | `policies/cyborg/cogamer/cogora` | `Metta-AI/cogora` | CogsGuard/CvC | COG/player-cog prior art and SDK surface. |
| BitWorld Among Them cyborg policies | cyborg | `policies/cyborg/bitworld/among-them` | metta `cogames-agents`, `Metta-AI/bitworld` | Among Them | Includes LLM/slow-loop Among Them policy code such as `mod-talks`. |
| BitWorld player policies | symbolic | `policies/symbolic/bitworld` | `Metta-AI/bitworld` | BitWorld games | Serious player-policy projects copied without the surrounding game code. |
| Cogames attempts policies | neural | `policies/neural/cogames-attempts` | `Metta-AI/cogames-attempts` | CogsGuard/CvC | Trainable policy, heterogeneous policy, and scripted-teacher research. |
| `relh/co-gas` | symbolic/cyborg | `users/relh/co-gas` | `Metta-AI/co-gas` | CvC, Coworld, BitWorld | Contributor-owned policy repo mounted as a submodule. |

## Tooling

| Tool Area | Path | Source | Notes |
| --- | --- | --- | --- |
| CogsGuard evals | `tools/eval/cogsguard` | metta `cogames-agents` | Eval maps, metric extraction, and baseline reports. |
| CogsGuard benchmarks | `tools/benchmark/cogsguard` | metta `cogames-agents` | Legacy benchmark shell entrypoint. |
| CogsGuard comparison | `tools/compare/cogsguard` | metta `cogames-agents` | Regression, parity, and comparison scripts. |
| CogsGuard upload | `tools/upload/cogsguard` | metta `cogames-agents` | Legacy submission notes. |
| CogsGuard research | `tools/research/cogsguard` | metta `cogames-agents` | Rollout, audit, and tuning scripts. |
| Coborg research tools | `tools/research/coborg` | `Metta-AI/policies`, `Metta-AI/cvc-debugger` | Cursor skills and policy optimizer tools. |
| CoGames attempts research | `tools/research/cogames-attempts` | `Metta-AI/cogames-attempts` | Sweep, train, eval, and utility scripts. |
| AI researcher workflows | `tools/research/cogames-rl-researcher` | metta `cogames-rl-researcher` | Monorepo-local workflow package copied out of metta. |

Future catalog work should move this table to a machine-readable manifest that
records owner, status, policy reference, target game, eval command, upload
command, benchmark command, and compare command for every serious policy.
