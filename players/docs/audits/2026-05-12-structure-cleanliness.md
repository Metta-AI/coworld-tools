# Structure And Cleanliness Audit

Date: 2026-05-12

## Scope

This audit reviewed the `agent-policies` repository structure, with special
attention to the former `cogames-agents` source split and the
`policies/cyborg/coborg` directory.

## Resolved Direction

The right package boundary is `agent_policies`, not a resurrected
`cogames-agents` package. Historical import roots were removed after canonical
repo-local references were migrated.

Canonical structure:

```text
src/agent_policies/
  frameworks/
    coborg/
    cogamer/
    cyborg_evolution/
  policies/
    scripted/cogsguard/
    cyborg/bitworld/among_them/
    cyborg/cogsguard/cvc_debugger_robot/
  tools/
    eval/cogsguard/
```

## Findings

### Former `cogames-agents` Source Needed Assimilation

The old source had been split across `policies/`, `tools/`, legacy packaging
files, and validation tests. That made the repo look organized by taxonomy while
still behaving like an external `cogames_agents` install was required.

Resolution:

- CogsGuard scripted Python/Nim/evolution modules moved to
  `src/agent_policies/policies/scripted/cogsguard/`.
- BitWorld Among Them Python policies moved to
  `src/agent_policies/policies/cyborg/bitworld/among_them/`.
- CogsGuard eval maps and metric helpers moved to
  `src/agent_policies/tools/eval/cogsguard/`.
- Root `pyproject.toml` now defines the `agent-policies` distribution.
- Old `tools/packaging/cogames-agents-legacy` package files were removed.
- Historical `src/cogames_agents/`, `src/cogamer/`, `src/framework/`, and
  `src/robot/` compatibility wrappers were removed.

### Coborg Contained Multiple Concepts Under One Directory

`policies/cyborg/coborg` mixed a reusable two-loop runtime, a separate
self-improving policy framework, and a concrete CVC robot policy.

Resolution:

- Reusable two-loop runtime: `src/agent_policies/frameworks/coborg/`.
- Self-improving policy framework:
  `src/agent_policies/frameworks/cyborg_evolution/`.
- Concrete CVC robot policy:
  `src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot/`.

### Cogamer Is A Framework, Not A Policy Snapshot

The Cogamer core is a reusable framework, while generated Cogamer policy repos
are product/source snapshots.

Resolution:

- Cogamer core moved to `src/agent_policies/frameworks/cogamer/`.
- Generated Cogamer policy artifacts remain under `policies/cyborg/cogamer/`
  until they are intentionally promoted or archived.

## Remaining Cleanup

- Top-level `policies/` still contains generated and non-Python snapshots. That
  is acceptable, but each serious policy should eventually get a manifest with
  owner, status, target game, import path or upload path, eval command, and
  packaging notes.
- `tools/cogbase/` is an intentional standalone tool subtree with its own package
  metadata, docs, tests, and lockfile. It should stay under `tools/` until it is
  either promoted into `src/agent_policies/tools/` or intentionally split out.
- Several historical docs under `docs/legacy/` intentionally preserve old
  `cogames-agents` paths. They should remain clearly marked as archaeology.
- Some old research scripts still mention local `~/projects/cogames-agents`
  paths. Treat those as experiment records unless a workflow is revived.

## Validation Boundary

Validation tests were renamed to `validation/agent-policies-tests/` and updated
to use canonical `agent_policies.*` imports.
