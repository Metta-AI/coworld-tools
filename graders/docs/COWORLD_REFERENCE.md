# Coworld Reference

> Navigation guide for coding agents working in this `graders` repo. This file is not the authoritative Coworld spec;
> treat the Metta checkout as the source of truth.

## Current Facts

- Canonical Coworld package: `~/coding/metta/packages/coworld/`.
- Grader role doc: `~/coding/metta/packages/coworld/src/coworld/docs/roles/grader.md`.
- Role overview: `~/coding/metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md`.
- Episode bundle contract: `~/coding/metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`.
- Manifest field reference: `~/coding/metta/packages/coworld/src/coworld/MANIFEST_README.md`.
- Generated manifest schema: `~/coding/metta/packages/coworld/src/coworld/coworld_manifest_schema.json`.
- Role repo spec: `~/coding/metta/docs/specs/0045-coworld-role-repos.md`.

## Role Model

Coworld roles are `game`, `player`, `commissioner`, `reporter`, `grader`, `diagnoser`, and `optimizer`.
`grader` is a post-episode supporting role declared under `manifest.grader[]`.

The grader role is still marked `reserved`, and its contract is tentative. Even so, the current docs define the shape
this repo should follow:

- input: `COGAME_EPISODE_BUNDLE_URI`, pointing at a zip episode bundle;
- output: `COGAME_GRADE_URI`, pointing at a JSON grade destination;
- output body: a required `score`, plus recommended `grader_id`;
- lifecycle: on-demand, not automatically run by the episode runner.

## Manifest Shape

Every declared role runnable uses the Coworld declared-role shape:

```python
class CoworldDeclaredRoleSpec(CoworldDeclaredRunnableSpec):
    type: Literal["player", "reporter", "commissioner", "grader", "diagnoser", "optimizer"]
```

For graders, the manifest field is:

```python
grader: list[CoworldDeclaredRoleSpec]
```

The current prose docs say all supporting role sections should be declared in Coworld manifests. The current generated
schema in Metta still accepts omitted non-player supporting role arrays during this transition. Do not treat that schema
leniency as a license for this repo to define a different role contract.

## Role Repo Catalog

`CATALOG.yaml` is the implementation index for this repo. Per `0045-coworld-role-repos.md`, source present on disk
without a catalog entry is incomplete. Empty scaffold directories should remain uncataloged until they contain a real
runtime implementation with a Dockerfile and README.

## Useful Questions

| Question | Start here |
| --- | --- |
| What does a grader receive and write? | `packages/coworld/src/coworld/docs/roles/grader.md` |
| What is an episode bundle? | `packages/coworld/src/coworld/EPISODE_BUNDLE_README.md` |
| How do Coworld roles compose? | `packages/coworld/src/coworld/docs/roles/OVERVIEW.md` |
| What belongs in a manifest entry? | `packages/coworld/src/coworld/MANIFEST_README.md` |
| What is the role-repo structure? | `docs/specs/0045-coworld-role-repos.md` |

## Keep This File Honest

Update this file when the Metta Coworld docs change the grader env vars, output schema, lifecycle, manifest shape,
or role-repo catalog requirements.
