# Test Suite Documentation

Date: 2026-02-09
Owner: Engineering / QA
Status: Active

This document describes the test organization, naming conventions, and guidelines for the Tribal Village test suite.

## Test Categories

The test suite uses two primary prefixes to distinguish test scope:

### `behavior_*` - Behavioral/Integration Tests

**Purpose**: Verify that game systems work correctly when all components interact over multiple simulation steps.

**Characteristics**:
- Run multi-step game simulations (100-500+ steps)
- Use full AI controllers or scripted multi-action sequences
- Test emergent behavior from combined system interactions
- Verify observable game outcomes (resources accumulated, units survived, damage dealt)
- Use suite names with "Behavior:" prefix

**Test Harness**: Uses `test_common.nim` which provides:
- `setupGameWithAI(seed)` - Creates environment with AI controller
- `runGameSteps(env, steps)` - Runs N simulation steps
- `initBrutalAI(seed)` - Initializes deterministic AI for testing

**When to use**: When testing that multiple game systems work together correctly over time.

**Examples**:
```nim
# behavior_economy.nim
suite "Behavioral Economy - Resource Gathering":
  test "gatherers accumulate food/wood/gold/stone over 200 steps":
    let env = setupGameWithAI(DefaultTestSeed)
    runGameSteps(env, 200)
    # Verify resources were accumulated
```

```nim
# behavior_garrison.nim
suite "Behavior: Garrison Attack":
  test "garrison attack damage includes building bonus arrows":
    # Compare damage with/without garrison using multi-step scenarios
```

### `domain_*` - Domain/Unit Tests

**Purpose**: Verify that specific modules, functions, or game rules work correctly in isolation.

**Characteristics**:
- Test individual functions or single-step mechanics
- Use minimal environment setup (`makeEmptyEnv()`)
- Test specific domain logic without full simulation
- Verify module-level correctness
- Use suite names describing the domain area (no "Behavior:" prefix)

**Test Harness**: Uses `test_utils.nim` directly which provides:
- `makeEmptyEnv()` - Creates minimal environment
- `addAgentAt()`, `addBuilding()` - Entity creation helpers
- `setStockpile()`, `setInv()` - State manipulation
- `stepAction()`, `stepNoop()` - Single-step execution

**When to use**: When testing a specific function, calculation, or isolated game rule.

**Examples**:
```nim
# domain_economy.nim
suite "Economy - Resource Snapshots":
  test "recordSnapshot stores resource levels":
    resetEconomy()
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 100)
    recordSnapshot(0, env)
    check teamEconomy[0].snapshots[0].food == 100
```

```nim
# domain_formations.nim
suite "Formation - Line Formation":
  test "line formation maintains spacing":
    let positions = calcLinePositions(ivec2(50, 50), 4, 0)
    check positions.len == 4
    # Direct function testing, no simulation
```

## Naming Conventions

### File Naming

| Prefix | Use Case | Example |
|--------|----------|---------|
| `behavior_` | Multi-step integration tests | `behavior_combat.nim` |
| `domain_` | Unit tests for specific modules | `domain_economy.nim` |
| `integration_` | Cross-system integration tests | `integration_behaviors.nim` |
| `fuzz_` | Randomized stress testing | `fuzz_seeds.nim` |
| `test_` | Utility tests or specialized tests | `test_map_determinism.nim` |

### Suite Naming

- **Behavior tests**: Use "Behavior: {Area}" prefix
  - `suite "Behavior: Garrison Entry":`
  - `suite "Behavioral Economy - Resource Gathering":`

- **Domain tests**: Use "{Module} - {Feature}" or just "{Feature}"
  - `suite "Economy - Resource Snapshots":`
  - `suite "Formation - Line Formation":`
  - `suite "Town Center Garrison":`

### Test Naming

Use descriptive names that state the expected behavior:
- "villager can garrison in own town center" (capability)
- "enemy villager cannot garrison in opponent TC" (constraint)
- "garrisoned units preserve HP while inside" (behavior)
- "calculateFlowRate returns zero with insufficient snapshots" (edge case)

## Decision Guide: behavior_* vs domain_*

| Question | behavior_* | domain_* |
|----------|-----------|----------|
| Does it need multiple simulation steps? | Yes | No |
| Does it test AI decision-making? | Yes | No |
| Does it test system interactions? | Yes | No |
| Does it test a specific function? | No | Yes |
| Does it test game rule calculations? | No | Yes |
| Does it test state transitions? | Sometimes | Yes |
| Does it need `setupGameWithAI()`? | Yes | No |
| Does it only need `makeEmptyEnv()`? | No | Yes |

## Common Anti-Patterns

### 1. Behavioral tests in domain_* files

**Problem**: Multi-step simulations placed in `domain_*` files.

**Solution**: Move to corresponding `behavior_*` file or rename file.

### 2. Unit tests in behavior_* files

**Problem**: Simple function tests that don't need simulation placed in `behavior_*` files.

**Solution**: Move to corresponding `domain_*` file or create one if needed.

### 3. Duplicate coverage

**Problem**: Same mechanic tested identically in both behavior_* and domain_* files.

**Solution**:
- Keep unit tests in domain_* for isolated logic
- Keep integration tests in behavior_* for system interactions
- Avoid duplicating the same assertions in both

### 4. Missing edge case coverage

**Problem**: Only testing success cases, not failure paths.

**Solution**: Add negative test cases:
```nim
test "enemy unit cannot garrison in opponent building":
  # Verify the rejection path
```

## Test File Inventory

| Category | Count | Pattern |
|----------|-------|---------|
| Behavior Tests | 25+ | `behavior_*.nim` |
| Domain Tests | 17+ | `domain_*.nim` |
| Integration | 1 | `integration_behaviors.nim` |
| Fuzz/Stress | 1 | `fuzz_seeds.nim` |
| Harness/Utils | 3 | `*_harness.nim`, `test_*.nim` |

For a complete file inventory, see the Test File Inventory appendix in `TEST_AUDIT_REPORT.md`.

## Related Documentation

- `TEST_AUDIT_REPORT.md` - Test suite audit findings and recommendations
- `quickstart.md` - How to run tests
