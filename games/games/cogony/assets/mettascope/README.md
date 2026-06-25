# Custom mettascope assets

Drop PNG files here to override or add to mettascope's built-in sprites.
Paths mirror the installed `mettagrid/nim/mettascope/data/` tree.

Examples:
- `objects/red:hub.png` — override the red-team hub sprite
- `agents/scout.png` — override the scout agent sprite

Files here are copied over the installed mettascope data dir via an idempotent
manifest-hash overlay on first `import cogony` after each change (see
`src/cogony/_mettascope_assets.py`).
