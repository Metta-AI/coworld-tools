## Arena allocator for per-step temporary allocations.
##
## Provides bump allocation that resets each step, avoiding repeated heap
## allocations for temporary sequences. Uses pre-allocated seq buffers that
## preserve capacity across resets.

import types

const
  ArenaIntsCap = 256
  ArenaStringsCap = 64

proc initArena*(): Arena =
  ## Initialize the arena with pre-allocated buffers.
  result = Arena(
    things1: newSeqOfCap[Thing](ArenaDefaultCap),
    things2: newSeqOfCap[Thing](ArenaDefaultCap div 2),
    things3: newSeqOfCap[Thing](ArenaDefaultCap div 4),
    things4: newSeqOfCap[Thing](ArenaDefaultCap div 4),
    positions1: newSeqOfCap[IVec2](ArenaDefaultCap),
    positions2: newSeqOfCap[IVec2](ArenaDefaultCap div 2),
    ints1: newSeqOfCap[int](ArenaIntsCap),
    ints2: newSeqOfCap[int](ArenaIntsCap),
    itemCounts: newSeqOfCap[tuple[key: ItemKey, count: int]](MapObjectAgentMaxInventory),
    strings: newSeqOfCap[string](ArenaStringsCap),
  )

proc reset*(arena: var Arena) {.inline.} =
  ## Reset all arena buffers for a new step.
  ## Uses setLen(0) to preserve capacity while clearing contents.
  arena.things1.setLen(0)
  arena.things2.setLen(0)
  arena.things3.setLen(0)
  arena.things4.setLen(0)
  arena.positions1.setLen(0)
  arena.positions2.setLen(0)
  arena.ints1.setLen(0)
  arena.ints2.setLen(0)
  arena.itemCounts.setLen(0)
  arena.strings.setLen(0)
