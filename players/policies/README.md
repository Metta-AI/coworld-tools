# Policies

This top-level directory is the canonical home for **all** policies in the
repo. It hosts both importable Python packages and runnable non-importable
snapshots, side by side. Reusable frameworks live separately under
`src/agent_policies/frameworks/`.

The tree is split by behavior:

- `scripted/`: deterministic scripted policies that ship as an importable
  Python package (`policies.scripted.*`).
- `symbolic/`: deterministic scripted policies kept as standalone snapshots
  (not Python-importable; kebab-case directory names).
- `cyborg/`: symbolic runtime plus slower LLM, memory, coaching, or
  self-improvement loops. Mixes importable Python (`policies.cyborg.*`) with
  generated snapshots and non-Python players.
- `neural/`: trainable policy experiments and checkpoint-oriented snapshots.

Contributor-owned active projects should stay under `users/<handle>/<project>`
as submodules until code is intentionally promoted into this curated tree.

## Current Families

- `scripted/cogsguard/`: importable CogsGuard scripted policies (Python +
  Nim).
- `cyborg/bitworld/among_them/` and `cyborg/bitworld/coborg_among_them/`:
  importable BitWorld Among Them policies (Python).
- `cyborg/cogsguard/cvc_debugger_robot/`: importable CVC debugger robot
  policy.
- `cyborg/bitworld/among-them/`: BitWorld Among Them policy snapshots that
  include LLM or slow-loop behavior and are not yet normalized into
  importable modules.
- `cyborg/cogamer/cvc/`: importable Cogs-vs-Clips policy (program-table +
  LLM brain). Pairs with the coglet/PCO frameworks under
  `src/agent_policies/frameworks/cogamer/`.
- `cyborg/cogamer/generated/`: generated-policy source snapshots derived
  from `cvc/`.
- `symbolic/bitworld/`: copied BitWorld player-policy projects by game.
- `neural/cogames-attempts/`: trainable policy and teacher-research snapshots
  from the `cogames-attempts` research repo.

## Importing

Importable subpackages use the top-level `policies` namespace, e.g.:

```python
from policies.scripted.cogsguard.scripted_registry import list_scripted_agent_names
from policies.cyborg.bitworld.among_them import BitWorldAmongThemCyborgPolicy
from policies.cyborg.cogamer.cvc.cogamer_policy import CvCPolicy
```

Snapshot directories with hyphenated names (e.g. `symbolic/bitworld/among-them/
modulabot/`) are deliberately not Python-importable.
