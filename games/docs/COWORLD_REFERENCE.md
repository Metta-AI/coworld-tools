# Coworld Reference

> Primary navigation guide for coding agents working in this `games` repository. This is not the
> authoritative coworld spec - it is an index. When a section here is too thin, follow the cited
> paths into the metta repo and treat those sources as the source of truth.

## 1. What this project is

`games` is the consolidated home for Metta-AI game definitions and runtime packages. The repo
contains imported game packages under `games/<name>/`, reusable authoring templates under
`templates/`, and shared migration notes under `docs/`.

For Coworld specifically, a game package is responsible for the game container: rules, state,
runtime config schema, results schema, live viewer, replay viewer, and the `game` section of a
`coworld_manifest.json`.

## 2. TL;DR for a future agent

- Canonical coworld package: `~/coding/metta/packages/coworld/`.
- Game runtime contract: `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md`.
- Manifest source of truth: `~/coding/metta/packages/coworld/src/coworld/types.py`.
- Generated manifest schema: `~/coding/metta/packages/coworld/src/coworld/coworld_manifest_schema.json`.
- Local runner: `~/coding/metta/packages/coworld/src/coworld/runner/runner.py`.
- Hosted runner: `~/coding/metta/packages/coworld/src/coworld/runner/kubernetes_runner.py`.
- Runnable role shape: `docs/specs/0043-user-container-management.md` in metta.
- Imported game inventory: [`docs/inventory.md`](inventory.md).
- Game-repo conventions: [`docs/GAME_DESIGN.md`](GAME_DESIGN.md).

## 3. Coworld game responsibilities

A Coworld game is exactly one runtime container per episode. It owns:

1. Reading `COGAME_CONFIG_URI`.
2. Serving `GET /healthz` on `0.0.0.0:8080`.
3. Serving player and global viewer websocket routes.
4. Validating player slot tokens.
5. Running the episode to completion.
6. Writing results JSON to `COGAME_RESULTS_URI`.
7. Writing replay data to `COGAME_SAVE_REPLAY_URI`.
8. Serving replay mode when `COGAME_REPLAY_SERVER=1` is set.

The full runtime details live in metta's `GAME_RUNTIME_README.md`; do not duplicate or drift them
here.

## 4. Manifest game shape

The game section is `CoworldGameManifest` in metta:

```python
class CoworldGameManifest(BaseModel):
    name: str
    version: str
    description: str
    owner: str
    config_schema: dict[str, Any]
    results_schema: dict[str, Any]
    runnable: CoworldGameRunnableSpec
    protocols: CoworldProtocolDocs
    docs: CoworldDocs | None = None
```

Important invariants:

- Authored variants and certification configs omit `tokens`; the runner injects them.
- `config_schema` must make the injected token count explicit.
- `results_schema` must include a `scores` array, one number per slot.
- Protocol docs are public HTTP(S) docs, not local Markdown bundled by upload.
- The game image may also implement player, reporter, or other role runnables through different
  `run` argv entries, but the game contract remains the container-server contract above.

## 5. Repo-specific layout

```text
games/
|-- README.md
|-- pyproject.toml
|-- docs/
|   |-- COWORLD_REFERENCE.md
|   |-- GAME_DESIGN.md
|   |-- inventory.md
|   `-- migration-plan.md
|-- games/
|   `-- <game>/
`-- templates/
    `-- <template>/
```

`games/<game>/` preserves the imported game's current package shape unless a migration requires a
narrow compatibility change. Do not force every game into one build system or one runtime language.

## 6. Reference games in this repo

Start with these when orienting on concrete examples:

| Path | Why it matters |
| --- | --- |
| `games/paintarena` | Minimal Coworld certification example imported from metta. |
| `games/cogs_vs_clips` | Coworld wrapper around Cogs vs Clips. |
| `games/liarliar` | Browser-first JavaScript Coworld game with manifest and Dockerfile. |
| `games/persephones_escape` | TypeScript Coworld game; currently needs manifest normalization. |
| `templates/mettagrid-python` | Starting template for new Python / MettaGrid games. |

For the complete list, use [`docs/inventory.md`](inventory.md).

## 7. Things that are easy to get wrong

1. **Do not mutate source repos from here.** Imported repositories stay untouched until humans
   decide retirement or mirroring policy.
2. **Game code is not player code.** Policies belong in `Metta-AI/players` unless they are a small
   game-owned fixture or bundled reference player.
3. **Container-first Coworld games are not Python workspace members by default.** Keep their local
   toolchains inside the game directory.
4. **Do not normalize all games at once.** Preserve behavior first, then migrate package metadata,
   manifests, and tests game by game.
5. **Nested `AGENTS.md` files matter.** Read them before editing a game or template subtree.
6. **`world` is not the game repo concept.** In this naming split, a world is the collection of game,
   players, graders, reporters, commissioners, diagnosers, and optimizers.

## 8. Keep this file honest

Update this file when metta changes the game runtime contract, the Coworld manifest shape, runner
behavior, or the canonical set of examples that future agents should inspect first.
