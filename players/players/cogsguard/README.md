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
│   ├── semantic/               # LLM/player semantic helpers over cogsguard.semantic
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
`tiny_baseline/`, `role/`, `buggy/`, and `cranky/`. Game-owned semantic
decoding lives in `cogsguard.semantic` in `Metta-AI/coworld-cogs-vs-clips`;
`_shared/semantic/` contains the policy-facing prompt, planner, learning, and
progress helpers that build on that public surface.

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

Each leaf ships as a self-contained Coworld player container. The canonical
production path is the leaf's `build.sh`:

```bash
players/cogsguard/<leaf>/build.sh        # → docker image + manifest snippet
```

The image hosts the policy inside
[`players.player_sdk.coworld_json_bridge`](../player_sdk/coworld_json_bridge.py),
which speaks the `coworld.player.v1` JSON protocol over the websocket the
Coworld runner supplies in `COWORLD_PLAYER_WS_URL`. See
[`docs/coworld-player-packaging.md`](../../docs/coworld-player-packaging.md)
for the player contract and each leaf's README for policy-specific notes:

- [`baseline/`](baseline/README.md), [`tiny_baseline/`](tiny_baseline/README.md)
  — single-file scripted policies, useful baselines and reading references.
- [`buggy/`](buggy/README.md), [`cranky/`](cranky/README.md) — goal-tree
  Python siblings (Planky/Cogas brains) used for tuning experiments.
- [`role/`](role/README.md) — the canonical CogsGuard vibe-based multi-role
  policy. Hosts six registered `short_names` (`role`, `teacher`, `wombo`,
  `cogsguard_v2`, `cogsguard_control`, `cogsguard_targeted`).
- [`nim/`](nim/README.md) — six Nim-backed policies sharing one image.

Policies still expose themselves to the mettagrid runtime via
`MultiAgentPolicy` subclasses and `short_names`; in-tree development
harnesses (e.g. `role/AGENTS.md`'s `DebugHarness`) continue to work
unchanged. The Coworld build path is the deployment surface.
