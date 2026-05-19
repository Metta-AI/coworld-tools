# Custom Mutations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace complex GameValue expression chains with 4 custom C++ mutations: CogonyAttackMutation, CogonyRebootMutation, CogonyLootMutation, CogonyHealMutation. Add sys_damage tracking per subsystem.

**Architecture:** C++ mutations in mettagrid, pybind bindings, Python config classes, bridge code, then rewrite combat.py and coherence.py to use them.

---

## Phase 1: C++ mutations + pybind

### Task 1.1: Add config structs

File: `.mettagrid/packages/mettagrid/cpp/include/mettagrid/core/mutation_config.hpp`

Add 4 new config structs to the MutationConfig variant.

### Task 1.2: Add mutation classes

Files (create):
- `.mettagrid/packages/mettagrid/cpp/include/mettagrid/handler/mutations/cogony_attack_mutation.hpp`
- `.mettagrid/packages/mettagrid/cpp/include/mettagrid/handler/mutations/cogony_reboot_mutation.hpp`
- `.mettagrid/packages/mettagrid/cpp/include/mettagrid/handler/mutations/cogony_loot_mutation.hpp`
- `.mettagrid/packages/mettagrid/cpp/include/mettagrid/handler/mutations/cogony_heal_mutation.hpp`

### Task 1.3: Register in mutation factory

File: `.mettagrid/packages/mettagrid/cpp/src/mettagrid/handler/mutations/mutation_factory.cpp`

### Task 1.4: Add pybind bindings

File: `.mettagrid/packages/mettagrid/cpp/include/mettagrid/handler/handler_bindings.hpp`

### Task 1.5: Build and verify

```bash
./scripts/build-mettascope.sh
```

## Phase 2: Python config + bridge

### Task 2.1: Python mutation configs

File (create): `src/cogony/game/mutations.py`

Pydantic models matching the C++ configs.

### Task 2.2: Bridge code

File: `.mettagrid/packages/mettagrid/python/src/mettagrid/config/mettagrid_c_mutations.py`

Add conversion for each new mutation type.

### Task 2.3: Register in AnyMutation

File: `.mettagrid/packages/mettagrid/python/src/mettagrid/config/mutation/__init__.py`

## Phase 3: Rewrite game code

### Task 3.1: Add sys_damage resources

File: `src/cogony/game/extractors.py`

Add `sys_damage_core`, `sys_damage_os`, `sys_damage_gen`, `sys_damage_storage` to extractor inventory.

### Task 3.2: Rewrite combat.py

Replace GameValue expression chains with CogonyAttackMutation + CogonyHealMutation + CogonyLootMutation.

### Task 3.3: Rewrite coherence.py

Replace reboot event mutations with CogonyRebootMutation.

### Task 3.4: Tests + verify

```bash
uv run pytest -q
uv run cogony play --render none --max-steps 5
```
