# Migration From Metta `cogames-agents`

The initial `cogames-agents` source was copied from the Metta monorepo. It is
now assimilated into the `agent_policies` package rather than kept as a
standalone `cogames-agents` package.

Current targets:

- CogsGuard/CvC scripted policies:
  `src/agent_policies/policies/scripted/cogsguard/`
- Coborg runtime and framework pieces:
  `src/agent_policies/frameworks/coborg/`
- BitWorld Among Them cyborg policy code:
  `src/agent_policies/policies/cyborg/bitworld/among_them/`
- Evals, benchmarks, comparisons, upload notes, and research helpers:
  `tools/`
- Importable eval helpers and maps:
  `src/agent_policies/tools/eval/cogsguard/`

Canonical imports use `agent_policies.*`. The historical `cogames_agents`,
`cogamer`, `framework`, and `robot` import roots are not packaged in this repo;
old imports and short policy specs should be migrated to canonical paths.
