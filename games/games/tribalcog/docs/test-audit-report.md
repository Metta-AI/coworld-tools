# Test Suite Audit Report

Date: 2026-01-31
Updated: 2026-02-10 (tv-gaalsg - always-true assertions resolved)
Owner: Engineering / QA
Status: Active
Issue: tv-o4qfd
Auditor: polecat/nux

## Executive Summary

The tribal_village test suite contains 97 test files covering various aspects of game behavior, domain logic, and integration scenarios. The tests are generally well-structured but have several coverage gaps, potential flaky tests, and some weak assertions that could mask real failures.

---

## 1. Coverage Gaps

### 1.1 Source Modules Without Direct Test Coverage

The following source modules in `src/` do not have corresponding dedicated test files:

| Module | Lines | Purpose | Risk |
|--------|-------|---------|------|
| `action_audit.nim` | - | Action tracking/debugging | Low |
| `actions.nim` | - | Action encoding/decoding | Medium |
| `combat_audit.nim` | - | Combat analysis | Low |
| `command_panel.nim` | - | UI command panel | Low (UI) |
| `console_viz.nim` | - | Console visualization | Low (Debug) |
| `ffi.nim` | - | Foreign function interface | Medium |
| `gather_heatmap.nim` | - | Resource gathering heatmaps | Low |
| `perf_regression.nim` | - | Performance testing | Low |
| `renderer.nim` | - | Game rendering | Low (UI) |
| `replay_analyzer.nim` | - | Replay analysis | Medium |
| `replay_common.nim` | - | Replay utilities | Medium |
| `replay_writer.nim` | - | Replay file writing | Medium |
| `spatial_index.nim` | - | Spatial indexing | High |
| `state_diff.nim` | - | State comparison | Medium |
| `state_dumper.nim` | - | State serialization | Medium |
| `tileset.nim` | - | Tile graphics | Low (UI) |
| `tint.nim` | - | Color tinting | Low (UI) |
| `tumor_audit.nim` | - | Tumor system analysis | Low |

**Recommendations:**
- **High Priority:** Add unit tests for `spatial_index.nim` - this is likely used for collision detection and pathfinding
- **Medium Priority:** Add tests for `actions.nim` (action encoding is critical), `ffi.nim` (external interface), and replay modules
- **Low Priority:** UI and debug modules can remain without direct tests

### 1.2 Critical Paths Potentially Undertested

Based on analysis of the codebase, these critical paths may need additional coverage:

1. **Market Price Dynamics:** `behavior_trade.nim` tests basic trading but may not cover edge cases like:
   - Price floor/ceiling enforcement
   - Concurrent multi-team trading effects
   - Long-term price recovery

2. **Multi-Building Garrison:** Tests exist for single building garrison but multi-building evacuation/transfer scenarios are sparse

3. **AI Handoff Scenarios:** When AI control switches teams mid-game via Tab key cycling

---

## 2. Flaky Tests

### 2.1 Previously Failing Tests (Now Resolved)

**File:** `tests/behavior_balance.nim`

| Test | Status | Analysis |
|------|--------|----------|
| `no team wins more than 80% of games` | PASSING | Now passing consistently. |
| `all teams have surviving units across seeds` | PASSING | Now passing consistently. |

**Resolution (tv-9i55qe, 2026-02-09):** These tests are now stable. Recent AI improvements
(shouldWaitForAllies, retreatTowardAllies, optGathererFollow, guard commands, multi-waypoint
patrol) and unit additions (Archery Range, Stable cavalry, Dock naval) have improved game
balance, resulting in more even team outcomes across seeds.

**Note:** These tests remain inherently sensitive to AI behavior and game mechanics changes.
Future changes may cause them to fail again - if so, investigate whether the change broke
actual game balance or if thresholds need adjustment.

### 2.2 Tests with Flakiness Risk

**Pattern: Fixed Seeds with Long Simulations**

Tests that rely on specific outcomes from long simulations are inherently fragile:

| File | Test Pattern | Risk |
|------|--------------|------|
| `behavior_ai.nim` | 300-step simulations with seed 42 | Medium |
| `integration_behaviors.nim` | 500-step games with fixed seeds | Medium |
| `fuzz_seeds.nim` | 100 games × 200 steps | High (good for catching crashes, but long runtime) |
| `behavior_balance.nim` | 20 games × 500 steps | High |

**Pattern: Race Conditions**

Tests in `behavior_wonder_race.nim` depend on specific step ordering which could become flaky if step timing changes.

**Pattern: Probabilistic Mechanics**

| File | Issue |
|------|-------|
| `ai_harness.nim:164-194` | Biome bonus tests - run 1000 trials but check only `>= 10` and `<= 500` |
| `behavior_ai.nim:380` | "different seeds produce different outcomes" - doesn't hard-fail on collision |

---

## 3. Poor Assertions

### 3.1 Always-True Assertions (Resolved)

**Resolution (tv-8wi7pj, tv-gaalsg 2026-02-10):** The `or true` patterns have been removed from the
test suite. All assertions now test actual behavior:

| Original | Fixed |
|----------|-------|
| `check anyCombat or true` | Removed - combat tests now use proper outcome verification |
| `check repaired or hpAfter >= hpBefore - 1 or true` | `check repaired or hpAfter >= hpBefore - 1` |
| `check anyProgress or true` | `check anyProgress` |

The tests now provide meaningful regression protection.

### 3.2 Overly Permissive Assertions

```nim
# behavior_economy.nim:83
check totalAt200 > 0 or totalAt100 > 0

# behavior_ai.nim:116
check totalAt100 > 0 or totalAt200 > 0
```

**Issue:** These check that resources were gathered at EITHER checkpoint, not that the economy is functioning properly over time.

### 3.3 Missing Negative Case Testing

Many tests verify success cases but don't test that failures are properly handled:

- Building placement tests verify successful placement but few test that invalid placements are rejected
- Combat tests verify damage is dealt but few verify damage is NOT dealt when it shouldn't be (range, team, etc.)

---

## 4. Test Organization Issues

### 4.1 Duplicate Test Coverage

Some functionality is tested in multiple places with slight variations:
- Monk conversion tested in `behavior_combat.nim`, `behavior_diplomacy.nim`, and `domain_conversion_relics.nim`
- Garrison mechanics in `behavior_garrison.nim` and `domain_garrison.nim`

**Recommendation:** Consolidate or clearly delineate unit vs integration scope.

### 4.2 Test Naming Inconsistency

- `behavior_*` vs `domain_*` distinction is unclear
- Some `domain_*` tests are behavioral, some are unit-level

**Resolution**: See `testing.md` for documented conventions on when to use each category.

---

## 5. Recommendations Summary

### Immediate Actions

1. ~~**Fix or Skip Balance Tests**~~ - RESOLVED (tv-9i55qe, 2026-02-09): Balance tests now passing

2. ~~**Remove Always-True Assertions**~~ - RESOLVED (tv-8wi7pj, tv-gaalsg 2026-02-10): Tests with `or true` removed or tightened

3. **Add spatial_index Tests** - This is a critical module without dedicated tests

### Short-term Improvements

4. **Add Negative Case Testing** - Especially for:
   - Invalid building placement
   - Out-of-range attacks
   - Cross-team action blocking

5. ~~**Document Test Categories**~~ - Complete. See `testing.md` for `behavior_*` vs `domain_*` conventions.

### Long-term Considerations

6. **Consider Property-Based Testing** - For balance-sensitive tests, consider using property-based testing that's more robust to parameter changes

7. **Add Test Coverage Metrics** - Implement a coverage tracking tool to measure test coverage over time

---

## Appendix: Test File Inventory

| Category | Count | Files |
|----------|-------|-------|
| Behavior Tests | 33 | behavior_*.nim |
| Domain Tests | 44 | domain_*.nim |
| Unit/Functional Tests | 8 | test_*.nim (excluding utils) |
| Integration | 1 | integration_behaviors.nim |
| Fuzz/Stress | 3 | fuzz_seeds.nim, stress_*.nim |
| Perf | 1 | perf_actions.nim |
| Harness/Utils | 7 | *_harness.nim, test_utils.nim, test_common.nim, run_all_tests.nim, balance_quick.nim |
| **Total** | **97** | |

---

*Report generated as part of test audit (tv-o4qfd)*
