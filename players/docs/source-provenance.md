# Source Provenance

This records what was copied into `agent-policies` during the first taxonomy
collation pass. It is a copy-based migration; no Git subtree history was
preserved.

## Copied Sources

| Source | Source commit | Copied target | Notes |
| --- | --- | --- | --- |
| `Metta-AI/metta:cogames-agents` | `aa1d7c5b48c8548d29632562137e571d738d0650` | `src/agent_policies/policies/scripted/cogsguard` | Python, Nim, registry, and evolution policy code. |
| `Metta-AI/metta:cogames-agents` | `aa1d7c5b48c8548d29632562137e571d738d0650` | `src/agent_policies/frameworks/coborg` | Former `cogames_agents.cyborg` runtime plus Coborg docs/examples. |
| `Metta-AI/metta:cogames-agents` | `aa1d7c5b48c8548d29632562137e571d738d0650` | `tools/eval`, `tools/benchmark`, `tools/compare`, `tools/upload`, `tools/research/cogsguard` | Eval/upload/benchmark/compare/research scripts split out of the old package. |
| `Metta-AI/cogamer` | `b57f070541cc19872a5ed6b03e962277edbc18ad` | `src/agent_policies/frameworks/cogamer` | Copied policy core, PCO code, skills, memory, lifecycle, and relevant docs; API/control-plane code left out. |
| `Metta-AI/cogamer-policy-cvc` | `09ff4e4862e66de34728139c5a22ce3be3fccbf9` | `policies/cyborg/cogamer/generated/cvc-policy` | Generated/runnable policy artifact preserved as source. |
| `Metta-AI/cogamer-policy-cogony` | `41dacd0c2a3c270c1c150a8c839bf596c32c612d` | `policies/cyborg/cogamer/generated/cogony-policy` | Generated/runnable policy artifact preserved as source. |
| `Metta-AI/policies` | `f0c7a851dd60caa2ed586acd4d62ca58cd0c703d` | `src/agent_policies/frameworks/cyborg_evolution`, `tools/research/cursor-skills` | Copied framework source and Cursor skills. |
| `Metta-AI/cvc-debugger` | `8666c607f54ae204893dc43558e3efb51a1c3d40` | `src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot`, `tools/research/cogsguard/cvc-debugger-policy-optimizer` | Copied robot policy, tests, policy architecture docs, and optimizer container; web UI left out. |
| `Metta-AI/cogora` | `436d60e52c33382da2547a05cf564918b8a4154d` | `policies/cyborg/cogamer/cogora` | Copied CVC player cog and SDK code; large cogent session logs left out. |
| `Metta-AI/bitworld` | `f2c063eeea1a43c8a8dc2da6df94797a84fdf081` | `policies/symbolic/bitworld`, `policies/cyborg/bitworld/among-them`, `docs/bitworld/among-them` | Copied player-policy projects and player docs without game source. |
| `Metta-AI/cogames-attempts` | `e80a0b67b0272c1c80206da3704dfd88a70162ea` | `policies/neural/cogames-attempts`, `tools/research/cogames-attempts`, `docs/experiments/cogames-attempts` | Copied trainable policy experiments, sweeps, eval scripts, and research notes. |
| `Metta-AI/metta:cogames-rl-researcher` | `aa1d7c5b48c8548d29632562137e571d738d0650` | `tools/research/cogames-rl-researcher` | GitHub repo was not accessible under `Metta-AI/cogames-rl-researcher`; copied clean monorepo directory instead. |
| local `cogbase` project | `d9621fb0f6a1ba324bf5f6e205526665fbfa2707` | `tools/cogbase` | Merged as a standalone base-agent meta-pipeline toolkit with its own package metadata, docs, tests, and lockfile. |

## Post-Collation Updates

- 2026-05-12: copied uncommitted metta `cogames-agents` cyborg framework updates into `src/agent_policies/frameworks/coborg` and `validation/agent-policies-tests/test_cyborg_framework.py` before deleting metta's copy. These source-preserving updates add shared locked memory snapshots, `ModeDecision`, `AsyncStrategyRunner`, metrics sinks, and priority `ReflexRule` support. They came from the metta worktree rather than from a committed metta revision.
- 2026-05-12: normalized importable Python source under `src/agent_policies`, added root package metadata, and removed historical `cogames_agents`, `cogamer`, `framework`, and `robot` import roots. Current code should use canonical `agent_policies.*` imports and policy class paths.
- 2026-05-13: documented `tools/cogbase` as an intentional standalone tool subtree and normalized Cogbase framework references to the in-repo `agent_policies.frameworks.coborg` package.

## Submodules

| Source | Commit | Target | Notes |
| --- | --- | --- | --- |
| `Metta-AI/co-gas` | `a7a02d0b7f4fdf4cf9c0180ce3684301e3687c48` | `users/relh/co-gas` | Contributor-owned active repo. Shared code should be promoted by explicit copy when it becomes canonical. |

## Inspected But Not Copied

| Source | Commit | Reason |
| --- | --- | --- |
| `Metta-AI/cogames-agents` | `03945ec72a2e30a5d270ee34a210f44bfceddc08` | Stale relative to the metta monorepo copy used as the seed. Retain only as archaeology unless a diff proves unique code. |
| `Metta-AI/cogames`, `Metta-AI/mettagrid`, `Metta-AI/coworld`, `Metta-AI/pufferlib-core` | not copied | Runtime, game, package, or platform sources remain in their owning repos. Their publishing boundaries should not change as part of this policy collation. |
| Local `bitworld` and `personal_cogs` checkouts | not copied | Local worktrees were dirty. Clean staged clones or submodules should be used for source migrations. |

## Follow-Up Work

- Continue promoting source snapshots into `src/agent_policies` when they need to
  be importable shared code.
- Decide which generated Cogamer policy repos stay as product artifacts versus
  generated examples.
- Build machine-readable policy manifests with owner, target game, policy
  reference, eval command, benchmark command, comparison command, and upload
  command.
- Keep canonical source and docs on `agent_policies.*` imports.
