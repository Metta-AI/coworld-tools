# Cogisis Agent Notes

Cogisis is a Nemesis-style cogame with a first-party engine in this repository.
Do not add `mettagrid`, `mettascope`, or vendored Metta engine paths as runtime
dependencies unless the user explicitly changes that direction.

## Working Rules

- The executable game loop lives in `src/cogisis/engine.py`.
- Mission setup lives in `src/cogisis/mission.py`.
- Bot policies live in `src/cogisis/policies.py` and should use only the public
  simulator/world API.
- `RULES.md` is the implementation contract. Do not paste rulebook text into
  repo files.
- Keep gameplay changes covered by focused tests in `tests/`.
- Run `uv run pytest -q` after logical engine changes.

## Smoke Commands

```bash
uv run cogisis --render none --autorun --max-steps 10
uv run cogisis --cogs 2 --render unicode --autorun --max-steps 5 --policy survivor
uv run pytest -q
```
