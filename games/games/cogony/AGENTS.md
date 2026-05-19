# AGENTS.md

Guidance for AI assistants (Claude Code, Codex) working in this repo.

## What this is

`cogony` is a MettaGrid game vendored from `cogs_vs_clips`. The single
registered mission is `CogonyMission` — a 4-team corner-compound arena where
agents bump hubs to join/swap teams and compete for junctions. All mechanics
live in `src/cogony/`.

## Source of truth: RULES.md

[`RULES.md`](RULES.md) is the spec for the game. **Every rule change
starts there.** Workflow:

1. Edit RULES.md — add/update the numbered rule.
2. Make the code in `src/cogony/` match.
3. Add or update the integration test in `tests/rules/test_rule_NN_<slug>.py`
   so it exercises the rule on a small map.

If RULES.md and the code disagree, RULES.md wins — fix the code.

4. **After every RULES.md edit**, regenerate both HTML pages and open them:
   - `/tmp/cogony_rules.html` — technical rules reference (dark cyber
     aesthetic, sidebar nav, gear sprites). See existing file for template.
   - `/tmp/guide.html` — player-facing guide (explains the game
     intuitively with numbered walkthroughs, examples, tips, and gear
     sprites). See existing file for template.

## Sprites

**Always check existing sprite sizes before adding new ones.** Generated images
are typically 1024x1024 and must be resized to match the target directory.

| Directory                          | Size   | Use                          |
|------------------------------------|--------|------------------------------|
| `data/vibe/`                       | 32x32  | Vibe button icons            |
| `data/objects/`                    | 64x64  | Grid object sprites          |
| `assets/mettascope/resources/`     | varies | Status bar / inventory icons |

Steps for any new sprite:
1. Generate image (nano-banana or artgen).
2. Remove background with `rembg` (Python API: `from rembg import remove`).
3. Resize to match the target directory (use `Image.resize(..., Image.LANCZOS)`).
4. Save to the correct directory.
5. Rebuild MettaScope and `rsync data/` to venv.

MettaScope loads vibe icons from `vibe/<name>` automatically.

## Spawning objects at runtime

`SpawnObjectMutation` and custom spawn mutations create objects from configs
in `game_config.objects`. **Known issue:** the C++ config's `initial_inventory`
is not preserved through the pybind11/variant pipeline — spawned objects start
with empty inventory. Work around this by setting inventory explicitly in the
C++ mutation after spawning:

```cpp
for (const auto& [name, amount] : _config.initial_resources) {
  for (size_t i = 0; i < rnames.size(); i++) {
    if (rnames[i] == name) {
      trap->inventory.update(static_cast<InventoryItem>(i),
                             static_cast<InventoryDelta>(amount), true, false);
      break;
    }
  }
}
```

Pass `initial_resources` as `vector<pair<string, int>>` (name, amount) in the
mutation config, then look up resource IDs from `ctx.game_config->resource_names`.

Also note: `grid_objects()` only reports resources that are in the object's
observation features. Spawned objects may show empty inventory in grid_objects()
even when resources are set. Test behavior (bumping, damage) rather than
reading inventory from grid_objects() for dynamically spawned objects.

## Testing game mechanics

Integration tests should exercise the full player action flow, not just config
setup. Always test from the agent's perspective: set vibe → perform action →
verify consequence.

```python
# Good: tests the full trap lifecycle
step_with_actions(sim, ["change_vibe_trap"])    # agent sets trap vibe
step_with_actions(sim, ["move_east"])           # agent moves, trap drops
step_with_actions(sim, ["move_west"])           # agent walks back onto trap
assert sim.agent(0).inventory["coherence"] < initial_coh  # took damage

# Bad: only checks config
assert _trap(sim).get("inv:time_left", 0) == 5  # may not work for spawned objects
```

When testing multi-tick mechanics (TTL, decay), verify the OUTCOME (trap stops
triggering) rather than reading intermediate inventory state.

## Quick commands

```bash
uv sync --extra dev                    # install deps
uv run pytest -q                        # run tests
uv run cogony play --render gui         # launch with MettaScope
uv run cogony play --render none        # headless sanity check
./scripts/build-mettascope.sh           # rebuild Nim dylib + mettagrid_c.so
```

## Architecture

- `src/cogony/mission.py` — the single `CogonyMission` class. Baked-in
  four-corner layout, default `CogonyVariant` added as a base variant.
- `src/cogony/base.py` — `BaseVariant`: cross-configures the sub-variants that
  shape the game loop (clips/days/damage/gear/roles/teams/territory/items/…).
  Sets per-agent heart reward; generates the death-clear-inventory handler.
- `src/cogony/game/` — the variant tree. Each module is one variant. Keep new
  mechanics self-contained and register the variant in `game/__init__.py`'s
  `VARIANTS` list + add it to `BaseVariant.dependencies()` if it should always
  be active.
- `src/cogony/terrain.py` — arena / compound / map generation. `find_arena(map)`
  gets a reference to the current arena config.
- `src/cogony/registration.py` — wires `CogonyGame` into the cogames registry.
- `src/cogony/cli.py` — the `cogony` console script.
- `src/cogony/_mettascope_assets.py` — on `import cogony`, syncs
  `assets/mettascope/` onto the installed mettagrid's data dir (manifest-hash
  sentinel: only copies when files change).

## Iteration on mettascope (Nim) and mettagrid (C++/Python)

`.mettagrid/` is a sparse clone of `Metta-AI/metta` containing
`packages/mettagrid/`. Edit Nim/C++/Python source there, then run
`./scripts/build-mettascope.sh` — it rebuilds `libmettascope.dylib` with Nim
and `mettagrid_c.so` with bazel, ad-hoc signs the dylibs, and overlays them
+ the relevant Python modules onto the installed `mettagrid` in `.venv/`.

## Adding art assets

Drop raw PNGs into `assets/mettascope/<subdir>/<name>.png` matching the
mettascope data layout (`resources/*.png`, `objects/*.png`, `agents/*.png`,
etc.). The overlay picks them up on the next `import cogony`.

For AI-generated art following a shared style guide, use **ArtGen** — the
folder-driven pipeline in the vendored mettascope source:
[`packages/mettagrid/nim/mettascope/tools/art/artgen.md`](.mettagrid/packages/mettagrid/nim/mettascope/tools/art/artgen.md).
ArtGen reads markdown asset specs from `artin/`, generates concept images via
an LLM image provider, converts them to 3D via Tripo, and renders final
sprites. Copy the generated PNGs into `assets/mettascope/` when ready.

## Non-negotiables

1. **Run the code after every change.** After ANY code or config change,
   run both of these before reporting success:
   ```bash
   uv run pytest -q                                             # all tests must pass
   uv run cogony play --render none --max-steps 5                # headless smoke
   uv run cogony play --render gui --max-steps 5 --autostart     # GUI smoke (autoplay)
   ```
   If either fails, fix it before moving on. Don't ask — just run.
6. **Test-first for bug reports.** When the user reports a game logic bug,
   FIRST write a failing integration test in `tests/rules/` that
   reproduces it. Verify it fails. THEN fix the code. Verify the test
   passes. This ensures the bug stays fixed.
2. **Let it crash.** No broad `try/except`. If the fix looks like a hotfix,
   zoom out and find the real invariant.
3. **Minimal diffs, root-cause fixes.** Touch more files if that's what the
   fix actually needs.
4. **No backwards-compat shims.** Update callsites; delete the old path.
5. **Prefer Pydantic models over raw dicts.** `MettaGridConfig` and its
   children are pydantic — use them directly.
7. **Integer math in the simulator.** All game values, inventory, and
   combat math must use integer arithmetic. Never use floats for game
   state — floats cause rounding bugs and non-determinism. The only
   exception is GameValue weights in `SumGameValue` (which are float
   coefficients applied to integer operands).

## Where to make changes

- **Mechanics** — add a new variant in `src/cogony/game/<name>.py`,
  register it in `game/__init__.py`, and add it to `BaseVariant.dependencies()`
  if it's part of the default loop. Variant `modify_env` runs in topo order
  after its deps; `BaseVariant.modify_env` runs last so it sees the final
  shape of `env.game`.
- **Map / compounds** — edit `CogonyVariant` in
  `src/cogony/game/teams/cogony.py` (compound placements) and `BaseVariant`
  in `src/cogony/base.py` (map size, spawn counts).
- **Station sprites** — put the image at `assets/mettascope/objects/<name>.png`
  and set `env.game.render.assets[map_name] = [RenderAsset(asset="<name>")]`
  when you create the `GridObjectConfig`.
- **Engine primitives** — new GameValue types, mutations, etc. go in
  `.mettagrid/packages/mettagrid/` (both C++ header + `.cpp` + pybind
  binding + Python wrapper + c_value_config converter). Rebuild via
  `./scripts/build-mettascope.sh`.

## Mettascope (Nim) changes — verification checklist

When modifying Nim mettascope code (panels, HUD, vibes, sprites), changes
can silently fail to appear if the Nim compiler cache is stale. **Always
follow this procedure:**

1. **Clear the Nim cache before rebuilding:**
   ```bash
   rm -rf ~/.cache/nim/mettascope_r ~/.cache/nim/mettascope_check
   ```
2. **Delete the old dylib to force recompilation:**
   ```bash
   rm -f .mettagrid/packages/mettagrid/nim/mettascope/bindings/generated/libmettascope.dylib
   ```
3. **Rebuild:**
   ```bash
   ./scripts/build-mettascope.sh
   ```
4. **Verify the change is in the compiled dylib:**
   ```bash
   # For new panels/strings, grep the dylib for a unique string:
   strings .venv/lib/python3.12/site-packages/mettagrid/nim/mettascope/bindings/generated/libmettascope.dylib | grep "YourNewString"
   ```
5. **Verify new sprite/data files are synced to venv:**
   ```bash
   ls .venv/lib/python3.12/site-packages/mettagrid/nim/mettascope/data/vibe/yourfile.png
   ```
6. **Restart the game** — the dylib is loaded once at startup:
   ```bash
   uv run cogony play --render gui --max-steps 5 --autostart
   ```

### Common pitfalls

- **Nim cache**: The compiler caches aggressively at `~/.cache/nim/`.
  If you change `.nim` files but the dylib doesn't change, clear the cache.
- **Data files**: `./scripts/build-mettascope.sh` syncs both `src/` and
  `data/` to the venv. New sprites (vibes, resources, objects) in
  `.mettagrid/.../data/` get copied automatically.
- **Panel not appearing**: Check that the panel is both imported in
  `mettascope.nim` and added via `addPanel()`. Verify with `strings`
  on the dylib. Tab bars have limited width — if too many tabs are in
  one area, some may be clipped.
- **Stale dylib in venv**: The build script copies the freshly compiled
  dylib to the venv. If the build was a no-op (cache hit), the venv
  dylib won't change. Always clear cache + delete dylib first.
