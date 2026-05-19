# Population Caps and Housing

Date: 2026-02-12
Owner: Design / Systems
Status: Current

## Team and Agent Limits
Core scale constants in `src/types.nim`:
- `MapRoomObjectsTeams = 8`
- `MapAgentsPerTeam = 125`
- Total agent slots = `MapRoomObjectsTeams * MapAgentsPerTeam` (+ goblins)

This means the environment targets ~1000 agents plus a small goblin set.

## Population Cap Formula
Population cap is computed each step in `src/step.nim` by summing building
pop caps per team:
- `buildingPopCap(House) = HousePopCap` (currently 4)
- `buildingPopCap(TownCenter) = TownCenterPopCap` (currently 5)
- Other buildings return 0
- Only **constructed** buildings contribute (see `thing.constructed` in `placement.nim`)

The total is clamped to `MapAgentsPerTeam`, so the effective cap is:

`min(MapAgentsPerTeam, townCenter_count * TownCenterPopCap + house_count * HousePopCap)`

There is no separate hard cap beyond `MapAgentsPerTeam`.

## Where the Cap Is Enforced
Population cap is consulted in the main step loop:
- Agents are prevented from training/spawning if `teamPopCounts >= teamPopCaps`.
- The cap is recomputed every step from the current building list.

## Builder AI: When to Add Houses
The scripted builder logic checks for cap pressure in
`src/scripted/ai_defaults.nim`:
- `needsPopCapHouse` compares current pop count + buffer against the cap.
- When needed, builders try to place `House` near the base position.

## Garrison Capacity
Buildings have garrison capacity (AoE2-style):
- Town Center: `TownCenterGarrisonCapacity` (15)
- Castle: `CastleGarrisonCapacity` (20)
- Guard Tower: `GuardTowerGarrisonCapacity` (5)
- House: `HouseGarrisonCapacity` (5)

Garrisoned units are removed from the map. When a garrisoned building is destroyed,
units are ejected to nearby empty tiles (or killed if no space).

## Town Bell
Buildings have a `townBellActive` flag. When rung, villagers seek nearby garrisonable
buildings for safety. The `GarrisonSeekRadius` (15) determines how far villagers will
search for shelter.

## Practical Notes
- Both Houses and Town Centers contribute to population cap.
- Town Centers provide 5 pop cap each plus training, garrison, and hearth focus.
- Houses provide 4 pop cap each and are the primary scaling mechanism.
- Buildings with no HP requirement (House, Mill, Granary, etc.) are auto-constructed
  on placement. Buildings with HP (Wall, Tower, Castle, etc.) must reach full HP first.
- Tuning `HousePopCap`, `TownCenterPopCap`, or `MapAgentsPerTeam` changes growth dynamics.
