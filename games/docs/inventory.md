# Game Inventory

This repo is the consolidated home for game definitions and runtime packages. The first import copied current source
snapshots into this repo; it did not delete, archive, close, or mark any original source repository.

## Imported Games

| Path | Source | Runtime | Notes |
| --- | --- | --- | --- |
| `games/amongcogs` | `Metta-AI/cogame-amongcogs` | Python / MettaGrid / CoGames | Among-Us-inspired MettaGrid game with custom assets and policies. |
| `games/cogsguard` | `Metta-AI/cogame-cogsguard` | Python / MettaGrid / CoGames | Cogs vs Clips / CogsGuard game package and eval missions. |
| `games/diplomacog` | `Metta-AI/cogame-diplomacog` | Python / MettaGrid / CoGames | Station-based diplomacy game; overlaps with the older in-metta `metta/games/diplomacy` surface. |
| `games/hungercog` | `Metta-AI/cogame-hungercog` | Python / MettaGrid / CoGames | Survival/resource game with train and play recipe entrypoints. |
| `games/overcogged` | `Metta-AI/cogame-overcogged` | Python / MettaGrid / CoGames | Overcooked-style cooperative kitchen game. |
| `games/tribalcog` | `Metta-AI/cogame-tribal` | Nim + Python wrapper | Tribal Village / AoE-style native game package. |
| `games/werecog` | `Metta-AI/cogame-werecog` | Python / MettaGrid / CoGames | Werewolf/social-deduction MettaGrid game. |
| `games/euchre` | `Metta-AI/cogame-euchre` | Python / MettaGrid | Euchre card-game package built from the cogame template. |
| `games/bombercog` | `Metta-AI/bomber-cog` | Python / MettaGrid | Bomberman-style deathmatch game. |
| `games/cogony` | `Metta-AI/cogame-cogony` | Python / MettaGrid / web server | Cogs-vs-Clips-derived game with bundled policy packages and browser server. |
| `games/cogisis` | `Metta-AI/cogame-cogisis` | Python game server | Nemesis-style first-party Python engine, not MettaGrid. |
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
| `Metta-AI/cogame-coghouse`, `Metta-AI/cogame-cogwars`, `Metta-AI/cogame-tag`, `Metta-AI/cogame-memory` | Still template-shaped; better handled later as either renamed real games or template experiments. |
