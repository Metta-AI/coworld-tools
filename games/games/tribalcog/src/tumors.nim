## Tumor growth, branching, and contact damage helpers for step.nim.

proc isBlockedByShield(
  env: Environment,
  agent: Thing,
  tumorPos: IVec2
): bool =
  ## Return whether the agent's active shield blocks the tumor position.
  if env.shieldCountdown[agent.agentId] <= 0:
    return false

  let
    direction = orientationToVec(agent.orientation)
    perpendicular =
      if direction.x != 0:
        ivec2(0, 1)
      else:
        ivec2(1, 0)
    forward = agent.pos + direction
  for offset in -1 .. 1:
    let shieldPos =
      forward + ivec2(perpendicular.x * offset, perpendicular.y * offset)
    if shieldPos == tumorPos:
      return true
  false

proc stepProcessTumors(
  env: Environment,
  tumorsToProcess: seq[Thing],
  newTumorsToSpawn: seq[Thing],
  stepRng: var Rand
) =
  ## Process tumor branching and insert new tumors into the environment.
  ## This handles both spawner-created tumors and branch tumors.
  ## Only one `TumorProcessStagger` bucket is checked each step.
  var
    newTumorBranches = addr env.arena.things3
    tumorIdx = 0
  let
    staggerBucket = env.currentStep mod TumorProcessStagger
    totalTumors = tumorsToProcess.len + newTumorsToSpawn.len
    branchingAllowed = totalTumors < MaxGlobalTumors
  newTumorBranches[].setLen(0)

  for tumor in tumorsToProcess:
    if env.getThing(tumor.pos) != tumor:
      continue
    tumor.turnsAlive += 1

    let inBucket = (tumorIdx mod TumorProcessStagger) == staggerBucket
    tumorIdx += 1
    if not inBucket or
      not branchingAllowed or
      tumor.turnsAlive < TumorBranchMinAge or
      randFloat(stepRng) >= TumorBranchChance:
        continue

    var
      branchPos = ivec2(-1, -1)
      branchCount = 0
    for offset in TumorBranchOffsets:
      let candidate = tumor.pos + offset
      if not env.isValidEmptyPosition(candidate):
        continue

      var adjacentTumor = false
      for adj in CardinalOffsets:
        let checkPos = candidate + adj
        if not isValidPos(checkPos):
          continue
        let occupant = env.getThing(checkPos)
        if not occupant.isNil and occupant.kind == Tumor:
          adjacentTumor = true
          break
      if adjacentTumor:
        continue

      inc branchCount
      if randIntExclusive(stepRng, 0, branchCount) == 0:
        branchPos = candidate
    if branchPos.x < 0:
      continue

    let
      newTumor = createTumor(env, branchPos, tumor.homeSpawner, stepRng)
      dx = branchPos.x - tumor.pos.x
      dy = branchPos.y - tumor.pos.y
    var branchOrientation: Orientation
    if abs(dx) >= abs(dy):
      branchOrientation =
        if dx >= 0:
          Orientation.E
        else:
          Orientation.W
    else:
      branchOrientation =
        if dy >= 0:
          Orientation.S
        else:
          Orientation.N

    newTumor.orientation = branchOrientation
    tumor.orientation = branchOrientation
    newTumorBranches[].add(newTumor)
    when defined(tumorAudit):
      recordTumorBranched()
    tumor.hasClaimedTerritory = true
    tumor.turnsAlive = 0

  for newTumor in newTumorsToSpawn:
    env.add(newTumor)
  for newTumor in newTumorBranches[]:
    env.add(newTumor)

proc stepApplyTumorDamage(env: Environment, stepRng: var Rand) =
  ## Resolve lethal tumor contact for adjacent agents and predators.
  ## This iterates agents and predators instead of tumors.
  ## Tumor count can grow unbounded while unit counts stay bounded.
  var
    tumorsToRemove = addr env.arena.things1
    predatorsToRemove = addr env.arena.things2
  tumorsToRemove[].setLen(0)
  predatorsToRemove[].setLen(0)

  for agent in env.thingsByKind[Agent]:
    if not isAgentAlive(env, agent):
      continue
    for offset in CardinalOffsets:
      let adjPos = agent.pos + offset
      if not isValidPos(adjPos):
        continue
      let tumor = env.getThing(adjPos)
      if tumor.isNil or tumor.kind != Tumor:
        continue
      if tumor in tumorsToRemove[]:
        continue
      if env.isBlockedByShield(agent, tumor.pos):
        continue
      if randFloat(stepRng) < TumorAdjacencyDeathChance:
        let killed = env.applyAgentDamage(agent, 1)
        when defined(tumorAudit):
          recordTumorDamage(killed)
        if killed:
          tumorsToRemove[].add(tumor)
          env.grid[tumor.pos.x][tumor.pos.y] = nil
          break

  for kind in [Bear, Wolf]:
    for predator in env.thingsByKind[kind]:
      for offset in CardinalOffsets:
        let adjPos = predator.pos + offset
        if not isValidPos(adjPos):
          continue
        let tumor = env.getThing(adjPos)
        if tumor.isNil or tumor.kind != Tumor:
          continue
        if tumor in tumorsToRemove[]:
          continue
        if randFloat(stepRng) < TumorAdjacencyDeathChance:
          when defined(tumorAudit):
            recordTumorPredatorKill()
          if predator notin predatorsToRemove[]:
            predatorsToRemove[].add(predator)
            env.grid[predator.pos.x][predator.pos.y] = nil
          tumorsToRemove[].add(tumor)
          env.grid[tumor.pos.x][tumor.pos.y] = nil
          break

  if tumorsToRemove[].len > 0:
    when defined(tumorAudit):
      for _ in tumorsToRemove[]:
        recordTumorDestroyed()
    for tumor in tumorsToRemove[]:
      removeThing(env, tumor)

  if predatorsToRemove[].len > 0:
    for predator in predatorsToRemove[]:
      removeThing(env, predator)
