# Cogame Template Upstream

Tribal Village is connected to `Metta-AI/cogame` through git history so future template updates can be merged from the template repo. The Nim runtime remains the source of truth for this game.

Use `cogame` as the upstream remote name:

```bash
git remote add cogame git@github.com:Metta-AI/cogame.git
git fetch cogame
```

To import template updates:

```bash
git fetch cogame
git merge cogame/main
```

Keep the Tribal Village runtime separate from the generic template package:

- Nim simulation, renderer, tests, and assets stay in `src/`, `tests/`, `data/`, and `tribal_village.nim`.
- The Python package stays under `tribal_village_env/`.
- The Metta optional install bridge stays in `tribal_village_env/recipe.py`.
- Template infrastructure should only be adopted when it applies cleanly to this standalone package.

After a template merge, run:

```bash
make check
timeout 15s nim r -d:release --path:src tribal_village.nim
make test-nim
uv run pytest tests/test_cli.py -q
```
