# Among Them Policies

Importable policies for the BitWorld Among Them Coworld.

## Layout

```
players/among_them/
├── README.md
├── scripted/    # BitWorldAmongThem* screen-space scripted policies (importable Python)
├── coborg/      # Coborg two-loop framework consumer (P0 scaffold; importable Python)
└── starter/     # Canonical Nim source for the bundled "ivotewell" starter player
```

- `scripted/` and `coborg/` are importable Python packages used inside the
  workspace (`players.among_them.scripted`, `players.among_them.coborg`).
- `starter/` is the canonical source for the bundled `ivotewell` baseline
  player used by the uploaded Among Them Coworld. It is built from a
  BitWorld checkout (see `starter/README.md`) and shipped as part of the
  Coworld bundle, not imported as Python.

## Importing

```python
from players.among_them.scripted import BitWorldAmongThemCyborgPolicy
from players.among_them.coborg import build_runtime
```

For public-league participation, follow the Coworld guide at
<https://softmax.com/play_amongthem.md>.
