# Policies

This top-level directory is the canonical home for concrete importable
policies. Reusable frameworks live separately under
`src/agent_policies/frameworks/`.

The tree is split by behavior:

- `scripted/`: deterministic scripted policies that ship as an importable
  Python package (`policies.scripted.*`).
- `cyborg/`: symbolic runtime plus slower LLM, memory, coaching, or
  self-improvement loops (`policies.cyborg.*`).

Contributor-owned active projects live under `users/<handle>/<project>`,
either as submodules or in-tree, until they are intentionally promoted
into this curated tree.

## Current Families

- `scripted/cogsguard/`: importable CogsGuard scripted policies (Python +
  Nim).
- `cyborg/bitworld/among_them/`: importable BitWorld Among Them policy.
- `cyborg/bitworld/coborg_among_them/`: importable BitWorld Among Them
  policy built on the Coborg framework
  (`agent_policies.frameworks.coborg`).

## Importing

```python
from policies.scripted.cogsguard.scripted_registry import list_scripted_agent_names
from policies.cyborg.bitworld.among_them import BitWorldAmongThemCyborgPolicy
from policies.cyborg.bitworld.coborg_among_them import CoborgAmongThemPolicy
```
