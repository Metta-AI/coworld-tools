import std/tables

import common

type
  StateSnapshot* = object
    position*: Location

    carbon*: int
    oxygen*: int
    germanium*: int
    silicon*: int
    heart*: int
    influence*: int
    hp*: int
    energy*: int

    minerGear*: bool
    scoutGear*: bool
    alignerGear*: bool
    scramblerGear*: bool

    vibe*: string

    teamCarbon*: int
    teamOxygen*: int
    teamGermanium*: int
    teamSilicon*: int
    teamHeart*: int
    teamInfluence*: int

  Blackboard* = object
    ints*: Table[string, int]
    bools*: Table[string, bool]
    strs*: Table[string, string]
    locs*: Table[string, Location]

proc newBlackboard*(): Blackboard =
  Blackboard(
    ints: initTable[string, int](),
    bools: initTable[string, bool](),
    strs: initTable[string, string](),
    locs: initTable[string, Location](),
  )

proc cargoTotal*(s: StateSnapshot): int =
  s.carbon + s.oxygen + s.germanium + s.silicon

proc cargoCapacity*(s: StateSnapshot): int =
  if s.minerGear: 40 else: 4
