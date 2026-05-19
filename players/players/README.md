# Players

Canonical home for concrete importable policies. Reusable frameworks live
separately under `src/agent_policies/frameworks/`.

The tree is flat: one subdirectory per game.

```
players/
├── among_them/      # BitWorld Among Them policies
├── cogsguard/       # Cogs vs Clips (CogsGuard) policies
├── infinite_blocks/ # Reserved (no policies yet)
└── paintarena/      # Reserved (no policies yet)
```

Within each game, each policy lives in its own subdirectory. See each
game's README for the per-policy layout. CogsGuard keeps a `_shared/`
folder for helpers used by multiple policies; that is the one explicit
exception to per-policy self-containment.

Contributor-owned active projects live under `users/<handle>/<project>`,
either as submodules or in-tree, until they are intentionally promoted
into this curated tree.

## Importing

```python
from players.cogsguard.scripted_registry import list_scripted_agent_names
from players.cogsguard.role import CogsguardPolicy
from players.cogsguard.baseline import BaselinePolicy
from players.among_them.scripted import BitWorldAmongThemCyborgPolicy
from players.among_them.coborg import build_runtime
```
