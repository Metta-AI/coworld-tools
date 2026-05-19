# CogsGuard Policies

Importable scripted policies for the Cogs vs Clips arena (CogsGuard), in
both Python and Nim. Used for ablation studies, baseline evaluation, and
historical comparison.

## Layout

```
players/cogsguard/
├── README.md
├── scripted_registry.py        # Discovers short_names from sibling dirs
├── _shared/                    # Helpers shared across multiple policies
│   ├── common/                 # geometry, context, entity_map, goal, roles, …
│   ├── pathfinding.py
│   ├── types.py
│   └── utils.py
├── baseline/                   # short_name: "baseline" (BaselinePolicy)
├── tiny_baseline/              # short_name: "tiny_baseline" (DemoPolicy)
├── role/                       # main vibe-based CogsguardPolicy family
│   ├── README.md               # vibe/role detail
│   ├── policy.py               # short_names: "role", "wombo"
│   ├── teacher.py              # short_name: "teacher"
│   ├── v2_agent.py             # short_name: "cogsguard_v2"
│   ├── control_agent.py        # short_name: "cogsguard_control"
│   ├── targeted_agent.py       # short_name: "cogsguard_targeted"
│   ├── aligner.py / miner.py / scout.py / scrambler.py / behavior_hooks.py / …
│   └── evolution/              # role-evolution coordinator (consumed by role only)
├── buggy/                      # short_name: "buggy" (Planky goal-tree variant)
├── cranky/                     # short_name: "cranky" (Cogas goal-tree variant)
└── nim/                        # Nim agents: "thinky", "nim_random", "race_car",
                                # "role_nim", "alignall", "nlanky"
```

The `_shared/` directory is the one explicit exception to the "each policy
wholly self-contained" rule for `players/`. It is consumed by `baseline/`,
`tiny_baseline/`, `role/`, `buggy/`, and `cranky/`.

## Importing

```python
from players.cogsguard.scripted_registry import list_scripted_agent_names
from players.cogsguard.baseline import BaselinePolicy
from players.cogsguard.tiny_baseline import DemoPolicy
from players.cogsguard.role import CogsguardPolicy, CogsguardTeacherPolicy
from players.cogsguard.buggy.policy import BuggyPolicy
from players.cogsguard.cranky.policy import CrankyPolicy
from players.cogsguard.nim.agents import (
    ThinkyAgentsMultiPolicy,
    RandomAgentsMultiPolicy,
    NlankyAgentsMultiPolicy,
)
```

## Short-name discovery

`scripted_registry.py` walks every subdirectory of `players/cogsguard/`
(except `_shared/`), parses each Python module, and collects
`short_names` declared on policy classes. The discovered names become URIs
like `metta://policy/role` for `discover_and_register_policies` to bind.

## Running policies

CogsGuard policies are intended to be run via the `cogames` and `mettagrid`
runtimes. See `role/README.md` for the canonical CogsGuard vibe API; the
baseline and tiny variants expose minimal stateless interfaces useful for
ablation studies.
