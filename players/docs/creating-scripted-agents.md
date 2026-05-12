# Creating Scripted Agents for co_gas

A step-by-step guide for developers new to co_gas who want to build their first scripted agent.

## 1. Package Structure Overview

```
cogames-agents/src/cogames_agents/policy/
├── scripted_agent/                    # All scripted agent implementations
│   ├── __init__.py
│   ├── types.py                       # Shared data types (Phase, SimpleAgentState, etc.)
│   ├── utils.py                       # Stateless helpers (parsing, adjacency, movement)
│   ├── pathfinding.py                 # BFS pathfinding with occupancy grid
│   ├── common/                        # Shared utilities
│   │   ├── geometry.py                # Manhattan distance, adjacency checks
│   │   ├── roles.py                   # Role enum and vibe mappings
│   │   └── tag_utils.py               # Observation tag parsing
│   ├── baseline_agent.py              # BaselinePolicy (short_name: "baseline")
│   ├── unclipping_agent.py            # UnclippingPolicy (short_name: "ladybug_py")
│   ├── demo_policy.py                 # DemoPolicy (short_name: "tiny_baseline")
│   ├── cogsguard/                     # Team-play agent with roles
│   │   ├── policy.py                  # CogsGuardPolicy (short_name: "role")
│   │   ├── role_trace.py              # Diagnostics helpers for role transitions/traces
│   │   ├── types.py                   # CogsGuard-specific state types
│   │   └── ...
│   └── nim_agents/                    # Nim-backed agents (nlanky, thinky, etc.)
│       ├── agents.py                  # PlankyAgentsMultiPolicy (short_name: "nlanky")
│       ├── goals/                     # Goal definitions per role
│       ├── navigator.py               # Navigation system
│       └── obs_parser.py              # Observation parser
├── scripted_registry.py               # Auto-discovery of agents via short_names
└── nim_agents/                        # Nim-backed agents (compiled, not Python)
```

Key framework classes (from `mettagrid.policy.policy`):

| Class                    | Purpose                                                                         |
| ------------------------ | ------------------------------------------------------------------------------- |
| `MultiAgentPolicy`       | Top-level wrapper; creates per-agent policies. **Your main class.**             |
| `StatefulPolicyImpl[S]`  | Per-agent logic; implements `step_with_state(obs, state) -> (Action, state)`    |
| `StatefulAgentPolicy[S]` | Glue layer; wraps `StatefulPolicyImpl` into `AgentPolicy` with state management |

## 2. Step-by-Step: Create a New Agent

### Step 1: Create the file

Create `scripted_agent/my_agent.py`.

### Step 2: Define your state dataclass

Every agent needs a state object that persists across steps. Extend `SimpleAgentState` or create your own:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

from .types import SimpleAgentState, Phase, CellType


@dataclass
class MyAgentState(SimpleAgentState):
    """State for my custom agent."""
    my_custom_counter: int = 0
    last_target: Optional[tuple[int, int]] = None
```

If your agent doesn't need extra state beyond what `SimpleAgentState` provides, you can use `SimpleAgentState` directly.

### Step 3: Implement the policy logic

Create your `StatefulPolicyImpl` subclass. This is where the per-agent decision-making lives:

```python
class MyAgentPolicyImpl(StatefulPolicyImpl[MyAgentState]):
    def __init__(self, policy_env_info: PolicyEnvInterface, agent_id: int):
        self._agent_id = agent_id
        self._policy_env_info = policy_env_info
        self._obs_hr = policy_env_info.obs_height // 2
        self._obs_wr = policy_env_info.obs_width // 2

    def initial_agent_state(self) -> MyAgentState:
        """Return initial state for this agent."""
        map_size = 200
        center = map_size // 2
        return MyAgentState(
            agent_id=self._agent_id,
            map_height=map_size,
            map_width=map_size,
            occupancy=[[CellType.FREE.value] * map_size for _ in range(map_size)],
            row=center,
            col=center,
        )

    def step_with_state(
        self, obs: AgentObservation, s: MyAgentState
    ) -> tuple[Action, MyAgentState]:
        """Called every step. Return (action, updated_state)."""
        s.step_count += 1
        s.my_custom_counter += 1

        # Your decision logic here
        action = Action(name="noop")
        return action, s
```

For more complex agents, you can extend `BaselineAgentPolicyImpl` and override specific methods:

```python
from .baseline_agent import BaselineAgentPolicyImpl
from .types import BaselineHyperparameters

class MyAgentPolicyImpl(BaselineAgentPolicyImpl):
    def __init__(self, policy_env_info, agent_id, hyperparams=None):
        super().__init__(policy_env_info, agent_id, hyperparams or BaselineHyperparameters())

    def _update_phase(self, s):
        """Override to customize phase transitions."""
        # Add custom logic before or after parent
        super()._update_phase(s)

    def _execute_phase(self, s):
        """Override to add custom phase behavior."""
        if s.phase == Phase.GATHER:
            # Custom gather behavior
            pass
        return super()._execute_phase(s)
```

### Step 4: Create the MultiAgentPolicy wrapper

This is the top-level class that the framework instantiates. It must:

- Subclass `MultiAgentPolicy`
- Define `short_names` (a list of strings for registry auto-discovery)
- Implement `agent_policy(agent_id)` to return per-agent policies

```python
class MyPolicy(MultiAgentPolicy):
    short_names = ["my_agent"]  # <-- This registers the agent

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu"):
        super().__init__(policy_env_info, device=device)
        self._agent_policies: dict[int, StatefulAgentPolicy[MyAgentState]] = {}

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[MyAgentState]:
        if agent_id not in self._agent_policies:
            self._agent_policies[agent_id] = StatefulAgentPolicy(
                MyAgentPolicyImpl(self._policy_env_info, agent_id),
                self._policy_env_info,
                agent_id=agent_id,
            )
        return self._agent_policies[agent_id]
```

### Step 5: Place the file

Put `my_agent.py` in:

```
cogames-agents/src/cogames_agents/policy/scripted_agent/my_agent.py
```

No imports or `__init__.py` changes needed. The registry discovers agents automatically.

## 3. Registry and Auto-Discovery

The registry (`scripted_registry.py`) auto-discovers agents by scanning all `.py` files in `scripted_agent/` and
`nim_agents/` directories. It uses AST parsing to find classes with a `short_names` class attribute.

### How it works

1. `_iter_policy_files()` recursively scans `scripted_agent/` and `nim_agents/` for `.py` files
2. For each file, it parses the AST (no imports, no execution)
3. It finds class definitions with a `short_names = [...]` attribute
4. Extracts the literal string values from the list
5. Builds a dict mapping `name -> "metta://policy/<name>"`

### Requirements for auto-discovery

Your `short_names` must be a **literal list of strings** assigned directly in the class body:

```python
# Works - literal list assignment
class MyPolicy(MultiAgentPolicy):
    short_names = ["my_agent", "my_alias"]

# Works - literal tuple assignment
class MyPolicy(MultiAgentPolicy):
    short_names = ("my_agent",)

# Does NOT work - computed value
class MyPolicy(MultiAgentPolicy):
    short_names = get_names()  # AST parser can't evaluate this

# Does NOT work - inherited only
class MyPolicy(BasePolicy):
    pass  # No short_names found in this class body
```

### Verifying registration

After creating your agent, verify it appears in the registry:

```bash
python -c "from cogames_agents.policy.scripted_registry import list_scripted_agent_names; print(list_scripted_agent_names())"
```

Your agent name should appear in the output tuple.

## 4. URI System and Parameters

Every registered agent gets a URI of the form:

```
metta://policy/<short_name>
```

URI parameters are passed as query strings and forwarded to your `MultiAgentPolicy.__init__` as keyword arguments:

```
metta://policy/my_agent?param1=value1&param2=value2
```

### Example: role-count parameters

The CogsGuard agent uses URI parameters to control role distribution:

```
metta://policy/role?miner=3&scout=2&aligner=2&scrambler=3
```

To support URI parameters, accept `**kwargs` in your `__init__`:

```python
class MyPolicy(MultiAgentPolicy):
    short_names = ["my_agent"]

    def __init__(self, policy_env_info, device="cpu", **kwargs):
        super().__init__(policy_env_info, device=device)
        self._difficulty = kwargs.get("difficulty", "normal")
        self._speed = int(kwargs.get("speed", "1"))
```

## 5. The Phase State Machine

Most agents use a phase-based state machine defined in `types.py`:

```python
class Phase(Enum):
    GATHER = "gather"          # Collect resources from extractors
    ASSEMBLE = "assemble"      # Craft hearts at hub
    DELIVER = "deliver"        # Deposit hearts to chest
    RECHARGE = "recharge"      # Restore energy at junction
    CRAFT_UNCLIP = "craft_unclip"  # Craft unclip items (UnclippingAgent)
    UNCLIP = "unclip"          # Restore clipped extractors (UnclippingAgent)
```

### Phase transition logic (BaselineAgent)

The `_update_phase` method runs every step and sets the agent's phase based on priority:

```
Priority 1: RECHARGE  — energy < recharge_threshold_low
Priority 2: DELIVER   — have hearts to deposit
Priority 3: ASSEMBLE  — have all recipe resources
Priority 4: GATHER    — default, collect resources
```

### Phase execution

The `_execute_phase` method dispatches to phase-specific handlers:

```
GATHER   -> _do_gather()    — find extractors, navigate, use them
ASSEMBLE -> _do_assemble()  — find hub, navigate, use it
DELIVER  -> _do_deliver()   — find chest, navigate, use it
RECHARGE -> _do_recharge()  — find junction, navigate, use it
```

### Adding custom phases

To add new phases, extend the `Phase` enum in your state and override both methods:

```python
from .types import Phase

# Option 1: Use existing Phase values with custom logic
class MyPolicyImpl(BaselineAgentPolicyImpl):
    def _update_phase(self, s):
        # Add custom priority check before standard logic
        if self._should_do_custom_thing(s):
            s.phase = Phase.GATHER  # Reuse an existing phase
            return
        super()._update_phase(s)

# Option 2: Use the CRAFT_UNCLIP/UNCLIP phases for new behavior
class MyPolicyImpl(BaselineAgentPolicyImpl):
    def _execute_phase(self, s):
        if s.phase == Phase.CRAFT_UNCLIP:
            return self._do_my_custom_behavior(s)
        return super()._execute_phase(s)
```

## 6. Roles and Vibes

The vibe system is used by team-play agents (CogsGuard, nlanky) to control agent behavior through in-game visual state.

### What are vibes?

A "vibe" is a string that the agent sends to the game engine via a `change_vibe` action. It determines:

- **Visual appearance** in replays (glyph shown above agent)
- **Protocol selection** at hubs (different vibes activate different recipes)
- **Role identity** for team coordination

### Common vibes

| Vibe                                               | Purpose                                                    |
| -------------------------------------------------- | ---------------------------------------------------------- |
| `default`                                          | Neutral state; used for heart delivery (chest interaction) |
| `heart_a`                                          | Heart assembly vibe                                        |
| `carbon_a`, `oxygen_a`, `germanium_a`, `silicon_a` | Resource-specific vibes                                    |
| `gear`                                             | Crafting/unclipping vibe                                   |
| `miner`, `scout`, `aligner`, `scrambler`           | Role-specific vibes (CogsGuard)                            |

### Changing vibes

Use the `change_vibe_action` helper:

```python
from .utils import change_vibe_action

# In your step_with_state:
if s.current_glyph != desired_vibe:
    s.current_glyph = desired_vibe
    action = change_vibe_action(desired_vibe, action_names=self._action_names)
    return action, s
```

Vibe changes consume a step (you can't move AND change vibe in the same step).

### Role assignment patterns

CogsGuard assigns roles through the `gear` vibe → role coordinator → role vibe flow:

1. Agent starts with `default` or `gear` vibe
2. Coordinator selects a role for the agent
3. Agent changes vibe to role name (`miner`, `scout`, etc.)
4. Agent acquires gear at role-specific station
5. Agent executes role behavior

## 7. Testing Your Agent

### Using `cogames play`

The primary way to test scripted agents:

```bash
# Basic single-agent test
uv run cogames play --mission evals.diagnostic_radial -p my_agent --cogs 1 --steps 1000

# Multi-agent test
uv run cogames play --mission evals.diagnostic_radial -p my_agent --cogs 4 --steps 2000

# With URI parameters
uv run cogames play --mission evals.diagnostic_radial -p "my_agent?speed=2" --cogs 1

# With replay recording
uv run cogames play --mission evals.diagnostic_radial -p my_agent --cogs 1 --steps 1000 --replay
```

### Useful diagnostic missions

| Mission                                   | Description                               |
| ----------------------------------------- | ----------------------------------------- |
| `evals.diagnostic_radial`                 | Standard single/multi-agent baseline test |
| `evals.diagnostic_radial_hard`            | Harder variant (more steps needed)        |
| `evals.diagnostic_chest_navigation1`      | Tests navigation to chest                 |
| `evals.diagnostic_extract_missing_oxygen` | Tests resource extraction                 |
| `evals.diagnostic_assemble_seeded_search` | Tests assembly workflow                   |

### CogsGuard missions

```bash
# Play with role-based agent
uv run cogames play --mission machina_1 -p role

# With custom role distribution
uv run cogames play --mission machina_1 \
    -p "role?miner=3&scout=2&aligner=2&scrambler=3"
```

### Running the evaluation suite

```bash
# Full evaluation across all diagnostic missions
uv run cogames diagnose my_agent -S diagnostic_evals
```

## 8. Code Examples from Existing Agents

### Minimal agent (DemoPolicy)

`demo_policy.py` is the simplest complete example. Key patterns:

- **No pathfinding** — uses greedy step-towards and random walks
- **No persistent map** — only uses current observation
- **Recipe discovery** — learns heart recipe from hub observation
- **Simple priority**: deliver hearts > assemble > gather > wander

```python
# Core decision loop from DemoPolicy.step_with_state():

# Learn recipe if visible
if s.heart_recipe is None:
    for _pos, obj in parsed.nearby_objects.items():
        if obj.name == "hub" and obj.protocol_outputs.get("heart", 0) > 0:
            s.heart_recipe = {k: v for k, v in obj.protocol_inputs.items() if k != "energy"}

# Deliver hearts
if s.hearts > 0:
    chest = self._closest(s, parsed, lambda o: is_station(o.name.lower(), "chest"))
    if chest:
        if self._adjacent(s, chest):
            return use_object_at(s, chest), s
        return self._step_towards(s, chest, parsed), s

# Assemble if have all resources
if can_assemble:
    hub = self._closest(s, parsed, lambda o: is_station(o.name.lower(), "hub"))
    ...

# Gather needed resources from nearest extractor
needed = [(pos, obj, r) for pos, obj, r in extractors if r and deficits[r] > 0]
if needed:
    pos, obj, r = min(needed, key=lambda x: manhattan((s.row, s.col), x[0]))
    ...

# Wander
return self._random_step(s, parsed), s
```

### Full baseline (BaselinePolicy)

`baseline_agent.py` adds robust infrastructure on top of the demo pattern:

- **Persistent occupancy map** — remembers walls, stations, extractors across steps
- **BFS pathfinding** — `_move_towards()` with path caching
- **Explore-until pattern** — `_explore_until(condition)` explores until a condition is met
- **Stuck detection** — detects oscillation loops and escapes
- **Phase state machine** — `_update_phase()` / `_execute_phase()` separation

### Extension pattern (UnclippingPolicy)

`unclipping_agent.py` shows how to extend `BaselineAgentPolicyImpl`:

- **Extended state** — `UnclippingAgentState` adds unclip-specific fields
- **Overridden `_update_phase`** — inserts CRAFT_UNCLIP/UNCLIP priorities
- **Overridden `_execute_phase`** — adds `_do_craft_unclip()` and `_do_unclip()` handlers
- **Overridden `_find_any_needed_extractor`** — triggers unclip workflow when all extractors are clipped
- **Overridden `step_with_state`** — adds recipe discovery pass after base step

### Team agent (CogsGuard)

`cogsguard/policy.py` shows the most complex pattern:

- **Shared coordinator** — `SmartRoleCoordinator` is shared across all agent instances
- **Vibe-driven roles** — agents change behavior based on their vibe string
- **Gear acquisition** — agents visit role stations to acquire gear before executing role
- **Per-role behaviors** — separate classes for miner, scout, aligner, scrambler

## Quick Reference: Complete Minimal Agent

```python
"""my_agent.py — Complete minimal scripted agent."""
from __future__ import annotations

import random
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

from .types import SimpleAgentState, CellType


class MyAgentImpl(StatefulPolicyImpl[SimpleAgentState]):
    def __init__(self, policy_env_info: PolicyEnvInterface, agent_id: int):
        self._agent_id = agent_id
        self._policy_env_info = policy_env_info

    def initial_agent_state(self) -> SimpleAgentState:
        size = 200
        return SimpleAgentState(
            agent_id=self._agent_id,
            map_height=size,
            map_width=size,
            occupancy=[[CellType.FREE.value] * size for _ in range(size)],
            row=size // 2,
            col=size // 2,
        )

    def step_with_state(
        self, obs: AgentObservation, s: SimpleAgentState
    ) -> tuple[Action, SimpleAgentState]:
        s.step_count += 1
        direction = random.choice(["north", "south", "east", "west"])
        return Action(name=f"move_{direction}"), s


class MyPolicy(MultiAgentPolicy):
    short_names = ["my_agent"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu"):
        super().__init__(policy_env_info, device=device)
        self._agents: dict[int, StatefulAgentPolicy] = {}

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy:
        if agent_id not in self._agents:
            self._agents[agent_id] = StatefulAgentPolicy(
                MyAgentImpl(self._policy_env_info, agent_id),
                self._policy_env_info,
                agent_id=agent_id,
            )
        return self._agents[agent_id]
```

Test it:

```bash
uv run cogames play --mission evals.diagnostic_radial -p my_agent --cogs 1 --steps 500
```
