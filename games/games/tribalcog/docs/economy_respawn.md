# Economy, Stockpiles, and Respawning

Date: 2026-02-17
Owner: Docs / Systems
Status: Reviewed

## Overview
The economy is split into **agent inventory** and **team stockpiles**. Agents gather and
craft locally, then deposit or trade into stockpiles via buildings. Altars store hearts
and drive respawning.

Key files:
- `src/items.nim` (item kinds and inventory helpers)
- `src/constants.nim` (game balance constants: HP, damage, costs, capacities)
- `src/environment.nim` (inventory/stockpile helpers, market trading)
- `src/step.nim` (use/craft/market/respawn logic)
- `src/registry.nim` (building use/craft/train definitions)
- `src/types.nim` (type definitions, map constants)

## Inventory vs Stockpile
**Inventory**:
- Per-agent table keyed by `ItemKey`.
- Capacity: `MapObjectAgentMaxInventory` (5) per non-stockpile item.

**Stockpile resources**:
- Food, wood, stone, gold, water.
- Carried capacity limited by `ResourceCarryCapacity` (5 total across these items).
- `giveItem` enforces these limits; `grantItem` bypasses some checks for special cases.

## Resource Nodes
Common resource nodes are Things with inventory counts:
- Tree -> wood
- Wheat -> wheat (becomes stubble)
- Stone / Gold -> mined with larger deposits (`MineDepositAmount`)
- Fish, plants, meat (from animals)

Nodes typically decrement their stored count and remove themselves at zero.

## Crafting and Production
Crafting is done via `use` on specific buildings (when off cooldown):
- **Magma**: smelt gold into bars.
- **Clay Oven**: bread from wheat.
- **Weaving Loom**: lantern/cloth from wheat or wood.
- **Blacksmith**: spears/armor.

Buildings can also serve as storage and dropoff points.

## Market (Trade)
Markets use AoE2-style dynamic pricing for resource trading:

**Pricing mechanics:**
- Base price: `MarketBasePrice` (100 gold per 100 resources)
- Price floor: `MarketMinPrice` (20)
- Price ceiling: `MarketMaxPrice` (300)
- Each buy increases price by `MarketBuyPriceIncrease` (3)
- Each sell decreases price by `MarketSellPriceDecrease` (3)
- Prices drift toward base at `MarketPriceDecayInterval` (50 steps)

**Resources tradeable:**
- Food, wood, stone can be bought/sold for gold
- Water is not traded
- Market cooldown: `DefaultMarketCooldown` (2 steps)

Trading is per-agent inventory; the market adds resources directly to team stockpiles and
then clears or reduces carried inventory. Prices are tracked per-team to allow economic
differentiation.

## Trade Cogs (Dock-to-Dock Trading)
- **Trade Cog** units travel between Docks to generate gold.
- Gold generation is proportional to the distance between the origin and destination Docks.
- Trade Cogs follow pre-computed water routes and are vulnerable to naval attack.

## Biome Resource Bonuses
Different biomes provide **gathering bonuses** (20% chance for +1 item) for specific resources:
- **Forest**: +20% wood
- **Plains**: +20% food (wheat)
- **Caves**: +20% stone
- **Snow**: +20% gold
- **Desert** (oasis effect): +10% all resources when gathering near water (within 3 tiles)

## Altars and Hearts
Altars are team-owned buildings that store **hearts**:
- Using a bar at an altar increments hearts (cooldown applies).
- Hearts are used for respawns and temple hybrid spawns.
- Altars are capturable: attacking reduces hearts; when hearts reach 0 the altar switches
  teams, and doors from the old team flip to the new team.

Constants:
- `MapObjectAltarInitialHearts`
- `MapObjectAltarRespawnCost` (currently 0 by default)

## Population Cap
Each step computes team pop-cap from buildings (`buildingPopCap`):
- Houses contribute `HousePopCap` (4) each.
- Town centers contribute `TownCenterPopCap` (currently 5).
- Cap is clamped to `MapAgentsPerTeam` (125).

Pop-cap gates:
- Respawns
- Monk conversion (cannot convert if target team is at cap)
- Temple hybrid spawns

## Respawning
During each step, dead agents with a home altar can respawn if:
- Their team is below pop-cap.
- Their altar exists and has enough hearts.
- An empty tile exists near the altar.

Respawn clears inventory and resets the unit to villager class.

## Temple Hybrid Spawns
Temples can spawn a new villager when:
- Two adjacent living teammates stand near a temple.
- The team has a dormant agent slot.
- The home altar has enough hearts.

The temple then goes on cooldown (25 steps).

## Common Gotchas (from recent sessions)
- Pop-cap silently blocks conversions/respawns; it is recalculated each step.
- Market only trades **stockpile** items; other items stay in inventory.
- Respawn heart cost is currently zero by default, so hearts are not consumed unless
  the constant is raised.

## See Also
- `docs/population_and_housing.md`
- `docs/temple_hybridization.md`
