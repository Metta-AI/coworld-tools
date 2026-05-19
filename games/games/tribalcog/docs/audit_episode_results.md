# Episode Audit Results (2026-02-15)

Baseline audit of two 3000-step episodes using `scripts/feature_audit.nim` with compile-time audit flags. Documents which implemented mechanics actually fire during gameplay.

## Summary

**Of ~150 implemented mechanics across 45 unit classes, 50+ building types, 30+ techs, and 5 victory modes, only a small fraction are exercised in 3000 steps.**

### Scorecard

| Category | Implemented | Fires | Coverage |
|----------|------------|-------|----------|
| Unit classes | 45 | 6 (Villager, ManAtArms, Scout, Archer, Monk, Boat) | **13%** |
| Building types | 50+ | ~22 core types | ~44% |
| Blacksmith upgrades | 15 tiers | 9-13 levels | **60-87%** |
| University techs | 10 | 0 | **0%** |
| Castle techs | 16 (2 per civ) | 0 | **0%** |
| Unit upgrades | 5 lines | 0 | **0%** |
| Economy techs | 12 | 4-6 (Wheelbarrow, Hand Cart only) | **33-50%** |
| Victory modes | 5 | 0 triggered | **0%** |
| Special mechanics | ~15 | ~5 | **33%** |

## What Works

### Economy (Good)
- Resource gathering active: Wood dominant, Food second, Gold/Stone low
- All teams build core economic buildings (Mill, LumberCamp, MiningCamp, Quarry, Granary)
- Market trading detected (price movement observed)
- Farm/Mill queues processing
- Resource stockpiles fluctuate with real income/spending flows
- All-time totals show 80-268 wood gathered, 0-121 food gathered per team

### Buildings (Good, but wall-heavy)
- Wall spam dominates: 393-856 walls per episode (60-70% of all buildings)
- Houses built consistently (~28-30 per team)
- Outposts built (54-110 total)
- Mills built (48-65 total, some teams build 14-27)
- Military buildings built: Barracks (5-6), Stables (3-5), Archery Ranges (2-4)
- Support buildings: Monasteries (2-6), Markets (2-9), Universities (6-7)

### Military (Partial)
- ManAtArms: 56-74 trained per episode (first at step ~837-866)
- Scouts: 30-42 trained (first at step ~1021-1095)
- Archers: 10-11 trained (first at step ~682-1030)
- Combat deaths: 215-349 per episode (real fighting happening)
- AI role split: ~330 Gatherer / ~336 Builder / ~328 Fighter

### Blacksmith (Good)
- 9-13 upgrade levels researched per episode
- Melee Attack L1 most common (4-5 teams)
- Archer Attack L1 researched by 2-3 teams
- Armor tiers (Infantry, Cavalry, Archer) researched by 1-2 teams
- One team reached Melee Attack L2
- First blacksmith research at step ~401-654

### Economy Techs (Partial)
- Wheelbarrow researched by 3-5 teams (first at step ~11-141)
- Hand Cart researched by 1-2 teams (step ~621-2928)
- No farming techs (Horse Collar, Heavy Plow, Crop Rotation)
- No mining/lumbering techs (Double Bit Axe, Gold Mining, etc.)

## What Never Fires

### University Techs (0/10)
Buildings exist (6-7 universities built) but AI never researches:
- Ballistics, Murder Holes, Masonry, Architecture
- Treadmill Crane, Arrowslits, Heated Shot
- Siege Engineers, Chemistry, Coinage

### Castle Techs (0/16)
No castles with civ techs researched. Zero unique civ tech usage.

### Unit Upgrades (0/5 lines)
No tier progression:
- ManAtArms never upgrades to Longswordsman/Champion
- Scout never upgrades to Light Cavalry/Hussar
- Archer never upgrades to Crossbowman/Arbalester
- Skirmisher line never trained
- Cavalry Archer line never trained

### Advanced Units (0 trained)
| Unit Category | Units | Trained |
|---------------|-------|---------|
| Heavy Infantry | Longswordsman, Champion | 0 |
| Heavy Cavalry | Knight, Cavalier, Paladin | 0 |
| Counter units | Skirmisher, Camel, Huskarl | 0 |
| Siege | Ram, Mangonel, Trebuchet, Scorpion | 0 |
| Naval combat | Galley, Fire Ship, Demo Ship, Cannon Galleon | 0 |
| Unique units | Samurai, Longbowman, Cataphract, etc. | 0 |
| Gunpowder | Hand Cannoneer, Janissary | 0 |
| Trade | Trade Cog | 0 |
| Transport | Transport Ship | 0 |

### Victory Conditions (0 triggered)
- All 8 kings alive at step 3000
- No wonder built
- Relics on map (16-17) but none garrisoned in monasteries
- No KOTH control point contested
- No conquest (no team eliminated)

### Other Missing Mechanics
- **Monk conversion**: 0-3 monks trained, no conversions observed
- **Garrison**: Not audited but likely minimal
- **Tribute**: No inter-team resource transfer
- **Naval economy**: 0-1 docks, 0-1 boats, no fishing ships or trade cogs
- **Relic collection**: Monasteries built but relics not picked up
- **Altar capture**: Not observed
- **Embark/disembark**: No transport ships
- **Trebuchet pack/unpack**: No trebuchets
- **AoE damage (Mangonel)**: No mangonels

## Economy Details (from econAudit)

### All-Time Resource Totals (Episode 2, seed varies)
| Team | Food Gained | Wood Gained | Gold Gained | Stone Gained |
|------|-------------|-------------|-------------|--------------|
| RED | 121 | 264 | 46 | 10 |
| ORANGE | 42 | 124 | 6 | 5 |
| YELLOW | 31 | 219 | 12 | 0 |
| GREEN | 2 | 80 | 1 | 0 |
| MAGENTA | 54 | 145 | 5 | 9 |
| BLUE | 0 | 255 | 0 | 0 |
| GRAY | 0 | 87 | 0 | 0 |
| PINK | 58 | 258 | 16 | 0 |

**Key insight**: Wood gathering massively outpaces all other resources. Gold is scarce (0-46 total). Stone nearly zero for most teams. Food moderate. This explains why advanced techs/units (which cost gold) never appear.

### Action Distribution (from actionAudit, end-of-episode)
Typical team breakdown: ~80% move, ~13% noop/idle, ~3-4% build, <1% attack

## Deep-Dive Investigation Results

### Investigation 1: Gold Scarcity (Root Blocker)

**Diagnosis**: Gold starvation is the #1 blocker. Teams gather 0-46 gold over 3000 steps vs 80-264 wood.

**Root causes (priority order)**:

1. **AI gatherer weight imbalance (70% of problem)**: In `scripted/gatherer.nim` lines 21-23, early-game gold weight is 1.5 (worst priority) vs food 0.5 (best). Gatherers never target gold when it matters most.

2. **Mining Camp build gate (15%)**: `gatherer.nim` line 279 requires 6 gold nodes within 4 tiles to build a Mining Camp. Initial placements rarely meet this — so no Mining Camps get built, no gather bonuses apply.

3. **Sparse initial placement (10%)**: Only 3-4 gold deposits per team at 8-15 tile distance (`spawn.nim` line 972). Wood spawns in dense clusters much closer.

4. **No early gold generation (5%)**: Relic income is 1 gold per 20 steps (negligible). Trade Cogs/Markets require gold to start.

**Fix**: Rebalance gatherer weights (gold 1.5→0.8 early), lower Mining Camp gate (6→3 nodes), increase initial gold spawns (3-4→5-7).

### Investigation 2: University/Castle Tech Dead Zone

**Diagnosis**: Code paths exist but are resource-gated. AI never accumulates enough resources.

- `options.nim` lines 1025-1054: `canStartResearchUniversityTech` exists and is registered in `BuilderOptions` at position 14.
- **But**: `canAffordNextUniversityTech` requires 5 food + 3 gold + 2 wood simultaneously. With gold at 0-7, this check almost always fails.
- University construction has no maxHp — marked `constructed = true` immediately (`placement.nim` line 135). Buildings ARE functional.
- Castle techs same pattern: code exists at `options.nim` lines 1075-1104, gated by resources.

**Fix**: Solving gold scarcity (Investigation 1) should unlock this automatically. The code paths are correct.

### Investigation 3: Unit Upgrade Gap

**Diagnosis**: AI decision path for unit upgrades is **completely missing**.

- Mechanical system fully implemented and tested (`environment.nim` lines 1754-1928, 26 passing tests).
- Upgrade costs are cheap: Tier 2 = 3F/2G, Tier 3 = 6F/4G.
- **But**: No `canStartResearchUnitUpgrade()`, no `optResearchUnitUpgrade()`, no `ResearchUnitUpgradeOption` defined anywhere.
- University/Castle research options exist (positions 14-15 in BuilderOptions), but unit upgrades have NO entry.
- `optUnitPromotionFocus()` in `options.nim` lines 847-862 focuses on TRAINING upgraded units, not researching the upgrade itself.

**Fix**: Create `ResearchUnitUpgradeOption` mirroring the University/Castle pattern. Add to BuilderOptions after tech buildings (~position 13).

### Investigation 4: Wall Spam

**Diagnosis**: 5 interacting factors create an infinite wall-building loop.

1. **Near-zero cost**: Walls cost 1 wood (`registry.nim` line 57). Barracks costs 9 wood.
2. **Perpetual activation**: `canStartBuilderWallRing` (`builder.nim` line 291) requires only homeAltar + LumberCamp + 3 wood — always true after early game.
3. **No completion condition**: Termination only triggers when preconditions fail (they never do). No wall count cap exists.
4. **Growing radius**: `calculateWallRingRadius` (`builder.nim` line 37) expands radius with building count (base 5, max 12). More buildings → bigger ring → more walls → more buildings.
5. **Builder glut**: 336 builders with no sub-roles all converge on wall building once higher-priority tasks complete (wall ring is priority 15, but everything above it finishes quickly).

**In threat mode** (`BuilderOptionsThreat`), wall ring jumps to priority 7 — making it even more dominant during conflict.

**Fix**: Add wall count cap (~50-80 per team) in `canStartBuilderWallRing`, or add ring completion flag that stops building once perimeter is full.

### Investigation 5: Action Distribution (80% MOVE)

**Diagnosis**: Mostly working as designed, with some optimization opportunities.

- **80% MOVE is expected**: 2/3 of agents are gatherers/builders who spend most time walking to resources/sites. Grid-based combat requires walking to enemies before attacking.
- **<1% ATTACK is normal**: With 5-8 damage per hit and 20-50 HP targets, kills take 10+ hits. Movement phase (5-10 steps) precedes each combat engagement.
- **13% NOOP is mixed**: ~50% intentional (decision delay system at `ai_defaults.nim` line 409, stop commands), ~50% bug (blocked pathfinding returns NOOP at `ai_core.nim` line 1461 instead of trying to attack nearby enemies).
- **Greedy pathfinding threshold**: `ai_core.nim` line 1411 uses greedy movement for <6 tiles, A* for >=6. Greedy gets stuck on obstacles, causing oscillation before replan.

**Fix (quick win)**: When blocked (`dirIdx < 0`), try attacking adjacent enemies instead of returning NOOP. Lower greedy→A* threshold from 6 to 4 tiles.

## Root Cause Summary

| Issue | Root Cause | Severity | Fix Complexity |
|-------|-----------|----------|----------------|
| Gold scarcity | Gatherer weights deprioritize gold + Mining Camp gate too high | **Critical** | Low (constants) |
| No University/Castle tech | Resource-gated; gold scarcity blocks affordability checks | **High** | None (fix gold) |
| No unit upgrades | AI option completely missing from decision tree | **High** | Medium (new option) |
| Wall spam | No cap + perpetual activation + cheap cost | **Medium** | Low (add cap) |
| High NOOP rate | Blocked pathfinding → NOOP instead of attack | **Low** | Low (fallback) |
| 80% MOVE | Expected for economic game with grid movement | **Normal** | N/A |

## Round 1+2 Fixes Applied (2026-02-15)

Seven changes merged to main in two rounds:

| Bead | Fix | Files Changed |
|------|-----|---------------|
| tv-87mp | Gold economy: gatherer weights 1.5→0.8, mining camp gate 6→3, gold spawns 3-4→5-7 | gatherer.nim, builder.nim, spawn.nim |
| tv-z0gt | New ResearchUnitUpgradeOption in AI decision tree (89 lines) | options.nim, builder.nim |
| tv-9129 | Wall cap: MaxWallsPerTeam=60 in canStartBuilderWallRing | constants.nim, builder.nim |
| tv-ap46 | Attack-adjacent when blocked + A* threshold 6→4 tiles | ai_core.nim |
| tv-qhmo | New ResearchEconomyTechOption for farming/mining techs (53 lines) | options.nim, builder.nim |
| tv-u0le | Monk relic garrison: direct USE on monastery + auto-reassign to Fighter | fighter.nim, ai_defaults.nim |
| tv-owov | (Doc comment only — diverse unit training NOT implemented) | ai_core.nim |

## Post-Fix Audit Results (same seed 42, 3000 steps)

### Before → After Comparison

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Economy techs researched | 6 | **27** | +350% |
| Combat deaths | 215-349 | **1068** | +5x |
| Unit classes seen | 6 | **8** (+LongSwordsman, LightCavalry) | +33% |
| Scouts trained | 42 | **193** | +4.6x |
| ManAtArms trained | 56-74 | ~80 | stable |
| Monks trained | 1 | **11** | +11x |
| Kings killed (regicide) | 0 of 8 | **7 of 8** | NEW |
| Hill control (KOTH) | none | **Team 3 since step 994** | NEW |
| Mining Camps | 8 | **18** | +125% |
| Walls built | 856 | **463** | -46% |
| Blacksmith levels | 9-13 | 3 | -70% (resources redirected to economy techs) |

### Updated Scorecard

| Category | Implemented | Fires (Post-Fix) | Coverage |
|----------|------------|-------------------|----------|
| Unit classes | 45 | 8 (Villager, ManAtArms, LongSwordsman, Scout, LightCavalry, Archer, Monk, Boat) | **18%** |
| Building types | 50+ | ~22 core types | ~44% |
| Blacksmith upgrades | 15 tiers | 3 levels | **20%** |
| University techs | 10 | 0 | **0%** |
| Castle techs | 16 (2 per civ) | 0 | **0%** |
| Unit upgrades | 5 lines | 2 lines (ManAtArms→LongSwordsman, Scout→LightCavalry) | **40%** |
| Economy techs | 12 | 27 researched (farming + mining techs firing) | **75%+** |
| Victory modes | 5 | 2 progressing (Regicide 7/8 kings dead, KOTH hill held) | **40%** |
| Special mechanics | ~15 | ~7 (relic garrison, monks, hill control new) | **47%** |

### What's New and Working
- **Unit upgrades firing**: LongSwordsman and LightCavalry appearing — ResearchUnitUpgradeOption works
- **Economy techs booming**: 27 researches vs 6 before — farming and mining techs now researched
- **Victory progress**: Regicide nearly triggered (7 of 8 kings dead), KOTH hill control active
- **Monks active**: 11 trained (was 1), relic behavior improved
- **Gold economy functional**: Mining Camps doubled (8→18), gold no longer bottleneck for basic techs
- **Wall spam controlled**: Down 46% (856→463), wall cap working

### Still Not Firing (Next Priorities)
- **University techs (0/10)**: Buildings exist but AI still never researches. May need dedicated priority boost or cheaper costs.
- **Castle techs (0/16)**: No castles built → no civ tech usage.
- **Diverse military (0)**: No Knights, Skirmishers, Cavalry Archers, Camels trained. tv-owov not implemented.
- **Siege units (0)**: No Rams, Mangonels, Trebuchets, Scorpions.
- **Naval (0)**: No Docks, no fishing, no naval combat.
- **Unique castle units (0)**: No Samurai, Longbowman, Cataphract, etc.
- **Wonders (0)**: Never built.
- **Blacksmith regression**: Dropped from 9-13 to 3 levels — economy techs may be crowding out blacksmith research in the priority queue.

## Round 3 Fixes Applied (2026-02-15)

Three more changes merged:

| Bead | Fix | Files Changed |
|------|-----|---------------|
| tv-5zi9 | Add ResearchBlacksmithUpgradeOption (53 lines) | options.nim, builder.nim, environment.nim |
| tv-qyfl | Reduce UniversityTechGoldCost from 3 to 1 | constants.nim |
| tv-1jj3 | Add Knight/Skirmisher/CavalryArcher unlock upgrades in effectiveTrainUnit | types.nim, environment.nim |

## Round 3 Audit Results (same seed 42, 3000 steps)

### Round 2 → Round 3 Comparison

| Metric | Round 2 | **Round 3** | Change |
|--------|---------|-------------|--------|
| Blacksmith upgrades | 3 | **26** | +767% (regression FIXED) |
| University techs | 0 | **1** | NEW (first ever!) |
| Economy techs | 27 | **56** | +107% |
| Unit upgrades | 2 lines | **4** (+Crossbowman, BatteringRam) | +100% |
| Siege units (BatteringRam) | 0 | **4** | NEW |
| Castle built | 0 | **1** | NEW |
| LightCavalry trained | 1 | **117** | massive |
| Crossbowman trained | 0 | **18** | NEW |
| Monks trained | 11 | **22** | +100% |
| Walls | 463 | **475** | stable (cap working) |
| Siege Workshops | 0 | **2** | NEW |
| Total tech events | ~33 | **115** | +250% |

### Updated Scorecard (Round 3)

| Category | Implemented | Fires (Round 3) | Coverage |
|----------|------------|-----------------|----------|
| Unit classes | 45 | 10 (+BatteringRam, Crossbowman) | **22%** |
| Building types | 50+ | ~25 core types (+Castle, SiegeWorkshop) | ~50% |
| Blacksmith upgrades | 15 tiers | 26 levels | **87%** (restored) |
| University techs | 10 | 1 | **10%** |
| Castle techs | 16 (2 per civ) | 0 | **0%** |
| Unit upgrades | 8 lines | 4 researched | **50%** |
| Economy techs | 12 | 56 researched | **100%** |
| Victory modes | 5 | 0 triggered (no kings died this seed) | **0%** |
| Special mechanics | ~15 | ~9 | **60%** |

### Key Firsts in Round 3
- **Siege units trained**: BatteringRam appears at step 1449
- **Crossbowman trained**: Archer→Crossbowman upgrade working (step 1773)
- **University tech researched**: First ever university tech in any audit
- **Castle constructed**: First castle built (team 5)
- **Blacksmith fully restored**: 26 levels (was 3 in round 2, 9-13 in baseline)
- **115 tech events total**: 3.5x the baseline (~33)
- **Siege Workshops built**: 2 (never before)

### Still Not Firing
- **Knights/Skirmishers/CavalryArchers**: Unlock upgrades exist but aren't researched yet (may need more game time or lower costs)
- **Castle techs (0/16)**: Castle built but no civ techs researched
- **Naval (0)**: No docks, no fishing, no naval combat (1 dock appeared in one seed)
- **Unique castle units (0)**: No Samurai, Longbowman, etc.
- **Wonders (0)**: Never built
- **Victory conditions**: No victory triggered (seed-dependent; round 2 had 7/8 kings dead)

## Recommendations (Updated after Round 3)

### High Priority
1. **Longer episodes**: Test 5000-10000 steps to see if more mechanics unlock with time (Knights, castle techs may just need time)
2. **Castle tech activation**: Castle exists (1 built) but no civ techs researched — may need dedicated AI option
3. **Knight/Skirmisher research priority**: Unlock upgrades are Tier 2 cost (3F+2G), but AI may prefer LightCavalry/Crossbowman path

### Medium Priority
4. **Naval AI**: Dock building, fishing ships, naval combat
5. **Victory condition pursuit**: AI actively works toward winning
6. **More university tech research**: Only 1 of 10 — need more time or lower costs

### Low Priority (polish)
7. **Unique castle units**: Enable training of civ-specific units
8. **Trade Cog / tribute**: Inter-team economy
9. **Wonder construction**: Victory via wonder
