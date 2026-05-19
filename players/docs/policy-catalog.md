# Policy Catalog

This repo is the policy experimentation workspace for Metta-AI projects.

Importable Python policy projects are organized under `src/agent_policies`:

- `frameworks/`: reusable policy frameworks such as Coborg, Cogamer, and the
  cyborg evolution framework.
- `policies/scripted/`: deterministic scripted policy implementations.
- `policies/cyborg/`: concrete policies using symbolic fast loops with slower
  LLM, memory, coaching, or self-improvement loops.
- `tools/`: importable tooling helpers, metrics, and eval definitions.

The top-level `policies/` tree remains for copied source snapshots that are not
yet normalized into the package, including non-Python player projects and
generated Cogamer policy artifacts.
- `users/<handle>/<project>/`: contributor-owned policy repos mounted as Git
  submodules when they remain actively edited by their owner.

Language is metadata rather than a top-level folder. Python, Nim, Go, CUDA, and
container-image policies should live next to the policy they implement.

## Catalog

| Project | Family | Path | Source | Targets | Notes |
| --- | --- | --- | --- | --- | --- |
| CogsGuard scripted agents | scripted | `policies/scripted/cogsguard/scripted_agent` | metta `cogames-agents` | CogsGuard/CvC | Python scripted policies from the old `cogames_agents` package. |
| CogsGuard Nim agents | scripted | `policies/scripted/cogsguard/nim_agents` | metta `cogames-agents` | CogsGuard/CvC | Nim lives with the scripted CogsGuard family. |
| CogsGuard evolution helpers | scripted | `policies/scripted/cogsguard/evolution` | metta `cogames-agents` | CogsGuard/CvC | Role/policy evolution code for CogsGuard scripted policies. |
| Coborg framework | framework | `src/agent_policies/frameworks/coborg` | metta `cogames-agents` | CoGames/BitWorld agents | Former `cogames_agents.cyborg` fast-loop/slow-loop runtime plus docs/examples. |
| Cyborg evolution framework | framework | `src/agent_policies/frameworks/cyborg_evolution` | `Metta-AI/policies` | Game-pluggable agents | Self-improving policy framework copied from the standalone policies repo. |
| CVC debugger robot | cyborg | `policies/cyborg/cogsguard/cvc_debugger_robot` | `Metta-AI/cvc-debugger` | CogsGuard/CvC | Robot policy and tests extracted without the debugger web UI. |
| Cogamer coglet/PCO framework | framework | `src/agent_policies/frameworks/cogamer/{coglet,pco}` | `Metta-AI/cogamer` | CogsGuard/CvC | Game-agnostic coglet runtime primitives and abstract PCO optimizer. |
| Cogamer CVC policy | cyborg | `policies/cyborg/cogamer/cvc` | `Metta-AI/cogamer` | CogsGuard/CvC | Canonical importable CvC policy: `CvCPolicy` entry point, program table, CvC PCO instantiations (critic/learner/losses/constraints), and `CvcEngine` decision tree. |
| Cogamer CVC generated policy | cyborg | `policies/cyborg/cogamer/generated/cvc-policy` | `Metta-AI/cogamer-policy-cvc` | CogsGuard/CvC | Generated product artifact preserved as a runnable source snapshot. |
| Cogamer Cogony generated policy | cyborg | `policies/cyborg/cogamer/generated/cogony-policy` | `Metta-AI/cogamer-policy-cogony` | Cogony | Generated product artifact preserved as a runnable source snapshot. |
| Cogora CVC player cog | cyborg | `policies/cyborg/cogamer/cogora` | `Metta-AI/cogora` | CogsGuard/CvC | COG/player-cog prior art and SDK surface. |
| BitWorld Among Them Python policies | cyborg | `policies/cyborg/bitworld/among_them` | metta `cogames-agents`, `Metta-AI/bitworld` | Among Them | Importable Python policy module. |
| BitWorld Among Them project snapshots | cyborg | `policies/cyborg/bitworld/among-them` | `Metta-AI/bitworld` | Among Them | Non-importable project source such as `mod-talks`. |
| BitWorld player policies | symbolic | `policies/symbolic/bitworld` | `Metta-AI/bitworld` | BitWorld games | Serious player-policy projects copied without the surrounding game code. |
| Cogames attempts policies | neural | `policies/neural/cogames-attempts` | `Metta-AI/cogames-attempts` | CogsGuard/CvC | Trainable policy, heterogeneous policy, and scripted-teacher research. |
| `relh/co-gas` | symbolic/cyborg | `users/relh/co-gas` | `Metta-AI/co-gas` | CvC, Coworld, BitWorld | Contributor-owned policy repo mounted as a submodule. |

## Tooling

| Tool Area | Path | Source | Notes |
| --- | --- | --- | --- |
| CogsGuard eval helpers | `src/agent_policies/tools/eval/cogsguard` | metta `cogames-agents` | Importable eval maps, metric extraction, and eval definitions. |
| CogsGuard eval scripts | `tools/eval/cogsguard` | metta `cogames-agents` | Shell/script entrypoints that call the importable helpers. |
| CogsGuard benchmarks | `tools/benchmark/cogsguard` | metta `cogames-agents` | Legacy benchmark shell entrypoint. |
| CogsGuard comparison | `tools/compare/cogsguard` | metta `cogames-agents` | Regression, parity, and comparison scripts. |
| CogsGuard upload | `tools/upload/cogsguard` | metta `cogames-agents` | Legacy submission notes. |
| CogsGuard research | `tools/research/cogsguard` | metta `cogames-agents` | Rollout, audit, and tuning scripts. |
| Cogbase | `tools/cogbase` | local `cogbase` project | Standalone prototype meta-pipeline for generating source-grounded game guides and base-agent artifacts. Uses `agent_policies.frameworks.coborg` for generated Cyborg runtime adapters. |
| Cursor skills | `tools/research/cursor-skills` | `Metta-AI/policies` | Cursor skills for the cyborg evolution framework. |
| CogsGuard CVC debugger optimizer | `tools/research/cogsguard/cvc-debugger-policy-optimizer` | `Metta-AI/cvc-debugger` | Standalone robot policy optimizer container and harness. |
| CoGames attempts research | `tools/research/cogames-attempts` | `Metta-AI/cogames-attempts` | Sweep, train, eval, and utility scripts. |
| AI researcher workflows | `tools/research/cogames-rl-researcher` | metta `cogames-rl-researcher` | Monorepo-local workflow package copied out of metta. |

Future catalog work should move this table to a machine-readable manifest that
records owner, status, policy reference, target game, eval command, upload
command, benchmark command, and compare command for every serious policy.
