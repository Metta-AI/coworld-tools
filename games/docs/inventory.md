# Game Inventory

This repo is the consolidated home for game definitions and runtime packages. The first import copied current source
snapshots into this repo; it did not delete, archive, close, or mark any original source repository. The first
certify-first migration wave now uses standalone `coworld-*` repos as source of truth for games that have been
renamed and upgraded outside this aggregate checkout. While the repo model is still being decided, the matching
`games/<name>` subtrees are kept in parity with those standalone repos.

## Coworld Source Repos

These repositories have been unarchived, renamed from their former `cogame-*` names, and upgraded with a
certifiable Coworld runtime.

| Game | Source of truth | Status |
| --- | --- | --- |
| AmongCogs | `Metta-AI/coworld-amongcogs` | Coworld manifest, game image, reference player image, player/global/replay routes, and certification tests. |
| HungerCog | `Metta-AI/coworld-hungercog` | Coworld manifest, game image, reference player image, player/global/replay routes, and certification tests. |
| Overcogged | `Metta-AI/coworld-overcogged` | Coworld manifest, game image, reference player image, player/global/replay routes, and certification tests. |
| Diplomacog | `Metta-AI/coworld-diplomacog` | Coworld manifest, game image, reference player image, player/global/replay routes, and certification tests. |
| WereCog | `Metta-AI/coworld-werecog` | Coworld manifest, game image, reference player image, player/global/replay routes, and certification tests. |

## Imported Games

| Path | Source | Runtime | Notes |
| --- | --- | --- | --- |
| `games/amongcogs` | `Metta-AI/coworld-amongcogs` | Python / MettaGrid / Coworld | Among-Us-inspired MettaGrid game with custom assets and policies; source of truth moved to the standalone Coworld repo. |
| `games/cogsguard` | `Metta-AI/cogame-cogsguard` | Python / MettaGrid / Coworld source | Cogs vs Clips / CogsGuard game package and eval missions, built into the Coworld image from source. |
| `games/diplomacog` | `Metta-AI/coworld-diplomacog` | Python / MettaGrid / Coworld | Station-based diplomacy game; source of truth moved to the standalone Coworld repo. |
| `games/hungercog` | `Metta-AI/coworld-hungercog` | Python / MettaGrid / Coworld | Survival/resource game with train and play recipe entrypoints; source of truth moved to the standalone Coworld repo. |
| `games/overcogged` | `Metta-AI/coworld-overcogged` | Python / MettaGrid / Coworld | Overcooked-style cooperative kitchen game; source of truth moved to the standalone Coworld repo. |
| `games/tribalcog` | `Metta-AI/cogame-tribal` | Nim + Python wrapper | Tribal Village / AoE-style native game package. |
| `games/werecog` | `Metta-AI/coworld-werecog` | Python / MettaGrid / Coworld | Werewolf/social-deduction MettaGrid game; source of truth moved to the standalone Coworld repo. |
| `games/euchre` | `Metta-AI/cogame-euchre` | Python / MettaGrid | Euchre card-game package built from the cogame template. |
| `games/bombercog` | `Metta-AI/bomber-cog` | Python / MettaGrid | Bomberman-style deathmatch game. |
| `games/coghouse` | `Metta-AI/cogame-coghouse` | Python / MettaGrid / CoGames | Coghouse game package; still mostly template-shaped after import and not a root workspace member until `src/cogame` is renamed. |
| `games/cogony` | `Metta-AI/cogame-cogony`, `Metta-AI/cogamer-policy-cogony` | Python / MettaGrid / web server | Cogs-vs-Clips-derived game with bundled baseline, Toolsy, and Cogamer policy packages. |
| `games/cogwars` | `Metta-AI/cogame-cogwars` | Python / MettaGrid / CoGames | Cogwars game package; still mostly template-shaped after import and not a root workspace member until `src/cogame` is renamed. |
| `games/cogisis` | `Metta-AI/cogame-cogisis` | Python game server | Nemesis-style first-party Python engine, not MettaGrid. |
| `games/tag` | `Metta-AI/cogame-tag` | Python / MettaGrid / CoGames | Tag game package; still mostly template-shaped after import and not a root workspace member until `src/cogame` is renamed. |
| `games/memory` | `Metta-AI/cogame-memory` | Python / MettaGrid / CoGames | Memory game package; still mostly template-shaped after import and not a root workspace member until `src/cogame` is renamed. |
| `games/liarliar` | `Metta-AI/liarliar` | JavaScript / Coworld | Browser-first bomb-manual Coworld game with manifest and Dockerfile. |
| `games/persephones_escape` | `Metta-AI/persephones-escape` | TypeScript / Coworld | Hidden-role social deduction Coworld game; manifest currently uses an older nested Cogame manifest shape. |
| `games/cogshambo` | `Metta-AI/cogshambo` | TypeScript browser/server | Browser game with server/client/runtime assets; not yet normalized to Coworld manifest form here. |
| `games/paintarena` | `Metta-AI/metta:packages/coworld/src/coworld/examples/paintarena` | Python / Coworld | Minimal Coworld certification example. |
| `games/cogs_vs_clips` | `Metta-AI/metta:packages/coworld/src/coworld/examples/cogs_vs_clips` | Python / Coworld | Coworld wrapper around Cogs vs Clips. |

## Template

| Path | Source | Purpose |
| --- | --- | --- |
| `templates/mettagrid-python` | `Metta-AI/cogame` | Vestigial cogame template, kept as the starting template for new Python/MettaGrid games. |

## Not Imported

| Repository | Reason |
| --- | --- |
| `Metta-AI/bitworld` | Explicitly excluded. |
| `Metta-AI/co-gas` | Policy/workflow repo, not a game repo. |
