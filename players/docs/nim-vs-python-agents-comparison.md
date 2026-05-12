# Nim vs Python Scripted Agent Implementations Comparison

**Date:** 2026-01-26 **Author:** Polecat brotherhood **Issue:** mt-nim-agents

## Executive Summary

Both Nim and Python implementations exist for the CogsGuard scripted agents. The Nim version provides a
performance-optimized implementation, while the Python version offers more features and sophisticated behavior. They are
**not behaviorally equivalent** - the Python implementation is significantly more advanced.

## Comparison Table

| Agent                 | Python | Nim     | Parity  | Notes                                                                                                    |
| --------------------- | ------ | ------- | ------- | -------------------------------------------------------------------------------------------------------- |
| **miner**             | ✓ Full | ✓ Basic | Partial | Python has HP-awareness, retry logic, safe extractor selection; Nim is a simpler gather/deposit loop     |
| **scout**             | ✓ Full | ✓ Basic | Partial | Python has frontier-based BFS + patrol; Nim uses spiral unseen search + direction-based exploration      |
| **aligner**           | ✓ Full | ✓ Basic | Partial | Python adds influence gating, retry logic, per-junction cooldown; Nim handles hearts + chest acquisition |
| **scrambler**         | ✓ Full | ✓ Basic | Partial | Python adds retry logic; Nim handles hearts + chest acquisition                                          |
| **role (multi-role)** | ✓ Full | ✓ Basic | Partial | Python has a smart-role coordinator + phase machine; Nim uses simple smart-role heuristics + vibes       |
| **teacher**           | ✓ Full | ✗ None  | None    | Python-only wrapper that delegates to Nim and forces initial vibes                                       |

## File Locations

### Python Implementations

- **Main policy**: `cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/policy.py`
- **Miner**: `cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/miner.py`
- **Scout**: `cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/scout.py`
- **Aligner**: `cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/aligner.py`
- **Scrambler**: `cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/scrambler.py`
- **Role wrappers**: `cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/roles.py`
- **Teacher**: `cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/teacher.py`

### Nim Implementations

- **Main agent code**: `cogames-agents/src/cogames_agents/policy/nim_agents/cogsguard_agents.nim`
- **Common utilities**: `cogames-agents/src/cogames_agents/policy/nim_agents/common.nim`
- **Python wrapper**: `cogames-agents/src/cogames_agents/policy/nim_agents/agents.py`

## Feature Comparison Details

### Miner Agent

| Feature                                    | Python | Nim |
| ------------------------------------------ | ------ | --- |
| Basic gather/deposit loop                  | ✓      | ✓   |
| Gear acquisition                           | ✓      | ✓   |
| HP-aware mining (return for healing)       | ✓      | ✗   |
| Safe extractor selection (avoid enemy AOE) | ✓      | ✗   |
| Action retry on failure                    | ✓      | ✗   |
| Gear re-acquisition on loss                | ✓      | ✓   |
| Extractor depletion tracking               | ✓      | ✓   |
| Corner-directed exploration                | ✓      | ✗   |

**Python LOC**: ~570 **Nim LOC**: ~14 (actMiner function)

### Scout Agent

| Feature                        | Python | Nim |
| ------------------------------ | ------ | --- |
| Basic exploration              | ✓      | ✓   |
| Gear acquisition               | ✓      | ✓   |
| Frontier-based BFS exploration | ✓      | ✗   |
| Systematic patrol fallback     | ✓      | ✗   |
| Unseen cell tracking           | ✓      | ✓   |

**Python LOC**: ~70 **Nim LOC**: ~9 (actScout function)

### Aligner Agent

| Feature                        | Python | Nim |
| ------------------------------ | ------ | --- |
| Align neutral junctions        | ✓      | ✓   |
| Gear acquisition               | ✓      | ✓   |
| Heart requirement check        | ✓      | ✓   |
| Influence requirement check    | ✓      | ✗   |
| Heart acquisition from chest   | ✓      | ✓   |
| Action retry on failure        | ✓      | ✗   |
| Cooldown tracking per junction | ✓      | ✗   |

**Python LOC**: ~330 **Nim LOC**: ~13 (actAligner function)

### Scrambler Agent

| Feature                            | Python | Nim |
| ---------------------------------- | ------ | --- |
| Scramble enemy junctions           | ✓      | ✓   |
| Gear acquisition                   | ✓      | ✓   |
| Heart requirement check            | ✓      | ✓   |
| Heart acquisition from chest       | ✓      | ✓   |
| Action retry on failure            | ✓      | ✗   |
| Prioritize clips-aligned junctions | ✓      | ✓   |

**Python LOC**: ~350 **Nim LOC**: ~13 (actScrambler function)

### CogsGuard Main Policy

| Feature                   | Python | Nim |
| ------------------------- | ------ | --- |
| Vibe-based role switching | ✓      | ✓   |
| Smart role coordinator    | ✓      | ✓   |
| Phase-based state machine | ✓      | ✗   |
| Detailed state tracking   | ✓      | ✓   |
| A\* pathfinding           | ✓      | ✓   |
| Map/occupancy tracking    | ✓      | ✓   |
| Structure discovery       | ✓      | ✓   |

**Note:** Nim's smart-role logic is a lightweight heuristic (hub/chest/heart/influence gated) rather than the full
Python `SmartRoleCoordinator` implementation.

## Which Version is Used by Default?

Current policy URI behavior:

1. **`metta://policy/role`** - Uses **Python** implementation (`CogsguardPolicy`)
2. **`metta://policy/role_nim`** - Uses **Nim** implementation (`CogsguardAgentsMultiPolicy`)
3. **`metta://policy/teacher`** - Uses **Nim** implementation via `CogsguardAgentsMultiPolicy` wrapped by Python teacher
4. **`metta://policy/miner`**, **`scout`**, **`aligner`**, **`scrambler`** - Uses **Python** role-specific
   implementations

**Short name registry:**

```
role          -> Python (CogsguardPolicy)
role_nim      -> Nim (CogsguardAgentsMultiPolicy)
wombo         -> Python (CogsguardWomboPolicy)
cogsguard_control  -> Python (CogsguardControlAgent)
cogsguard_targeted -> Python (CogsguardTargetedAgent)
cogsguard_v2       -> Python (CogsguardV2Agent)
teacher       -> Python wrapper over Nim
miner         -> Python (MinerPolicy)
scout         -> Python (ScoutPolicy)
aligner       -> Python (AlignerPolicy)
scrambler     -> Python (ScramblerPolicy)
```

## Test Coverage

Tests exist for both versions:

- `recipes/tests/test_cogsguard.py` - Integration tests
- `packages/cogames/tests/test_scripted_policies.py` - Policy tests
- `cogames-agents/tests/test_cogsguard_roles.py` - Role-specific tests

## Key Differences

### Architecture

**Python:**

- Uses a `StatefulPolicyImpl` pattern with rich `CogsguardAgentState`
- Phase-based state machine (GET_GEAR, EXECUTE_ROLE)
- Separate implementation classes per role (MinerAgentPolicyImpl, etc.)
- SmartRoleCoordinator for multi-agent coordination
- Detailed debug logging support

**Nim:**

- Simpler procedural approach
- Single `CogsguardAgent` struct with all state
- Role selection via a small heuristic when in the `gear` vibe, then vibe-based switch for role execution
- Direct function calls for each role behavior

### Performance

The Nim implementation is designed for performance:

- Uses raw pointer math for observation parsing
- Minimal memory allocations
- Compiled to native code via Nim's C backend

The Python implementation prioritizes behavior sophistication:

- Rich state tracking
- Detailed error handling and retry logic
- More intelligent decision making

## Recommendations

1. **For Training (BC/RL)**: Use the **Nim** implementation via `CogsguardAgentsMultiPolicy` or the teacher wrapper -
   it's faster and the simpler behaviors may be easier to learn.

2. **For Evaluation/Testing**: Consider the **Python** implementation - its more sophisticated behavior may achieve
   better scores.

3. **Feature Development**: Add to the **Python** implementation first - it has better debug support and is easier to
   extend.

4. **Performance Critical Paths**: The **Nim** implementation can handle higher agent counts more efficiently.

## Issues Found

1. **No Nim teacher**: The teacher policy exists only in Python, though it delegates to Nim for the actual agent
   behavior.

2. **Behavioral divergence**: The two implementations will produce different behaviors in the same situations, which
   could affect training reproducibility.
