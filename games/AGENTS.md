# AGENTS.md

Guidance for AI assistants working in this repository.

- Run `git pull` before starting repository work.
- Read any nested `AGENTS.md` before editing files under a game or template subtree.
- Prefer `rg` for search.
- Do not delete, archive, close, or otherwise mutate the source repositories that were imported here.
- Keep game migrations narrow: preserve each game's package/runtime shape unless a change is needed to make it work inside this repo.
- Put shared authoring guidance in `docs/` or `templates/`; avoid copying new duplicated docs into every game.
