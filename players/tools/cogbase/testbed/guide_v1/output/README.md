# guide_v1 Generated Artifacts

This directory is for game-specific guide bundles produced by the `guide_v1`
meta-pipeline. These bundles are outputs, not reusable `guide_v1` toolkit code.

`guide_v1` is the canonical first-stage generator for new games. A guide bundle
should establish the player interface contract, classify observations as
symbolic, visual, or mixed, and identify any downstream visual artifacts,
parsers, capture plans, or policy scaffolds that should be generated later.

Typical contents for one generated game bundle:

```text
output/
  my_game/
    README.md
    GAME_OVERVIEW.md
    INTERFACE_CONTRACT.md
    ...
    .drafts/
```

Use `generate_guides.py --output-dir output/<game_slug>` to keep generated
artifacts separate from the generator code, prompt templates, and orchestration
modules in the parent directory.

Future coding agents should treat game directories here as generated artifact
state. Modify `generate_guides.py`, `guide_v1/`, or `prompts/` when changing
the meta-pipeline itself.
