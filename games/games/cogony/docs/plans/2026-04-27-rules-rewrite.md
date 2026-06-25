# Rules Rewrite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the cogony variant tree and tests to match the new RULES.md (coherence, 4 channels, unified combat, node levels, reboot, gear slots, hub payouts).

**Architecture:** Strip the old variant tree down to structural bones (mission, terrain, teams), then rebuild mechanics bottom-up. Each phase adds one rules-section worth of mechanics and a matching integration test. The game should be playable (headless) after each phase.

**Tech Stack:** Python + mettagrid (CoGameMissionVariant, Deps, handlers, mutations, events, filters, GameValue expressions). Tests via pytest + Simulator.

**Reference:** `/Users/daveey/code/cogame-cogony/RULES.md` — the source of truth. Every decision comes from there.

---

## Phase 0: Strip old systems

### Task 0.1: Delete obsolete variant files

**Files:**
- Delete: `src/cogony/game/roles/aligner.py`
- Delete: `src/cogony/game/roles/miner.py`
- Delete: `src/cogony/game/roles/scout.py`
- Delete: `src/cogony/game/roles/scrambler.py`
- Delete: `src/cogony/game/roles/role.py`
- Delete: `src/cogony/game/security.py`
- Delete: `src/cogony/game/items.py`
- Delete: `src/cogony/game/solar.py`
- Delete: `src/cogony/game/days.py`
- Delete: `src/cogony/game/damage.py`
- Delete: `src/cogony/game/gear.py`
- Delete: `src/cogony/game/multi_team.py`
- Delete: `src/cogony/game/clips/clips.py`
- Delete: `src/cogony/game/clips/ship.py`
- Delete: `src/cogony/game/clips/__init__.py`
- Delete: `src/cogony/game/territory/damage_strangers.py`
- Delete: `src/cogony/game/teams/junction_deposit.py`
- Delete: `src/cogony/game/teams/hub_observations.py`
- Delete: `src/cogony/game/teams/item_stations.py`
- Delete: `tests/rules/test_rule_04_junction_alignment.py`

**Step 1:** Delete all the files listed above.

```bash
rm -f src/cogony/game/roles/aligner.py \
      src/cogony/game/roles/miner.py \
      src/cogony/game/roles/scout.py \
      src/cogony/game/roles/scrambler.py \
      src/cogony/game/roles/role.py \
      src/cogony/game/security.py \
      src/cogony/game/items.py \
      src/cogony/game/solar.py \
      src/cogony/game/days.py \
      src/cogony/game/damage.py \
      src/cogony/game/gear.py \
      src/cogony/game/multi_team.py \
      src/cogony/game/clips/clips.py \
      src/cogony/game/clips/ship.py \
      src/cogony/game/clips/__init__.py \
      src/cogony/game/territory/damage_strangers.py \
      src/cogony/game/teams/junction_deposit.py \
      src/cogony/game/teams/hub_observations.py \
      src/cogony/game/teams/item_stations.py \
      tests/rules/test_rule_04_junction_alignment.py
rmdir src/cogony/game/clips 2>/dev/null || true
rmdir src/cogony/game/roles 2>/dev/null || true
```

**Step 2:** Strip `src/cogony/game/__init__.py` — remove all imports referencing deleted files. Keep only: `elements`, `heart`, `energy`, `cargo`, `creds`, `extractors`, `junction`, `vibes`, and everything under `teams/` and `territory/` that still exists.

**Step 3:** Rewrite `src/cogony/base.py` — strip `BaseVariant.dependencies()` down to only the variants that still exist. Remove all `configure()` and `modify_env()` logic that references deleted variants. The goal is a minimal BaseVariant that compiles.

Required deps for the stripped BaseVariant:
```python
return Deps(required=[
    VibesVariant,
    TeamVariant,
    ElementsVariant,
    HeartVariant,
    EnergyVariant,
    CargoLimitVariant,
    CredsVariant,
    ExtractorsVariant,
    JunctionVariant,
    TeamGearStationsVariant,
    TeamMarketStationsVariant,
    TerritoryVariant,
    HealTeamVariant,
])
```

Remove all imports for deleted variants. Remove `GEAR_COSTS` dict. Remove death-reset handler, heart reward, and any reference to aligner/scrambler/miner/scout/security/damage/items/solar/days/clips.

**Step 4:** Fix `src/cogony/game/teams/cogony.py` — remove references to deleted station types (item_stations, junction_deposit). Update `station_offsets` to only include stations that still exist. Remove NoClipsVariant import.

**Step 5:** Fix `src/cogony/game/teams/gear_stations.py` — temporarily make it a no-op (empty `modify_env`). We'll rewrite it in Phase 5.

**Step 6:** Fix `src/cogony/game/extractors.py` — remove all miner-tier handlers. Simplify to a single extract handler per element type that yields 1 unit on bump. Remove security references. Remove respawn event (we'll re-add in Phase 4).

**Step 7:** Fix `src/cogony/game/teams/junction.py` — strip all the old heal/damage/unalign/claim handlers. Make `modify_env` a minimal pass-through (junction object exists but has no special handlers yet). Remove security imports.

**Step 8:** Fix `src/cogony/game/territory/heal_team.py` — change `hp` references to a temporary resource name (we'll rename properly in Phase 1). Remove energy healing. Keep `+2 hp/tick` for same-team agents.

**Step 9:** Fix `src/cogony/game/teams/market_stations.py` — simplify to sell 10 cargo for 1 cred (fixed ratio, remove old floating-price logic).

**Step 10:** Fix `src/cogony/game/energy.py` — simplify. Remove movement cost (no energy system in new rules). Keep as a minimal variant that adds an `energy` resource with cap=100, initial=50 (needed for compatibility until we add coherence). Or delete entirely and let coherence replace it in Phase 1.

**Step 11:** Run tests to verify the stripped game compiles and runs:

```bash
uv run pytest tests/test_registration.py tests/test_default_play.py -v
```

Expected: both pass (game registers, 10 ticks run without crash).

**Step 12:** Commit.

```bash
git add -A
git commit -m "strip old variant tree to structural bones for rules rewrite"
```

---

## Phase 1: Coherence (RULES.md §1)

### Task 1.1: Add CoherenceVariant

**Files:**
- Create: `src/cogony/game/coherence.py`
- Test: `tests/rules/test_rule_01_coherence.py`

**Step 1: Write the test**

```python
"""Rule 1: coherence is the primary health resource."""
from tests.rules.conftest import build_rule_config, new_simulation


SMALL_MAP = [["#","#","#"],["#","@","#"],["#","#","#"]]


def test_cog_spawns_with_correct_coherence(build_rule_config, new_simulation):
    cfg = build_rule_config(SMALL_MAP)
    sim = new_simulation(cfg, seed=0)
    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a.get("inv:coherence", 0) == 50


def test_coherence_regen_ticks(build_rule_config, new_simulation, step_with_actions):
    """Coherence regens +1 every 10 ticks when 0 < coherence < cap."""
    cfg = build_rule_config(SMALL_MAP)
    sim = new_simulation(cfg, seed=0)
    # Run 10 noop ticks
    for _ in range(10):
        step_with_actions(sim, ["noop"])
    a = next(o for o in sim.grid_objects().values() if o.get("type_name") == "agent")
    assert a.get("inv:coherence", 0) == 51
```

**Step 2:** Run test to verify it fails.

```bash
uv run pytest tests/rules/test_rule_01_coherence.py -v
```

**Step 3: Implement CoherenceVariant**

Create `src/cogony/game/coherence.py`:
- Add `coherence` resource: cap=100, initial=50
- Add periodic regen event: every 10 ticks, +1 coherence for entities with 0 < coherence < cap
- Add `reboot` resource: cap=100, initial=0
- Add on_tick handler: when coherence=0, increment reboot by 1. When reboot >= max_coherence//2, set coherence = max_coherence//2, reboot=0
- Add `heal` resource: cap=100, initial=1
- Add `creds` initial=100 on agents (move from CredsVariant or set here)

Wire into BaseVariant dependencies.

**Step 4:** Run test.

```bash
uv run pytest tests/rules/test_rule_01_coherence.py -v
```

**Step 5:** Commit.

---

## Phase 2: Channels (RULES.md §2)

### Task 2.1: Add ChannelsVariant

**Files:**
- Create: `src/cogony/game/channels.py`
- Test: `tests/rules/test_rule_02_channels.py`

**Step 1: Write the test**

Test that attacking an entity with Dmg stats applies damage across all 4 channels, reduced by Res, and kickback fires.

Use a tiny map with 2 agents. Give attacker Dmg[K]=3 via initial inventory. Give target Res[K]=1, Kick[K]=2. Attack by bumping. Verify:
- Target loses `max(0, 3-1) = 2` coherence (from K channel; other channels 0)
- Attacker loses `max(0, 2-0) = 2` coherence from kickback

**Step 2:** Run test, verify fail.

**Step 3: Implement ChannelsVariant**

Create `src/cogony/game/channels.py`:
- Register 12 channel-stat resources: `dmg_k`, `dmg_t`, `dmg_d`, `dmg_m`, `res_k`, `res_t`, `res_d`, `res_m`, `kick_k`, `kick_t`, `kick_d`, `kick_m`
- All with initial=0, cap=100
- The combat resolution handler will be attached in Phase 3 (bump dispatch)

**Step 4:** Run test, verify pass.

**Step 5:** Commit.

---

## Phase 3: Bumping objects (RULES.md §3)

### Task 3.1: Rewrite bump dispatch and combat resolution

**Files:**
- Create: `src/cogony/game/combat.py`
- Modify: `src/cogony/game/extractors.py`
- Modify: `src/cogony/game/teams/junction.py`
- Modify: `src/cogony/game/vibes.py`
- Test: `tests/rules/test_rule_03_bumping.py`

**Step 1: Write the test**

Test each row of the §3 bump table:
- Bump extractor (coh > 0): attack resolution runs, extractor loses coherence
- Bump extractor (coh = 0): transfer elements to bumper
- Bump junction (coh > 0): attack resolution
- Bump junction (coh = 0): align to team
- Bump same-team cog (coh > 0): heal
- Bump enemy cog (coh > 0): attack
- Bump disabled cog (coh = 0): loot elements + gear

Start with 2-3 of these; add the rest iteratively.

**Step 2:** Run test, verify fail.

**Step 3: Implement CombatVariant**

Create `src/cogony/game/combat.py`:
- Build the attack handler using SumGameValue expressions:
  ```python
  # For each channel C in {k, t, d, m}:
  # damage_C = max(0, actor.dmg_C - target.res_C)
  # kick_C = max(0, target.kick_C - actor.res_C)
  # Apply: target.coherence -= sum(damage_C), actor.coherence -= sum(kick_C)
  ```
- Use `MaxGameValue` and `SumGameValue` to build the per-channel expressions
- Attach as on_use_handler to extractors, junctions, and agents
- Use vibe-based `firstMatch` dispatch:
  - vibe_attack filter → attack handler
  - vibe_heal filter → heal handler (apply `actor.heal` to `target.coherence`)
  - default → per-object-type handler

**Step 4: Rewrite vibes.py**

Reduce vibes to 3: `default`, `attack`, `heal`. Remove all old vibes (heart, gear, scrambler, aligner, miner, scout, battery, wrench).

**Step 5: Rewrite extractors.py**

- Remove old miner-tier handlers
- Extractor on_use_handler: `firstMatch([attack_handler, collect_handler])`
  - attack: filter `targetHas({"coherence": 1})` → combat resolution
  - collect: filter `isNot(targetHas({"coherence": 1}))` → transfer element inventory to actor

**Step 6: Rewrite teams/junction.py**

- Junction on_use_handler: `firstMatch([attack_handler, align_handler])`
  - attack: filter `targetHas({"coherence": 1})` → combat resolution
  - align: filter `isNot(targetHas({"coherence": 1}))` + `actorHasTagPrefix("team:")` → add team tag

**Step 7:** Run tests.

**Step 8:** Commit.

---

## Phase 4: Teams and hubs (RULES.md §4)

### Task 4.1: Rewrite hub with join cost and payouts

**Files:**
- Modify: `src/cogony/game/teams/hub.py`
- Test: `tests/rules/test_rule_04_teams.py`

**Step 1: Write the test**

- Test join cost = 0 when no junctions aligned (free join)
- Test join cost deducted and added to hub inventory
- Test hub payout every 100 ticks distributes creds to members
- Test payout = 10 × aligned_junctions, split equally

**Step 2:** Run test, verify fail.

**Step 3: Implement hub changes**

- Add `creds` to hub inventory (cap=unlimited)
- Join handler: compute `cost = 100 × junctions // max(1, members)` via GameValue expressions. Filter: `actorHas({"creds": cost})`. Mutations: deduct creds from actor, add to hub, add team tag.
- Payout event: `EventConfig(periodic(100, 100))` targeting hubs. Mutation: add `10 × junction_count` creds. Then distribute via QueryInventoryMutation to team members.

**Step 4:** Run tests.

**Step 5:** Commit.

---

## Phase 5: Node levels (RULES.md §5)

### Task 5.1: Add NodeLevelsVariant

**Files:**
- Create: `src/cogony/game/node_levels.py`
- Test: `tests/rules/test_rule_05_node_levels.py`

**Step 1: Write the test**

- Level-1 node: coherence=10, res=1 per channel, kick=0, heal=1
- Level-1 extractor holds 1 unit of its element
- After disable + reboot: level increments to 2, coherence cap=20, inventory=2

**Step 2:** Run test, verify fail.

**Step 3: Implement NodeLevelsVariant**

- Add `level` resource to extractors and junctions (initial=1)
- Set initial stats from level via t=0 event:
  - coherence cap = level × 10
  - res_k = res_t = res_d = res_m = level
  - kick_k = kick_t = kick_d = kick_m = max(0, level - 3)
  - heal = 1
  - element inventory = level (extractors only)
- Reboot event: on restart, level += 1, recompute all stats, refill inventory

**Step 4:** Run tests.

**Step 5:** Commit.

---

## Phase 6: Gear slots (RULES.md §6)

### Task 6.1: Rewrite gear system

**Files:**
- Create: `src/cogony/game/gear_slots.py`
- Modify: `src/cogony/game/teams/gear_stations.py`
- Test: `tests/rules/test_rule_06_gear.py`

**Step 1: Write the test**

- Agent starts with 5 gear slots, 0 stats
- Buying Dmg[K] at gear station costs 10 creds, adds 1 to dmg_k inventory, uses 1 slot
- Can't exceed slot cap

**Step 2:** Run test, verify fail.

**Step 3: Implement GearSlotsVariant**

- Add `gear_slots` resource: cap=5, initial=0 (counts USED slots)
- Add `gear_slots_max` resource: cap=unlimited, initial=5
- Gear station handler: filter `actorHas({"creds": 10})` + slot check. Mutation: deduct 10 creds, add 1 to the stat resource, increment gear_slots.

**Step 4: Rewrite gear_stations.py**

- One station per stat type (13 stations: 4×Dmg + 4×Res + 4×Kick + Heal)
- Plus a slot station that sells +1 gear_slots_max for 10 creds
- All cost 10 creds

**Step 5:** Run tests.

**Step 6:** Commit.

---

## Phase 7: Resources and stations (RULES.md §7)

### Task 7.1: Market and heart stations

**Files:**
- Modify: `src/cogony/game/teams/market_stations.py`
- Create: `src/cogony/game/teams/heart_station.py`
- Test: `tests/rules/test_rule_07_resources.py`

**Step 1: Write the test**

- Market: agent with 10 carbon bumps market → gains 1 cred, loses 10 carbon
- Heart: agent with 100 creds bumps heart station → gains 1 heart, loses 100 creds
- Elements order is COGS (carbon, oxygen, germanium, silicon)

**Step 2:** Run test, verify fail.

**Step 3: Implement**

- Market station: handler with `GameValueFilter(cargo_sum >= 10)`, mutation clears 10 elements, adds 1 cred
- Heart station: handler with `actorHas({"creds": 100})`, mutation deducts 100 creds, adds 1 heart
- Add heart station to compound layout

**Step 4:** Run tests.

**Step 5:** Commit.

---

## Phase 8: Integration and cleanup

### Task 8.1: Wire everything into BaseVariant

**Files:**
- Modify: `src/cogony/base.py`
- Modify: `src/cogony/game/__init__.py`
- Modify: `src/cogony/game/teams/cogony.py`

**Step 1:** Update BaseVariant dependencies to include all new variants.

**Step 2:** Update `game/__init__.py` to export new variants, remove old.

**Step 3:** Update CogonyVariant compound layout with new station types.

**Step 4:** Run full test suite:

```bash
uv run pytest -v
```

**Step 5:** Run headless smoke test:

```bash
uv run cogony play --render none
```

**Step 6:** Commit.

### Task 8.2: Full rules integration test

**Files:**
- Create: `tests/rules/test_full_loop.py`

Write an end-to-end test that exercises the core game loop:
1. Cog spawns with 100 creds, 50 coherence
2. Buys Dmg[K] gear at station
3. Attacks a level-1 extractor (10 coh, 1 res per channel)
4. Collects elements when extractor disabled
5. Sells at market for creds
6. Joins a team
7. Attacks a junction, aligns it
8. Waits for hub payout

This validates the entire economic loop from RULES.md §3.

---

## Summary: variant file mapping

| Old file | Action | New file |
|----------|--------|----------|
| `damage.py` | Delete → replace | `coherence.py` |
| `gear.py` | Delete → replace | `gear_slots.py` |
| `security.py` | Delete | (combat handles kickback) |
| `items.py` | Delete | — |
| `solar.py` | Delete | — |
| `days.py` | Delete | — |
| `clips/*` | Delete | — |
| `roles/*` | Delete | (gear stations sell stats directly) |
| `multi_team.py` | Delete | — |
| `territory/damage_strangers.py` | Delete | — |
| `teams/junction_deposit.py` | Delete | — |
| `teams/hub_observations.py` | Delete | — |
| `teams/item_stations.py` | Delete | — |
| — | Create | `channels.py` |
| — | Create | `combat.py` |
| — | Create | `node_levels.py` |
| — | Create | `teams/heart_station.py` |
| `extractors.py` | Rewrite | (same file) |
| `junction.py` | Rewrite | (same file) |
| `teams/junction.py` | Rewrite | (same file) |
| `teams/hub.py` | Rewrite | (same file) |
| `teams/gear_stations.py` | Rewrite | (same file) |
| `teams/market_stations.py` | Rewrite | (same file) |
| `vibes.py` | Rewrite | (same file) |
| `energy.py` | Delete | (no energy in new rules) |
| `base.py` | Rewrite | (same file) |
| `game/__init__.py` | Rewrite | (same file) |
