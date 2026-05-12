# Migration From Metta `cogames-agents`

The initial `cogames-agents` source was copied from the Metta monorepo and then
split by behavior. This repo is no longer organized as one `cogames-agents`
package at the root.

Current targets:

- Symbolic CogsGuard/CvC policies:
  `policies/symbolic/cogsguard/cogames-agents/`
- Coborg runtime and framework pieces:
  `policies/cyborg/coborg/`
- BitWorld Among Them cyborg policy code:
  `policies/cyborg/bitworld/among-them/`
- Evals, benchmarks, comparisons, upload notes, and research helpers:
  `tools/`
- Legacy packaging scaffolding:
  `tools/packaging/cogames-agents-legacy/`

Import paths and package metadata still need a follow-up normalization pass.
The first collation pass prioritizes taxonomy, provenance, and source
ownership over preserving the old `src/cogames_agents` layout.
