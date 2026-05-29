# Coworld Grader Audit

Audit date: 2026-05-29.

This audit searched local Metta-AI checkouts and GitHub code search for `coworld_manifest.json` and
`coworld_manifest_template.json`, then parsed manifests with Coworld `game` and `player` sections. Local inspection
used fresh temporary clones under `/private/tmp/metta-ai-coworld-audit` for repos not already checked out.

## Existing Coverage

These Coworlds already had manifest grader entries and cataloged starter graders in this repo:

| Coworld | Grader |
| --- | --- |
| `among_them` | `among-them-grader` |
| `cogs_vs_clips` | `cogs-v-clips-grader` |
| `paintarena` | `paint-arena-grader` |

The generic `default-grader` also exists for manifests that need a fallback scalar score-spread grader.

## Missing Coverage Found

The audit found Coworld manifests with absent or empty `grader` arrays in these repos:

| Repo | Coworlds without graders |
| --- | --- |
| `Metta-AI/bitworld` | `asteroid_arena`, `big_adventure`, `crewrift`, `heartleaf`, `infinite_blocks`, `jumper`, `planet_wars` |
| `Metta-AI/cogame-staghunt` | `stag_hunt` |
| `Metta-AI/coworld-asteroid-arena` | `asteroid_arena` |
| `Metta-AI/coworld-big-adventure` | `big_adventure` |
| `Metta-AI/coworld-crewrift` | `crewrift` |
| `Metta-AI/coworld-heartleaf` | `heartleaf` |
| `Metta-AI/coworld-infinite-blocks` | `infinite_blocks` |
| `Metta-AI/coworld-jumper` | `jumper` |
| `Metta-AI/coworld-planet-wars` | `planet_wars` |
| `Metta-AI/coworld-tribal-fortress` | `coworld-tribal-fortress` |
| `Metta-AI/coworld-tribal-quest` | `tribal_quest` |
| `Metta-AI/games` | `amongcogs`, `cogs_vs_clips`, `diplomacog`, `hungercog`, `liar-liar-cut-the-wire`, `overcogged`, `paintarena`, `persephones-escape`, `tribalcog`, `werecog` |
| `Metta-AI/liarliar` | `liar-liar-cut-the-wire` |
| `Metta-AI/metta` | `crewrift` template |
| `Metta-AI/persephones-escape` | `persephones_escape` manifest and template |

Optimizer artifact snapshots with empty graders were ignored as downloaded/runtime artifacts, not source manifests.

## Repair Added Here

This repo now provides six additional starter graders:

| New grader | Intended Coworlds |
| --- | --- |
| `bitworld-score-grader` | `asteroid_arena`, `big_adventure`, `heartleaf`, `infinite_blocks`, `jumper`, `planet_wars`, `stag_hunt`, `tribal_quest` |
| `crewrift-grader` | `crewrift` |
| `mettagrid-score-grader` | `amongcogs`, `diplomacog`, `hungercog`, `overcogged`, `werecog`; usable as a simple fallback for score/steps manifests |
| `liarliar-grader` | `liar-liar-cut-the-wire` |
| `persephones-escape-grader` | `persephones_escape`, `persephones-escape` |
| `tribal-cog-grader` | `tribalcog`, `coworld-tribal-fortress` |

The previously existing `cogs-v-clips-grader` and `paint-arena-grader` cover the corresponding missing manifests in
`Metta-AI/games` once those manifests are wired to grader entries.

## Manifest Wiring Still Required

This repository owns grader implementations and catalog entries. The Coworld manifests listed above still need PRs in
their source repos to add `manifest.grader[]` entries pointing at the appropriate grader images after images are built
and published.
