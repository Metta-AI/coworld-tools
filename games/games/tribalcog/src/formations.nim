## Formation system for coordinated fighter movement and positioning.
## Enables groups of fighters to maintain spatial relationships during movement.
##
## Formation types:
##   - Line: Units arranged in a horizontal or vertical line
##   - Box: Units arranged in a rectangular perimeter
##   - Wedge: V-shaped formation (reserved for future)
##   - Scatter: No formation constraint (default)

import vmath
import types

type
  FormationType* = enum
    FormationNone = 0     ## No formation (scatter/default)
    FormationLine = 1     ## Line formation (horizontal or vertical)
    FormationBox = 2      ## Box formation (rectangular perimeter)
    FormationWedge = 3    ## Wedge/V-shape (reserved)
    FormationScatter = 4  ## Explicit scatter
    FormationStaggered = 5 ## Staggered/checkerboard formation (offset rows)
    FormationRangedSpread = 6 ## Wide spread for ranged units - avoids friendly fire

  FormationState* = object
    formationType*: FormationType
    active*: bool
    ## Rotation in 45-degree increments (0=East, 1=NE, 2=North, etc.)
    ## Maps to Orientation enum values
    rotation*: int

const
  FormationSpacing* = 2       ## Tiles between units in formation
  MaxFormationSize* = 20      ## Max units in a single formation

## Per-control-group formation state
var groupFormations*: array[ControlGroupCount, FormationState]

## Per-group position cache to avoid recomputing per-agent
type
  FormationPosCache = object
    center: IVec2
    size: int
    ftype: FormationType
    rotation: int
    positions: array[MaxFormationSize, IVec2]
    posCount: int

var formationPosCache: array[ControlGroupCount, FormationPosCache]

proc clearFormation*(groupIndex: int) =
  ## Clear formation for a control group, returning to scatter behavior.
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    groupFormations[groupIndex] = FormationState(
      formationType: FormationNone,
      active: false,
      rotation: 0
    )

proc setFormation*(groupIndex: int, formationType: FormationType) =
  ## Set formation type for a control group.
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return
  if formationType == FormationNone or formationType == FormationScatter:
    clearFormation(groupIndex)
    return
  groupFormations[groupIndex] = FormationState(
    formationType: formationType,
    active: true,
    rotation: 0
  )

proc getFormation*(groupIndex: int): FormationType =
  ## Get formation type for a control group.
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    return groupFormations[groupIndex].formationType
  FormationNone

proc setFormationRotation*(groupIndex: int, rotation: int) =
  ## Set formation rotation (0-7 for 8 directions).
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    groupFormations[groupIndex].rotation = rotation mod 8

proc getFormationRotation*(groupIndex: int): int =
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    return groupFormations[groupIndex].rotation
  0

proc isFormationActive*(groupIndex: int): bool =
  if groupIndex >= 0 and groupIndex < ControlGroupCount:
    return groupFormations[groupIndex].active
  false

# --- Position Calculation ---

proc calcLinePositions*(center: IVec2, unitCount: int, rotation: int): seq[IVec2] =
  ## Calculate positions for line formation around a center point.
  ## rotation: 0=horizontal (E-W), 2=vertical (N-S), 1/3=diagonal
  ## Uses proper centering so formations are symmetric around the center.
  result = newSeq[IVec2](unitCount)
  if unitCount == 0:
    return

  # Direction vector based on rotation
  let dir = case rotation
    of 0: ivec2(1, 0)       # East-West line
    of 1: ivec2(1, -1)      # NE-SW diagonal
    of 2: ivec2(0, -1)      # North-South line
    of 3: ivec2(-1, -1)     # NW-SE diagonal
    of 4: ivec2(-1, 0)      # Same as 0 (reversed)
    of 5: ivec2(-1, 1)      # Same as 1 (reversed)
    of 6: ivec2(0, 1)       # Same as 2 (reversed)
    of 7: ivec2(1, 1)       # Same as 3 (reversed)
    else: ivec2(1, 0)

  # Place units centered on the center point using proper symmetric centering
  # For n units, total span is (n-1)*spacing, so half-span is (n-1)*spacing/2
  # Each unit i gets offset: (i - (n-1)/2) * spacing
  # Using integer math: offset = (2*i - (n-1)) * spacing / 2
  for i in 0 ..< unitCount:
    let offsetX2 = (2 * i - (unitCount - 1)) * FormationSpacing  # 2x the offset
    result[i] = ivec2(
      center.x + dir.x * (offsetX2 div 2).int32,
      center.y + dir.y * (offsetX2 div 2).int32
    )

proc calcBoxPositions*(center: IVec2, unitCount: int, rotation: int): seq[IVec2] =
  ## Calculate positions for box formation around a center point.
  ## Units are placed on the perimeter of a rectangle.
  result = newSeq[IVec2](unitCount)
  if unitCount == 0:
    return
  if unitCount == 1:
    result[0] = center
    return

  # Determine box dimensions based on unit count
  # Try to make a roughly square box
  let sideLen = max(1, (unitCount + 3) div 4)  # Units per side
  let halfW = (sideLen * FormationSpacing) div 2
  let halfH = halfW

  # Generate perimeter positions (clockwise from top-left)
  var perimeterPositions: seq[IVec2] = @[]

  # Top edge (left to right)
  for i in 0 ..< sideLen:
    let x = -halfW + i * FormationSpacing
    perimeterPositions.add(ivec2(center.x + x.int32, center.y - halfH.int32))

  # Right edge (top to bottom)
  for i in 1 ..< sideLen:
    let y = -halfH + i * FormationSpacing
    perimeterPositions.add(ivec2(center.x + halfW.int32, center.y + y.int32))

  # Bottom edge (right to left)
  for i in countdown(sideLen - 1, 0):
    let x = -halfW + i * FormationSpacing
    perimeterPositions.add(ivec2(center.x + x.int32, center.y + halfH.int32))

  # Left edge (bottom to top)
  for i in countdown(sideLen - 2, 1):
    let y = -halfH + i * FormationSpacing
    perimeterPositions.add(ivec2(center.x - halfW.int32, center.y + y.int32))

  # Apply rotation to all positions around center
  # For tile-based grids, we use discrete rotations that map to valid positions.
  # Cardinal rotations (0, 2, 4, 6) = 0, 90, 180, 270 degrees - exact
  # Diagonal rotations (1, 3, 5, 7) use approximate 45-degree steps that
  # preserve the general shape while snapping to the integer grid.
  if rotation != 0:
    for i in 0 ..< perimeterPositions.len:
      let dx = perimeterPositions[i].x - center.x
      let dy = perimeterPositions[i].y - center.y
      case rotation
      of 2: # 90 degrees CCW
        perimeterPositions[i] = ivec2(center.x + dy, center.y - dx)
      of 4: # 180 degrees
        perimeterPositions[i] = ivec2(center.x - dx, center.y - dy)
      of 6: # 270 degrees CCW (90 CW)
        perimeterPositions[i] = ivec2(center.x - dy, center.y + dx)
      of 1: # 45 degrees - rotate by averaging cardinal neighbors
        # For diagonal rotation, we use: new_x = (dx - dy) * 0.707, new_y = (dx + dy) * 0.707
        # Approximating with integer math: multiply then divide to preserve scale
        let newDx = (dx - dy + 1) div 2 + (dx - dy) div 2  # Better rounding
        let newDy = (dx + dy + 1) div 2 + (dx + dy) div 2
        perimeterPositions[i] = ivec2(center.x + (newDx div 2).int32, center.y + (newDy div 2).int32)
      of 3: # 135 degrees
        let newDx = (-dx - dy + 1) div 2 + (-dx - dy) div 2
        let newDy = (dx - dy + 1) div 2 + (dx - dy) div 2
        perimeterPositions[i] = ivec2(center.x + (newDx div 2).int32, center.y + (newDy div 2).int32)
      of 5: # 225 degrees
        let newDx = (-dx + dy + 1) div 2 + (-dx + dy) div 2
        let newDy = (-dx - dy + 1) div 2 + (-dx - dy) div 2
        perimeterPositions[i] = ivec2(center.x + (newDx div 2).int32, center.y + (newDy div 2).int32)
      of 7: # 315 degrees
        let newDx = (dx + dy + 1) div 2 + (dx + dy) div 2
        let newDy = (-dx + dy + 1) div 2 + (-dx + dy) div 2
        perimeterPositions[i] = ivec2(center.x + (newDx div 2).int32, center.y + (newDy div 2).int32)
      else: discard

  # Assign units to perimeter positions (wrapping if more positions than units)
  for i in 0 ..< unitCount:
    if i < perimeterPositions.len:
      result[i] = perimeterPositions[i]
    else:
      # Extra units go toward center
      let innerOffset = i - perimeterPositions.len + 1
      result[i] = ivec2(
        center.x + ((innerOffset mod 3) - 1).int32,
        center.y + ((innerOffset div 3) - 1).int32
      )

proc calcStaggeredPositions*(center: IVec2, unitCount: int, rotation: int): seq[IVec2] =
  ## Calculate positions for staggered/checkerboard formation around a center point.
  ## Units are arranged in a grid where every other row is offset by half the spacing.
  ## rotation: 0=horizontal rows, 2=vertical columns
  result = newSeq[IVec2](unitCount)
  if unitCount == 0:
    return
  if unitCount == 1:
    result[0] = center
    return

  # Calculate grid dimensions - try to make roughly square
  let cols = max(1, (unitCount.float32.sqrt + 0.5).int)
  let rows = (unitCount + cols - 1) div cols

  # Direction vectors based on rotation
  let (rowDir, colDir) = case rotation
    of 0: (ivec2(0, 1), ivec2(1, 0))      # Horizontal rows (standard)
    of 1: (ivec2(1, 1), ivec2(1, -1))     # Diagonal NE
    of 2: (ivec2(1, 0), ivec2(0, 1))      # Vertical columns
    of 3: (ivec2(1, -1), ivec2(-1, -1))   # Diagonal SE
    of 4: (ivec2(0, -1), ivec2(-1, 0))    # Reversed horizontal
    of 5: (ivec2(-1, -1), ivec2(-1, 1))   # Diagonal SW
    of 6: (ivec2(-1, 0), ivec2(0, -1))    # Reversed vertical
    of 7: (ivec2(-1, 1), ivec2(1, 1))     # Diagonal NW
    else: (ivec2(0, 1), ivec2(1, 0))

  # Calculate offsets to center the formation
  let halfRows = (rows - 1) * FormationSpacing div 2
  let halfCols = (cols - 1) * FormationSpacing div 2

  var idx = 0
  for row in 0 ..< rows:
    # Stagger offset: every other row is shifted by half spacing
    let staggerOffset = if row mod 2 == 1: FormationSpacing div 2 else: 0
    for col in 0 ..< cols:
      if idx >= unitCount:
        break
      let rowOffset = row * FormationSpacing - halfRows
      let colOffset = col * FormationSpacing - halfCols + staggerOffset
      result[idx] = ivec2(
        center.x + colDir.x * colOffset.int32 + rowDir.x * rowOffset.int32,
        center.y + colDir.y * colOffset.int32 + rowDir.y * rowOffset.int32
      )
      inc idx

proc calcRangedSpreadPositions*(center: IVec2, unitCount: int, rotation: int): seq[IVec2] =
  ## Calculate positions for ranged unit formation optimized for avoiding friendly fire.
  ## Units are arranged in staggered rows with wider spacing (RangedFormationSpacing = 3)
  ## and offset between rows so archers don't shoot through each other.
  ## rotation: 0=facing East (line runs N-S), 2=facing North (line runs E-W)
  result = newSeq[IVec2](unitCount)
  if unitCount == 0:
    return
  if unitCount == 1:
    result[0] = center
    return

  # Use wider spacing for ranged units
  let spacing = RangedFormationSpacing
  let rowOffset = RangedFormationRowOffset

  # Calculate grid dimensions - prefer wide lines for maximum firing arc
  # More units per row than regular formations
  let cols = max(1, min(unitCount, (unitCount + 1) div 2 + 1))
  let rows = (unitCount + cols - 1) div cols

  # Direction vectors based on rotation
  # Row direction is perpendicular to facing, col direction is backward from facing
  let (rowDir, colDir) = case rotation
    of 0: (ivec2(0, 1), ivec2(-1, 0))      # Facing East: line runs N-S, depth goes West
    of 1: (ivec2(1, 1), ivec2(-1, 1))      # Facing NE: diagonal
    of 2: (ivec2(1, 0), ivec2(0, 1))       # Facing North: line runs E-W, depth goes South
    of 3: (ivec2(1, -1), ivec2(1, 1))      # Facing NW: diagonal
    of 4: (ivec2(0, -1), ivec2(1, 0))      # Facing West: line runs N-S, depth goes East
    of 5: (ivec2(-1, -1), ivec2(1, -1))    # Facing SW: diagonal
    of 6: (ivec2(-1, 0), ivec2(0, -1))     # Facing South: line runs E-W, depth goes North
    of 7: (ivec2(-1, 1), ivec2(-1, -1))    # Facing SE: diagonal
    else: (ivec2(0, 1), ivec2(-1, 0))

  # Calculate offsets to center the formation
  let halfCols = (cols - 1) * spacing div 2
  let halfRows = (rows - 1) * rowOffset div 2

  var idx = 0
  for row in 0 ..< rows:
    # Stagger offset: every other row shifts by half spacing for line of sight
    # This ensures back row archers can fire between front row archers
    let staggerOffset = if row mod 2 == 1: spacing div 2 else: 0
    for col in 0 ..< cols:
      if idx >= unitCount:
        break
      let colOffset = col * spacing - halfCols + staggerOffset
      let rowDepth = row * rowOffset - halfRows
      result[idx] = ivec2(
        center.x + rowDir.x * colOffset.int32 + colDir.x * rowDepth.int32,
        center.y + rowDir.y * colOffset.int32 + colDir.y * rowDepth.int32
      )
      inc idx

proc calcFormationPositions*(center: IVec2, unitCount: int,
                              formationType: FormationType,
                              rotation: int = 0): seq[IVec2] =
  ## Calculate positions for any formation type.
  case formationType
  of FormationLine:
    calcLinePositions(center, unitCount, rotation)
  of FormationBox:
    calcBoxPositions(center, unitCount, rotation)
  of FormationStaggered:
    calcStaggeredPositions(center, unitCount, rotation)
  of FormationRangedSpread:
    calcRangedSpreadPositions(center, unitCount, rotation)
  of FormationNone, FormationScatter, FormationWedge:
    # No formation - return empty (units use their own movement)
    newSeq[IVec2](0)

proc getFormationTargetForAgent*(groupIndex: int, agentIndex: int,
                                  groupCenter: IVec2,
                                  groupSize: int): IVec2 =
  ## Get the formation target position for a specific agent within a control group.
  ## agentIndex: the index of the agent within the control group (0-based).
  ## groupCenter: the center point of the formation (e.g., average position or move target).
  ## groupSize: total number of units in the group.
  ## Returns (-1, -1) if no formation is active or index is out of bounds.
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return ivec2(-1, -1)
  if not groupFormations[groupIndex].active:
    return ivec2(-1, -1)
  if agentIndex < 0 or agentIndex >= groupSize:
    return ivec2(-1, -1)

  let ftype = groupFormations[groupIndex].formationType
  let rotation = groupFormations[groupIndex].rotation

  # Check cache - within a step, all agents in the same group call with identical params
  var cache = addr formationPosCache[groupIndex]
  if cache.center != groupCenter or cache.size != groupSize or
     cache.ftype != ftype or cache.rotation != rotation:
    # Cache miss - recompute and store
    let positions = calcFormationPositions(groupCenter, groupSize, ftype, rotation)
    cache.center = groupCenter
    cache.size = groupSize
    cache.ftype = ftype
    cache.rotation = rotation
    cache.posCount = min(positions.len, MaxFormationSize)
    for i in 0 ..< cache.posCount:
      cache.positions[i] = positions[i]

  if agentIndex < cache.posCount:
    # Clamp to valid map positions
    let pos = cache.positions[agentIndex]
    return ivec2(
      max(0'i32, min(MapWidth.int32 - 1, pos.x)),
      max(0'i32, min(MapHeight.int32 - 1, pos.y))
    )
  ivec2(-1, -1)

proc findAgentControlGroup*(agentId: int): int =
  ## Find which control group an agent belongs to.
  ## Returns -1 if not in any group.
  for g in 0 ..< ControlGroupCount:
    for thing in controlGroups[g]:
      if not thing.isNil and thing.agentId == agentId:
        return g
  -1

proc calcGroupCenter*(groupIndex: int, env: Environment): IVec2 =
  ## Calculate the center position of a control group (average of alive members).
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return ivec2(-1, -1)
  var sumX, sumY, count: int32 = 0
  for thing in controlGroups[groupIndex]:
    if not thing.isNil and isAgentAlive(env, thing):
      sumX += thing.pos.x
      sumY += thing.pos.y
      inc count
  if count == 0:
    return ivec2(-1, -1)
  ivec2(sumX div count, sumY div count)

proc aliveGroupSize*(groupIndex: int, env: Environment): int =
  ## Count alive units in a control group.
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return 0
  for thing in controlGroups[groupIndex]:
    if not thing.isNil and isAgentAlive(env, thing):
      inc result

proc agentIndexInGroup*(groupIndex: int, agentId: int, env: Environment): int =
  ## Get the index of an agent within its control group (only counting alive members).
  ## Returns -1 if not found.
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return -1
  var idx = 0
  for thing in controlGroups[groupIndex]:
    if not thing.isNil and isAgentAlive(env, thing):
      if thing.agentId == agentId:
        return idx
      inc idx
  -1

proc resetAllFormations*() =
  ## Reset all formation state (called on environment reset).
  for g in 0 ..< ControlGroupCount:
    groupFormations[g] = FormationState()

proc countRangedUnitsInGroup*(groupIndex: int, env: Environment): int =
  ## Count how many ranged units are in a control group.
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return 0
  for thing in controlGroups[groupIndex]:
    if not thing.isNil and isAgentAlive(env, thing):
      if thing.unitClass in RangedUnitClasses:
        inc result

proc isGroupMostlyRanged*(groupIndex: int, env: Environment): bool =
  ## Returns true if more than half the alive units in a control group are ranged.
  ## Used to determine if ranged spread formation should be automatically applied.
  let total = aliveGroupSize(groupIndex, env)
  if total < 2:
    return false
  let rangedCount = countRangedUnitsInGroup(groupIndex, env)
  rangedCount * 2 > total  # More than 50% are ranged

proc getRecommendedFormation*(groupIndex: int, env: Environment): FormationType =
  ## Get the recommended formation type for a control group based on unit composition.
  ## - Mostly ranged units: FormationRangedSpread (wider spacing, staggered rows)
  ## - Mixed/melee units: FormationLine (default tight formation)
  if isGroupMostlyRanged(groupIndex, env):
    FormationRangedSpread
  else:
    FormationLine

proc setFormationAuto*(groupIndex: int, env: Environment) =
  ## Automatically set the best formation for a control group based on unit composition.
  ## Ranged units get spread formation to avoid friendly fire; melee units get line formation.
  if groupIndex < 0 or groupIndex >= ControlGroupCount:
    return
  let recommended = getRecommendedFormation(groupIndex, env)
  setFormation(groupIndex, recommended)
