# This file is included by src/environment.nim
# std/os is already imported by console_viz.nim (included before this file)
# std/strutils is already imported by environment.nim

when defined(stateDiff):
  import state_diff

# Timing infrastructure, tick helpers, and utility procs
include "step_tick"

let logRenderEnabled = parseEnvBool("TV_LOG_RENDER", false)
let logRenderWindow = max(100, parseEnvInt("TV_LOG_RENDER_WINDOW", 100))
let logRenderEvery = max(1, parseEnvInt("TV_LOG_RENDER_EVERY", 1))
let logRenderPath = parseEnvString("TV_LOG_RENDER_PATH", "tribal_village.log")

var logRenderBuffer: seq[string] = @[]
var logRenderHead = 0
var logRenderCount = 0

include "actions"
include "animal_ai"
include "auras"
include "respawn"

# chebyshevDist and manhattanDist templates are now in common_types.nim

# Action constants and dispatch tables
include "step_actions"

include "step_visuals"

include "building_combat"

# Building predicates (depend on garrisonCapacity from building_combat.nim)
proc isGarrisonableBuilding(k: ThingKind): bool =
  ## Check if a building kind can garrison units.
  garrisonCapacity(k) > 0

proc isTownCenterKind(k: ThingKind): bool =
  ## Check if a building kind is a TownCenter.
  k == TownCenter

# Victory conditions extracted to victory.nim
include "victory"

# Tumor processing extracted to tumors.nim
include "tumors"

# ============================================================================
# Main Step Procedure
# ============================================================================

proc step*(env: Environment, actions: ptr array[MapAgents, uint16]) =
  ## Step the environment forward by one tick.
  ## Processes agent actions, updates all entities, checks victory conditions.
  when defined(stepTiming):
    let perStepTiming = stepTimingTarget >= 0 and env.currentStep >= stepTimingTarget and
      env.currentStep <= stepTimingTarget + stepTimingWindow
    let aggregateTiming = stepTimingInterval > 0
    let timing = perStepTiming or aggregateTiming
    var tStart: MonoTime
    var tNow: MonoTime
    var tTotalStart: MonoTime
    var tActionTintMs: float64
    var tShieldsMs: float64
    var tPreDeathsMs: float64
    var tActionsMs: float64
    var tThingsMs: float64
    var tTumorsMs: float64
    var tTumorDamageMs: float64
    var tAurasMs: float64
    var tPopRespawnMs: float64
    var tSurvivalMs: float64
    var tTintMs: float64
    var tEndMs: float64

    if timing:
      tStart = getMonoTime()
      tTotalStart = tStart

  when defined(perfRegression):
    ensurePerfInit()
    var prfStart = getMonoTime()
    var prfNow: MonoTime
    var prfTotalStart = prfStart
    var prfSubsystems: array[PerfSubsystemCount, float64]

  when defined(flameGraph):
    ensureFlameInit()
    var fgStart = getMonoTime()
    var fgNow: MonoTime
    var fgTotalStart = fgStart
    var fgSubsystems: array[FlameSubsystemCount, int64]

  when defined(combatAudit):
    ensureCombatAuditInit()


  when defined(actionAudit):
    ensureActionAuditInit()

  when defined(actionFreqCounter):
    ensureActionFreqInit()

  when defined(stateDiff):
    capturePreStep(env)

  # Reset arena allocator for this step's temporary allocations
  env.arena.reset()

  # Decay short-lived action tints, projectile visuals, damage numbers, ragdolls, and debris particles
  env.stepDecayActionTints()
  env.stepDecayProjectiles()
  env.stepDecayDamageNumbers()
  env.stepRagdolls()
  env.stepDecayDebris()
  env.stepDecaySpawnEffects()
  env.stepDecayDyingUnits()
  env.stepDecayGatherSparkles()
  env.stepDecayConstructionDust()
  env.stepDecayUnitTrails()
  env.stepDecayDustParticles()
  env.stepDecayWaterRipples()
  env.stepDecayAttackImpacts()
  env.stepDecayConversionEffects()

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tActionTintMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[0] = msBetweenPerfTiming(prfStart, prfNow)  # actionTint
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[0] = usBetween(fgStart, fgNow)  # actionTint
    fgStart = fgNow

  # Decay shields
  env.stepDecayShields()

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tShieldsMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[1] = msBetweenPerfTiming(prfStart, prfNow)  # shields
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[1] = usBetween(fgStart, fgNow)  # shields
    fgStart = fgNow

  # Remove any agents that already hit zero HP so they can't act this step
  env.enforceZeroHpDeaths()

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tPreDeathsMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[2] = msBetweenPerfTiming(prfStart, prfNow)  # preDeaths
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[2] = usBetween(fgStart, fgNow)  # preDeaths
    fgStart = fgNow

  inc env.currentStep

  # AoE2-style market price equilibrium: drift prices toward base rate periodically
  if env.currentStep mod MarketPriceDecayInterval == 0:
    env.decayMarketPrices()

  # Periodically tune spatial index bucket size based on unit density
  when defined(spatialAutoTune):
    env.maybeTuneSpatialIndex(env.currentStep)

  # Single RNG for entire step - XOR gameSeed for variation across different games.
  # Without gameSeed, all games at the same step have identical agent ordering.
  var stepRng = initRand(env.gameSeed xor env.currentStep)

  # Track builders per construction site for multi-builder speed bonus
  # Reuse environment's table to avoid per-step heap allocation
  env.constructionBuilders.clear()

  # Pre-compute team pop caps before action processing (for monk conversion)
  # This avoids O(buildings) iteration inside the action loop
  # Also used later for respawning and production building spawning
  for i in 0 ..< MapRoomObjectsTeams:
    env.stepTeamPopCaps[i] = 0
    env.stepTeamPopCounts[i] = 0
  for thing in env.thingsByKind[TownCenter]:
    if thing.teamId >= 0 and thing.teamId < MapRoomObjectsTeams and thing.constructed:
      env.stepTeamPopCaps[thing.teamId] += TownCenterPopCap
  for thing in env.thingsByKind[House]:
    if thing.teamId >= 0 and thing.teamId < MapRoomObjectsTeams and thing.constructed:
      env.stepTeamPopCaps[thing.teamId] += HousePopCap
  # Clamp to agent pool limit
  for i in 0 ..< MapRoomObjectsTeams:
    if env.stepTeamPopCaps[i] > MapAgentsPerTeam:
      env.stepTeamPopCaps[i] = MapAgentsPerTeam
  for agent in env.agents:
    if not isAgentAlive(env, agent):
      continue
    let teamId = getTeamId(agent)
    if teamId >= 0 and teamId < MapRoomObjectsTeams:
      inc env.stepTeamPopCounts[teamId]

  # -------------------------------------------------------------------------
  # Agent Action Processing
  # Actions are processed in shuffled order to ensure fair team access.
  # Each agent executes one action per step (move, attack, use, build, etc.)
  # -------------------------------------------------------------------------

  # Shuffle agent processing order to prevent Team 0 from always acting first.
  stepRng.shuffle(env.agentOrder)

  for id in env.agentOrder:
    let actionValue = actions[id]
    let agent = env.agents[id]
    if not isAgentAlive(env, agent):
      continue

    let verb = actionValue.int div ActionArgumentCount
    let argument = actionValue.int mod ActionArgumentCount

    # Track idle state: agent is idle if taking NOOP (0) or ORIENT (9) action
    # This enables AoE2-style idle villager detection for RL agents
    agent.isIdle = verb == 0 or verb == 9

    when defined(actionAudit):
      recordAction(id, verb)

    when defined(actionFreqCounter):
      recordActionByUnitType(id, verb, agent.unitClass)

    template invalidAndBreak(label: untyped) =
      inc env.stats[id].actionInvalid
      break label

    case verb:
    of 0:
      inc env.stats[id].actionNoop
    of 1:
      block moveAction:
        # Trebuchets cannot move when unpacked or while packing/unpacking
        if agent.unitClass == UnitTrebuchet:
          if not agent.packed or agent.cooldown > 0:
            invalidAndBreak(moveAction)

        # Check terrain movement debt - agents with debt >= 1.0 skip their move
        if agent.movementDebt >= 1.0'f32:
          agent.movementDebt -= 1.0'f32
          agent.orientation = Orientation(argument)  # Still update orientation
          env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
          break moveAction  # Skip movement but don't count as invalid

        let moveOrientation = Orientation(argument)
        let delta = orientationToVec(moveOrientation)
        let step1 = agent.pos + delta

        if not isValidPos(step1) or isOutOfBounds(step1):
          invalidAndBreak(moveAction)
        if not env.canTraverseElevation(agent.pos, step1):
          invalidAndBreak(moveAction)
        if env.isWaterBlockedForAgent(agent, step1):
          invalidAndBreak(moveAction)
        if env.terrain[step1.x][step1.y] == Mountain:
          invalidAndBreak(moveAction)
        # Non-transport water units cannot move onto land
        if agent.isWaterUnit and agent.unitClass != UnitBoat and
            env.terrain[step1.x][step1.y] notin WaterTerrain:
          invalidAndBreak(moveAction)
        if not env.canAgentPassDoor(agent, step1):
          inc env.stats[id].actionInvalid
          break moveAction

        # Allow walking through planted lanterns by relocating the lantern, preferring push direction (up to 2 tiles ahead)
        proc canEnterFrom(fromPos, pos: IVec2): bool =
          if not isValidPos(pos) or isOutOfBounds(pos):
            return false
          if not env.canTraverseElevation(fromPos, pos):
            return false
          var canMove = env.isEmpty(pos)
          if canMove:
            return true
          let blocker = env.getThing(pos)
          if blocker.kind != Lantern:
            return false

          var relocated = false
          # Helper to ensure lantern spacing (Chebyshev >= 3 from other lanterns)
          # Uses spatial query with pre-allocated buffer to avoid heap allocations
          template spacingOk(nextPos: IVec2): bool =
            var isSpaced = true
            env.tempLanternSpacing.setLen(0)
            collectThingsInRangeSpatial(env, nextPos, Lantern, 2, env.tempLanternSpacing)
            for t in env.tempLanternSpacing:
              if t != blocker:
                isSpaced = false
                break
            isSpaced
          # Preferred push positions in move direction
          let ahead1 = pos + delta
          let ahead2 = pos + ivec2(delta.x * 2'i32, delta.y * 2'i32)
          let blockerOldPos = blocker.pos
          if isValidPos(ahead2) and not isOutOfBounds(ahead2) and
              env.isEmpty(ahead2) and not env.hasDoor(ahead2) and
              not env.isWaterBlockedForAgent(agent, ahead2) and
              not isBlockedTerrain(env.terrain[ahead2.x][ahead2.y]) and spacingOk(ahead2):
            env.grid[blocker.pos.x][blocker.pos.y] = nil
            blocker.pos = ahead2
            env.grid[blocker.pos.x][blocker.pos.y] = blocker
            updateSpatialIndex(env, blocker, blockerOldPos)
            relocated = true
          elif isValidPos(ahead1) and not isOutOfBounds(ahead1) and
              env.isEmpty(ahead1) and not env.hasDoor(ahead1) and
              not env.isWaterBlockedForAgent(agent, ahead1) and
              not isBlockedTerrain(env.terrain[ahead1.x][ahead1.y]) and spacingOk(ahead1):
            env.grid[blocker.pos.x][blocker.pos.y] = nil
            blocker.pos = ahead1
            env.grid[blocker.pos.x][blocker.pos.y] = blocker
            updateSpatialIndex(env, blocker, blockerOldPos)
            relocated = true
          # Fallback to any adjacent empty tile around the lantern
          if not relocated:
            for dy in -1 .. 1:
              for dx in -1 .. 1:
                if dx == 0 and dy == 0:
                  continue
                let alt = ivec2(pos.x + dx, pos.y + dy)
                if not isValidPos(alt) or isOutOfBounds(alt):
                  continue
                if env.isEmpty(alt) and not env.hasDoor(alt) and
                    not env.isWaterBlockedForAgent(agent, alt) and
                    not isBlockedTerrain(env.terrain[alt.x][alt.y]) and spacingOk(alt):
                  env.grid[blocker.pos.x][blocker.pos.y] = nil
                  blocker.pos = alt
                  env.grid[blocker.pos.x][blocker.pos.y] = blocker
                  updateSpatialIndex(env, blocker, blockerOldPos)
                  relocated = true
                  break
              if relocated:
                break
          return relocated

        let isCavalry = agent.unitClass in CavalryMoveUnits
        let step2 = agent.pos + ivec2(delta.x * 2'i32, delta.y * 2'i32)

        var finalPos = step1
        if not canEnterFrom(agent.pos, step1):
          let blocker = env.getThing(step1)
          if not isNil(blocker):
            if blocker.kind == Agent and not isThingFrozen(blocker, env) and
                sameTeamMask(blocker, agent) and
                env.canTraverseElevation(agent.pos, step1) and
                env.canTraverseElevation(step1, agent.pos):
              let agentOld = agent.pos
              let blockerOld = blocker.pos
              agent.pos = blockerOld
              blocker.pos = agentOld
              env.grid[agentOld.x][agentOld.y] = blocker
              env.grid[blockerOld.x][blockerOld.y] = agent
              updateSpatialIndex(env, agent, agentOld)
              updateSpatialIndex(env, blocker, blockerOld)
              agent.orientation = moveOrientation
              env.updateObservations(AgentLayer, agentOld, getTeamId(blocker) + 1)
              env.updateObservations(AgentLayer, blockerOld, getTeamId(agent) + 1)
              env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
              env.updateObservations(AgentOrientationLayer, blocker.pos, blocker.orientation.int)
              inc env.stats[id].actionMove
              break moveAction
            if blocker.kind in {Tree} and not isThingFrozen(blocker, env):
              if env.harvestTree(agent, blocker):
                inc env.stats[id].actionUse
                break moveAction
          inc env.stats[id].actionInvalid
          break moveAction

        if isCavalry:
          if isValidPos(step2) and
              not env.isWaterBlockedForAgent(agent, step2) and
              env.terrain[step2.x][step2.y] != Mountain and
              env.canAgentPassDoor(agent, step2):
            if canEnterFrom(step1, step2):
              finalPos = step2
        else:
          # Roads and ramps accelerate movement in the direction of entry.
          let step1Terrain = env.terrain[step1.x][step1.y]
          if step1Terrain == Road or isRampTerrain(step1Terrain):
            if isValidPos(step2) and
                not env.isWaterBlockedForAgent(agent, step2) and
                env.terrain[step2.x][step2.y] != Mountain and
                env.canAgentPassDoor(agent, step2):
              if canEnterFrom(step1, step2):
                finalPos = step2

        let originalPos = agent.pos  # Save for cliff fall damage check
        env.grid[agent.pos.x][agent.pos.y] = nil
        # Clear old position and set new position
        env.updateObservations(AgentLayer, agent.pos, 0)  # Clear old
        agent.pos = finalPos
        agent.orientation = moveOrientation
        env.grid[agent.pos.x][agent.pos.y] = agent
        updateSpatialIndex(env, agent, originalPos)

        # Spawn dust trail at the position the unit left (not every move to reduce particles)
        if env.currentStep mod UnitTrailSpawnChance == 0:
          env.spawnUnitTrail(originalPos, getTeamId(agent))

        # Spawn water ripple when non-water units enter water terrain
        let terrainAtPos = env.terrain[agent.pos.x][agent.pos.y]
        if terrainAtPos in WaterTerrain and not agent.isWaterUnit:
          env.spawnWaterRipple(agent.pos)

        # Spawn dust particles when walking on dusty terrain (based on terrain left behind)
        let terrainLeft = env.terrain[originalPos.x][originalPos.y]
        if terrainLeft in DustyTerrain:
          env.spawnDustParticles(originalPos, terrainLeft)

        let dockHere = env.hasDockAt(agent.pos)
        if agent.unitClass == UnitTradeCog:
          # Trade Cogs generate gold when reaching a friendly dock that isn't their home dock
          if dockHere:
            let dockThing = env.getBackgroundThing(agent.pos)
            if not isNil(dockThing) and dockThing.teamId == getTeamId(agent):
              let homeDock = agent.tradeHomeDock
              if homeDock != agent.pos and homeDock != ivec2(0, 0):
                let dist = abs(agent.pos.x - homeDock.x) + abs(agent.pos.y - homeDock.y)
                let goldAmount = max(1, dist div TradeCogDistanceDivisor * TradeCogGoldPerDistance)
                # Trade route gold: no gather rate modifier (fixed economic mechanic)
                env.teamStockpiles[getTeamId(agent)].counts[ResourceGold] += goldAmount
                when defined(econAudit):
                  recordFlow(getTeamId(agent), ResourceGold, goldAmount, rfsTradeShip, env.currentStep)
                agent.tradeHomeDock = agent.pos  # Flip home dock for return trip
        elif agent.unitClass == UnitBoat:
          if dockHere or env.terrain[agent.pos.x][agent.pos.y] != Water:
            disembarkAgent(env, agent)
        elif dockHere:
          embarkAgent(env, agent)

        # Update observations for new position only
        env.updateObservations(AgentLayer, agent.pos, getTeamId(agent) + 1)
        env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)

        # Accumulate terrain movement debt (water units are unaffected by terrain penalties)
        if not agent.isWaterUnit:
          let terrainModifier = getTerrainSpeedModifier(env.terrain[agent.pos.x][agent.pos.y])
          if terrainModifier < 1.0'f32:
            var penalty = 1.0'f32 - terrainModifier
            # Villager speed bonus reduces terrain penalty (Wheelbarrow/Hand Cart)
            if agent.unitClass == UnitVillager:
              let speedBonus = env.getVillagerSpeedBonus(getTeamId(agent))
              if speedBonus > 0:
                penalty = penalty * (1.0'f32 - speedBonus.float32 / 100.0'f32)
            agent.movementDebt += penalty

        # Apply cliff fall damage when dropping elevation without a ramp/road
        # Check both steps of movement (original→step1 and step1→finalPos if different)
        if not agent.isWaterUnit:
          var fallDamage = 0
          if env.willCauseCliffFallDamage(originalPos, step1):
            fallDamage += CliffFallDamage
          if finalPos != step1 and env.willCauseCliffFallDamage(step1, finalPos):
            fallDamage += CliffFallDamage
          if fallDamage > 0:
            discard env.applyAgentDamage(agent, fallDamage)

        inc env.stats[id].actionMove
    of 2:
      block attackAction:
        ## Attack an entity in the given direction. Spears extend range to 2 tiles.
        if argument > 7:
          invalidAndBreak(attackAction)

        # Trebuchets can only attack when unpacked and not in packing/unpacking transition
        if agent.unitClass == UnitTrebuchet:
          if agent.packed or agent.cooldown > 0:
            invalidAndBreak(attackAction)

        let attackOrientation = Orientation(argument)
        agent.orientation = attackOrientation
        env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
        let delta = orientationToVec(attackOrientation)
        let attackerTeam = getTeamId(agent)
        let attackerMask = getTeamMask(attackerTeam)  # Pre-compute for bitwise checks
        var damageAmount = max(1, agent.attackDamage)

        # Ballistics: +1 damage for ranged units (better accuracy = more effective shots)
        if agent.unitClass in BallisticsUnits and
           attackerTeam >= 0 and env.hasUniversityTech(attackerTeam, TechBallistics):
          damageAmount += 1

        var rangedRange = UnitRangedRange[agent.unitClass]

        # Siege Engineers: +1 range for siege units
        if agent.unitClass in SiegeUnits and
           attackerTeam >= 0 and env.hasUniversityTech(attackerTeam, TechSiegeEngineers):
          if rangedRange > 0:
            rangedRange += 1
        let hasSpear = agent.inventorySpear > 0 and rangedRange == 0
        let maxRange = if hasSpear: 2 else: 1

        proc tryHitAt(pos: IVec2): bool =
          if not isValidPos(pos):
            return false
          let door = env.getBackgroundThing(pos)
          if not isNil(door) and door.kind == Door and not isTeamInMask(door.teamId, attackerMask):
            discard env.applyStructureDamage(door, damageAmount, agent)
            return true
          let structure = env.getThing(pos)
          if not isNil(structure) and structure.kind in AttackableStructures:
            if not isTeamInMask(structure.teamId, attackerMask):
              discard env.applyStructureDamage(structure, damageAmount, agent)
              return true
          var target = env.getThing(pos)
          if isNil(target):
            target = env.getBackgroundThing(pos)
          if isNil(target):
            return false
          case target.kind
          of Tumor:
            removeThing(env, target)
            env.rewards[id] += env.config.tumorKillReward
            return true
          of Spawner:
            removeThing(env, target)
            return true
          of Agent:
            if target.agentId == agent.agentId:
              return false
            if (getTeamMask(target) and attackerMask) != 0:  # Same team check via bitwise
              return false
            discard env.applyAgentDamage(target, damageAmount, agent)
            return true
          of Altar:
            if isTeamInMask(target.teamId, attackerMask):  # Same team check via bitwise
              return false
            target.hearts = max(0, target.hearts - 1)
            env.updateObservations(altarHeartsLayer, target.pos, target.hearts)
            if target.hearts == 0:
              let oldTeam = target.teamId
              target.teamId = attackerTeam
              updateTeamMask(target)  # Update cached mask after teamId change
              if attackerTeam >= 0 and attackerTeam < env.teamColors.len:
                env.altarColors[target.pos] = env.teamColors[attackerTeam]
              if oldTeam >= 0:
                for door in env.thingsByKind[Door]:
                  if door.teamId == oldTeam:
                    door.teamId = attackerTeam
                    updateTeamMask(door)  # Update cached mask after teamId change
            return true
          of Cow, Bear, Wolf:
            if not env.giveItem(agent, ItemMeat):
              return false
            # Check if killed wolf is pack leader - scatter the pack
            if target.kind == Wolf and target.isPackLeader:
              let pack = target.packId
              # Clear pack leader tracking
              if pack < env.wolfPackLeaders.len:
                env.wolfPackLeaders[pack] = nil
              # Scatter remaining pack members
              for wolf in env.thingsByKind[Wolf]:
                if wolf.packId == pack and wolf != target:
                  wolf.scatteredSteps = ScatteredDuration
            removeThing(env, target)
            if ResourceNodeInitial > 1:
              let corpse = acquireThing(env, Corpse)
              corpse.pos = pos
              corpse.inventory = emptyInventory()
              setInv(corpse, ItemMeat, ResourceNodeInitial - 1)
              env.add(corpse)
            return true
          of Tree:
            return env.harvestTree(agent, target)
          else:
            return false

        if agent.unitClass == UnitMonk:
          let healPos = agent.pos + delta
          let target = env.getThing(healPos)
          if not isNil(target) and target.kind == Agent:
            if (getTeamMask(target) and attackerMask) != 0:  # Same team check via bitwise
              discard env.applyAgentHeal(target, 1, agent)
              env.applyActionTint(healPos, TileColor(r: 0.35, g: 0.85, b: 0.35, intensity: 1.1), 2, ActionTintHealMonk)
              inc env.stats[id].actionAttack
            else:
              # Faith check for conversion (AoE2-style)
              if agent.faith < MonkConversionFaithCost:
                inc env.stats[id].actionInvalid
                break attackAction
              let newTeam = attackerTeam
              if newTeam < 0 or newTeam >= MapRoomObjectsTeams:
                inc env.stats[id].actionInvalid
                break attackAction
              # Use pre-computed pop caps/counts (avoids O(buildings+agents) per conversion)
              let popCap = env.stepTeamPopCaps[newTeam]
              let popCount = env.stepTeamPopCounts[newTeam]
              if popCap <= 0 or popCount >= popCap:
                inc env.stats[id].actionInvalid
                break attackAction
              var newHome = ivec2(-1, -1)
              if agent.homeAltar.x >= 0:
                let altarThing = env.getThing(agent.homeAltar)
                if not isNil(altarThing) and altarThing.kind == Altar and
                    altarThing.teamId == newTeam:
                  newHome = agent.homeAltar
              if newHome.x < 0:
                # Use spatial query instead of O(n) scan for nearest team altar
                let nearestAltar = findNearestFriendlyThingSpatial(env, target.pos, newTeam, Altar, 1000)
                if not nearestAltar.isNil:
                  newHome = nearestAltar.pos
              target.homeAltar = newHome
              let oldTeam = getTeamId(target)  # Capture old team before override
              let defaultTeam = getTeamId(target.agentId)
              if newTeam == defaultTeam:
                target.teamIdOverride = -1
              else:
                target.teamIdOverride = newTeam
              updateTeamMask(target)  # Update cached mask after teamIdOverride change
              if newTeam < env.teamColors.len:
                env.agentColors[target.agentId] = env.teamColors[newTeam]
              env.updateObservations(AgentLayer, target.pos, newTeam + 1)
              # Update regicide king tracking on conversion
              if target.unitClass == UnitKing:
                if oldTeam >= 0 and oldTeam < MapRoomObjectsTeams and
                    env.victoryStates[oldTeam].kingAgentId == target.agentId:
                  env.victoryStates[oldTeam].kingAgentId = -1  # Old team lost their king
                if newTeam >= 0 and newTeam < MapRoomObjectsTeams:
                  env.victoryStates[newTeam].kingAgentId = target.agentId  # New team gained a king
              # Apply conversion-specific visual effect (golden tint + pulsing glow)
              env.applyActionTint(healPos, ConversionTint, ConversionTintDuration, ActionTintConvertMonk)
              if newTeam < env.teamColors.len:
                env.spawnConversionEffect(healPos, env.teamColors[newTeam])
              # Consume faith on successful conversion
              agent.faith = agent.faith - MonkConversionFaithCost
              when defined(combatAudit):
                let oldTargetTeam = getTeamId(target.agentId)  # original team before override
                recordConversion(env.currentStep, attackerTeam, oldTargetTeam,
                                 agent.agentId, target.agentId, $target.unitClass)
              when defined(eventLog):
                let oldTargetTeamForLog = getTeamId(target.agentId)
                logConversion(attackerTeam, oldTargetTeamForLog, $target.unitClass, env.currentStep)
              inc env.stats[id].actionAttack
          else:
            inc env.stats[id].actionInvalid
          break attackAction

        if agent.unitClass == UnitMangonel:
          # "Large spear" attack: forward line 5 tiles with 1-tile side prongs
          # per siege_fortifications_plan.md section 1.2 and combat.md
          var hit = false
          let left = ivec2(-delta.y, delta.x)
          let right = ivec2(delta.y, -delta.x)
          let offsets = [ivec2(0, 0), left, right]  # 1-tile side prongs
          # Visual projectile to midpoint of AoE area
          let midStep = (MangonelAoELength + 1) div 2
          let mangonelTarget = agent.pos + ivec2(delta.x * midStep.int32, delta.y * midStep.int32)
          env.spawnProjectile(agent.pos, mangonelTarget, ProjMangonel)
          for step in 1 .. MangonelAoELength:
            let forward = agent.pos + ivec2(delta.x * step.int32, delta.y * step.int32)
            for offset in offsets:
              let attackPos = forward + offset
              env.applyUnitAttackTint(agent.unitClass, attackPos)
              if tryHitAt(attackPos):
                hit = true
          if hit:
            inc env.stats[id].actionAttack
          else:
            inc env.stats[id].actionInvalid
          break attackAction

        if rangedRange > 0:
          var attackHit = false
          # Spawn visual projectile to max range (or first hit)
          let rangedProjKind = case agent.unitClass
            of UnitTrebuchet: ProjTrebuchet
            of UnitLongbowman: ProjLongbow
            of UnitJanissary: ProjJanissary
            else: ProjArrow
          for distance in 1 .. rangedRange:
            let attackPos = agent.pos + ivec2(delta.x * distance.int32, delta.y * distance.int32)
            env.applyUnitAttackTint(agent.unitClass, attackPos)
            if tryHitAt(attackPos):
              env.spawnProjectile(agent.pos, attackPos, rangedProjKind)
              attackHit = true
              break
          if not attackHit:
            # Missed: show arrow flying to max range
            let maxPos = agent.pos + ivec2(delta.x * rangedRange.int32, delta.y * rangedRange.int32)
            env.spawnProjectile(agent.pos, maxPos, rangedProjKind)
          if attackHit:
            inc env.stats[id].actionAttack
          else:
            inc env.stats[id].actionInvalid
          break attackAction

        # Armor overlay (defensive flash)
        if agent.inventoryArmor > 0:
          let tint = TileColor(r: 0.95, g: 0.75, b: 0.25, intensity: 1.1)
          if abs(delta.x) == 1 and abs(delta.y) == 1:
            let diagPos = agent.pos + ivec2(delta.x, delta.y)
            let xPos = agent.pos + ivec2(delta.x, 0)
            let yPos = agent.pos + ivec2(0, delta.y)
            env.applyActionTint(diagPos, tint, 2, ActionTintShield)
            env.applyActionTint(xPos, tint, 2, ActionTintShield)
            env.applyActionTint(yPos, tint, 2, ActionTintShield)
          else:
            let perp = if delta.x != 0: ivec2(0, 1) else: ivec2(1, 0)
            let forward = agent.pos + ivec2(delta.x, delta.y)
            for offset in -1 .. 1:
              let pos = forward + ivec2(perp.x * offset, perp.y * offset)
              env.applyActionTint(pos, tint, 2, ActionTintShield)
          env.shieldCountdown[agent.agentId] = 2

        # Spear: area strike (3 forward + diagonals)
        if hasSpear:
          var hit = false
          let left = ivec2(-delta.y, delta.x)
          let right = ivec2(delta.y, -delta.x)
          let offsets = [ivec2(0, 0), left, right]
          for step in 1 .. 3:
            let forward = agent.pos + ivec2(delta.x * step, delta.y * step)
            for offset in offsets:
              let attackPos = forward + offset
              env.applyUnitAttackTint(agent.unitClass, attackPos)
              if tryHitAt(attackPos):
                hit = true

          if hit:
            agent.inventorySpear = max(0, agent.inventorySpear - 1)
            inc env.stats[id].actionAttack
          else:
            inc env.stats[id].actionInvalid
          break attackAction

        if agent.unitClass in ChargeAttackUnits:
          var hit = false
          for distance in 1 .. 2:
            let attackPos = agent.pos + ivec2(delta.x * distance, delta.y * distance)
            env.applyUnitAttackTint(agent.unitClass, attackPos)
            if tryHitAt(attackPos):
              hit = true
              break
          if hit:
            inc env.stats[id].actionAttack
          else:
            inc env.stats[id].actionInvalid
          break attackAction

        if agent.isWaterUnit:
          if agent.unitClass == UnitTradeCog:
            # Trade Cogs cannot attack
            inc env.stats[id].actionInvalid
          else:
            var hit = false
            let left = ivec2(-delta.y, delta.x)
            let right = ivec2(delta.y, -delta.x)
            let forward = agent.pos + delta
            for pos in [forward, forward + left, forward + right]:
              env.applyUnitAttackTint(agent.unitClass, pos)
              if tryHitAt(pos):
                hit = true
            if hit:
              inc env.stats[id].actionAttack
              # DemoShip: kamikaze self-destruction after successful attack
              if agent.unitClass == UnitDemoShip:
                env.killAgent(agent)
            else:
              inc env.stats[id].actionInvalid
          break attackAction

        var attackHit = false

        for distance in 1 .. maxRange:
          let attackPos = agent.pos + ivec2(delta.x * distance.int32, delta.y * distance.int32)
          env.applyUnitAttackTint(agent.unitClass, attackPos)
          if tryHitAt(attackPos):
            attackHit = true
            break

        if attackHit:
          if hasSpear:
            agent.inventorySpear = max(0, agent.inventorySpear - 1)
          inc env.stats[id].actionAttack
        else:
          inc env.stats[id].actionInvalid
    of 3:
      block useAction:
        ## Use terrain or building with a single action in a direction.
        ## Trebuchets: argument 8 triggers pack/unpack toggle.

        # Trebuchet pack/unpack: special argument 8 triggers state toggle
        if agent.unitClass == UnitTrebuchet and argument == 8:
          if agent.cooldown > 0:
            # Already in pack/unpack transition, can't start another
            invalidAndBreak(useAction)
          # Start pack/unpack transition
          agent.cooldown = TrebuchetPackDuration
          # Apply visual tint to show packing/unpacking animation
          let tint = TileColor(r: 0.60, g: 0.40, b: 0.95, intensity: 1.15)
          env.applyActionTint(agent.pos, tint, TrebuchetPackDuration.int8, ActionTintAttackTrebuchet)
          inc env.stats[id].actionUse
          break useAction

        # Ungarrison: argument 9 triggers ungarrison of all units from adjacent garrisonable building
        if argument == 9:
          let foundBuilding = env.findAdjacentFriendlyBuilding(
            agent.pos, getTeamId(agent), isGarrisonableBuilding)
          if foundBuilding.isNil:
            invalidAndBreak(useAction)
          let ejected = env.ungarrisonAllUnits(foundBuilding)
          if ejected.len > 0:
            inc env.stats[id].actionUse
          else:
            invalidAndBreak(useAction)
          break useAction

        # Town Bell: argument 10 toggles the town bell for the team
        if argument == 10:
          # Find adjacent TownCenter belonging to agent's team
          let foundTC = env.findAdjacentFriendlyBuilding(
            agent.pos, getTeamId(agent), isTownCenterKind)
          if foundTC.isNil:
            invalidAndBreak(useAction)
          let teamId = getTeamId(agent)
          if teamId >= 0 and teamId < MapRoomObjectsTeams:
            if env.townBellActive[teamId]:
              # Second press: deactivate bell, ungarrison all team buildings
              env.townBellActive[teamId] = false
              for kind in [TownCenter, Castle, GuardTower, House]:
                for building in env.thingsByKind[kind]:
                  if building.teamId == teamId and building.garrisonedUnits.len > 0:
                    discard env.ungarrisonAllUnits(building)
            else:
              # First press: activate bell, villagers will seek garrison via AI options
              env.townBellActive[teamId] = true
          inc env.stats[id].actionUse
          break useAction

        if argument > 7:
          invalidAndBreak(useAction)
        let useOrientation = Orientation(argument)
        agent.orientation = useOrientation
        env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
        let delta = orientationToVec(useOrientation)
        let targetPos = agent.pos + delta

        if not isValidPos(targetPos):
          inc env.stats[id].actionInvalid
          break useAction

        # Frozen tiles are non-interactable (terrain or things sitting on them)
        if isTileFrozen(targetPos, env):
          inc env.stats[id].actionInvalid
          break useAction

        var thing = env.getThing(targetPos)
        if isNil(thing):
          thing = env.getBackgroundThing(targetPos)
        template decInv(key: ItemKey) =
          setInv(agent, key, getInv(agent, key) - 1)

        template incInv(key: ItemKey) =
          setInv(agent, key, getInv(agent, key) + 1)

        if isNil(thing):
          # Terrain use only when no Thing occupies the tile.
          var used = false
          case env.terrain[targetPos.x][targetPos.y]:
          of Water:
            if env.giveItem(agent, ItemWater):
              env.rewards[id] += env.config.waterReward
              used = true
          of Empty, Grass, Dune, Sand, Snow, Road,
             RampUpN, RampUpS, RampUpW, RampUpE,
             RampDownN, RampDownS, RampDownW, RampDownE:
            if env.hasDoor(targetPos):
              used = false
            elif agent.inventoryRelic > 0 and agent.unitClass == UnitMonk:
              let canDrop = env.isEmpty(targetPos) and not env.hasDoor(targetPos) and
                not isTileFrozen(targetPos, env) and env.terrain[targetPos.x][targetPos.y] != Water
              if canDrop:
                let relic = Thing(kind: Relic, pos: targetPos)
                relic.inventory = emptyInventory()
                setInv(relic, ItemGold, 0)
                env.add(relic)
                agent.inventoryRelic = agent.inventoryRelic - 1
                used = true
            elif agent.inventoryBread > 0:
              decInv(ItemBread)
              let tint = TileColor(r: 0.35, g: 0.85, b: 0.35, intensity: 1.1)
              for dx in -1 .. 1:
                for dy in -1 .. 1:
                  let pos = agent.pos + ivec2(dx, dy)
                  env.applyActionTint(pos, tint, 2, ActionTintHealBread)
                  let occ = env.getThing(pos)
                  if occ.isKind(Agent):
                    let healAmt = min(BreadHealAmount, occ.maxHp - occ.hp)
                    if healAmt > 0:
                      discard env.applyAgentHeal(occ, healAmt)
              used = true
            else:
              if agent.inventoryWater > 0:
                decInv(ItemWater)
                env.terrain[targetPos.x][targetPos.y] = Fertile
                env.resetTileColor(targetPos)
                env.updateObservations(TintLayer, targetPos, 0)
                used = true
          else:
            used = false

          if used:
            inc env.stats[id].actionUse
          else:
            inc env.stats[id].actionInvalid
          break useAction
        # Building use
        # Prevent interacting with frozen objects/buildings
        if isThingFrozen(thing, env):
          inc env.stats[id].actionInvalid
          break useAction

        let agentTeamId = getTeamId(agent)
        let agentMask = getTeamMask(agentTeamId)  # Pre-compute for bitwise checks
        var used = false
        template takeFromThing(key: ItemKey, rewardAmount: float32 = 0.0) =
          let stored = getInv(thing, key)
          if stored <= 0:
            removeThing(env, thing)
            used = true
          elif env.giveItem(agent, key):
            let gatherPos = thing.pos  # Capture for sparkle effect
            let remaining = stored - 1
            if rewardAmount != 0:
              env.rewards[id] += rewardAmount
            if remaining <= 0:
              removeThing(env, thing)
            else:
              setInv(thing, key, remaining)
            # Apply biome gathering bonus
            let bonus = env.getBiomeGatherBonus(gatherPos, key)
            if bonus > 0:
              discard env.giveItem(agent, key, bonus)
            # Apply economy tech gathering bonus (AoE2-style)
            var techBonusPct = 0
            if key == ItemGold:
              techBonusPct = env.getGoldGatherBonus(agentTeamId)
            elif key == ItemStone:
              techBonusPct = env.getStoneGatherBonus(agentTeamId)
            elif key == ItemWood:
              techBonusPct = env.getWoodGatherBonus(agentTeamId)
            if techBonusPct > 0 and (env.currentStep mod (100 div max(1, techBonusPct))) == 0:
              # Probabilistic bonus: techBonusPct% chance per gather to get +1
              discard env.giveItem(agent, key)
            # Spawn sparkle effect at resource location
            env.spawnGatherSparkle(gatherPos)
            used = true
        case thing.kind:
        of Relic:
          if agent.unitClass in {UnitMonk, UnitGoblin}:
            let stored = getInv(thing, ItemGold)
            if stored > 0:
              if env.giveItem(agent, ItemGold):
                setInv(thing, ItemGold, stored - 1)
              else:
                used = false
                break useAction
            if agent.inventoryRelic < MapObjectAgentMaxInventory:
              agent.inventoryRelic = agent.inventoryRelic + 1
              removeThing(env, thing)
              used = true
            else:
              used = stored > 0
        of Lantern:
          if agent.inventoryLantern < MapObjectAgentMaxInventory:
            agent.inventoryLantern = agent.inventoryLantern + 1
            removeThing(env, thing)
            used = true
        of Wheat:
          let stored = getInv(thing, ItemWheat)
          if stored <= 0:
            removeThing(env, thing)
            used = true
          elif env.grantItem(agent, ItemWheat):
            env.rewards[id] += env.config.wheatReward
            # Apply biome gathering bonus
            let bonus = env.getBiomeGatherBonus(thing.pos, ItemWheat)
            if bonus > 0:
              discard env.grantItem(agent, ItemWheat, bonus)
            let stubblePos = thing.pos  # Capture before pool release
            removeThing(env, thing)
            let stubble = acquireThing(env, Stubble)
            stubble.pos = stubblePos
            stubble.inventory = emptyInventory()
            let remaining = stored - 1
            if remaining > 0:
              setInv(stubble, ItemWheat, remaining)
              env.add(stubble)
            else:
              # Farm exhausted - check for pre-paid reseed first
              let mill = env.findNearestMill(stubblePos, agentTeamId)
              if mill != nil and mill.queuedFarmReseeds > 0:
                # Consume pre-paid reseed and immediately rebuild farm
                mill.queuedFarmReseeds -= 1
                # Don't add stubble, create new farm instead
                releaseThing(env, stubble)
                let newFarm = Thing(kind: Wheat, pos: stubblePos)
                newFarm.inventory = emptyInventory()
                let farmFood = ResourceNodeInitial + env.getFarmFoodBonus(agentTeamId)
                setInv(newFarm, ItemWheat, farmFood)
                env.add(newFarm)
              elif env.canAutoReseed(agentTeamId) and mill != nil:
                # Add to mill queue for delayed processing
                env.addFarmToMillQueue(mill, stubblePos)
                env.add(stubble)
              else:
                env.add(stubble)
            # Spawn sparkle effect at harvest location
            env.spawnGatherSparkle(stubblePos)
            used = true
        of Stubble, Stump:
          let (key, reward) = if thing.kind == Stubble:
            (ItemWheat, env.config.wheatReward)
          else:
            (ItemWood, env.config.woodReward)
          if env.grantItem(agent, key):
            let gatherPos = thing.pos  # Capture for sparkle effect
            env.rewards[id] += reward
            # Apply biome gathering bonus
            let bonus = env.getBiomeGatherBonus(gatherPos, key)
            if bonus > 0:
              discard env.grantItem(agent, key, bonus)
            let remaining = getInv(thing, key) - 1
            if remaining <= 0:
              removeThing(env, thing)
            else:
              setInv(thing, key, remaining)
            # Spawn sparkle effect at resource location
            env.spawnGatherSparkle(gatherPos)
            used = true
        of Stone:
          takeFromThing(ItemStone)
        of Gold:
          takeFromThing(ItemGold)
        of Bush, Cactus:
          takeFromThing(ItemPlant)
        of Stalagmite:
          takeFromThing(ItemStone)
        of Fish:
          takeFromThing(ItemFish)
        of Tree:
          used = env.harvestTree(agent, thing)
        of Corpse:
          var lootKey = ItemNone
          var lootCount = 0
          for key, count in thing.inventory.pairs:
            if count > 0:
              lootKey = key
              lootCount = count
              break
          if lootKey != ItemNone:
            if env.giveItem(agent, lootKey):
              let remaining = lootCount - 1
              if remaining <= 0:
                thing.inventory.del(lootKey)
              else:
                setInv(thing, lootKey, remaining)
              var hasItems = false
              for _, count in thing.inventory.pairs:
                if count > 0:
                  hasItems = true
                  break
              if not hasItems:
                removeThing(env, thing)
                if lootKey != ItemMeat:
                  let skeletonPos = thing.pos  # Capture before potential pool reuse
                  let skeleton = acquireThing(env, Skeleton)
                  skeleton.pos = skeletonPos
                  skeleton.inventory = emptyInventory()
                  env.add(skeleton)
              used = true
        of Magma:  # Magma smelting
          if thing.cooldown == 0 and getInv(agent, ItemGold) > 0 and agent.inventoryBar < MapObjectAgentMaxInventory:
            setInv(agent, ItemGold, getInv(agent, ItemGold) - 1)
            agent.inventoryBar = agent.inventoryBar + 1
            thing.cooldown = 0
            if agent.inventoryBar == 1:
              env.rewards[id] += env.config.barReward
            used = true
        of WeavingLoom:
          if thing.cooldown == 0 and agent.inventoryLantern == 0 and
              (agent.inventoryWheat > 0 or agent.inventoryWood > 0):
            if agent.inventoryWood > 0:
              decInv(ItemWood)
            else:
              decInv(ItemWheat)
            setInv(agent, ItemLantern, 1)
            thing.cooldown = 0
            env.rewards[id] += env.config.clothReward
            used = true
          elif thing.cooldown == 0:
            if env.tryCraftAtStation(agent, StationLoom, thing):
              used = true
        of ClayOven:
          if thing.cooldown == 0:
            if env.tryCraftAtStation(agent, StationOven, thing):
              used = true
            elif agent.inventoryWheat > 0:
              decInv(ItemWheat)
              incInv(ItemBread)
              thing.cooldown = 0
              # No observation layer for bread; optional for UI later
              env.rewards[id] += env.config.foodReward
              used = true
        of Skeleton:
          let stored = getInv(thing, ItemFish)
          if stored > 0 and env.giveItem(agent, ItemFish):
            let remaining = stored - 1
            if remaining <= 0:
              removeThing(env, thing)
            else:
              setInv(thing, ItemFish, remaining)
            used = true
        of Temple:
          if agent.unitClass == UnitVillager and thing.cooldown == 0:
            env.templeInteractions.add TempleInteraction(
              agentId: agent.agentId,
              teamId: getTeamId(agent),
              pos: thing.pos
            )
            thing.cooldown = TempleInteractionCooldown
            used = true
        of Wall, Door:
          # Construction/repair: villagers can work on walls and doors
          if isTeamInMask(thing.teamId, agentMask) and thing.hp < thing.maxHp and
             agent.unitClass == UnitVillager:
            # Register this builder for the multi-builder bonus
            env.constructionBuilders.mgetOrPut(thing.pos, 0) += 1
            used = true
        else:
          if isBuildingKind(thing.kind):
            # Construction: villagers can work on buildings under construction
            if thing.maxHp > 0 and thing.hp < thing.maxHp and
               isTeamInMask(thing.teamId, agentMask) and agent.unitClass == UnitVillager:
              # Register this builder for the multi-builder bonus
              env.constructionBuilders.mgetOrPut(thing.pos, 0) += 1
              used = true
            # Normal building use (skip if construction happened)
            if not used:
              let useKind = buildingUseKind(thing.kind)
              case useKind
              of UseAltar:
                if thing.cooldown == 0 and agent.inventoryBar >= 1:
                  decInv(ItemBar)
                  thing.hearts = thing.hearts + 1
                  thing.cooldown = MapObjectAltarCooldown
                  env.updateObservations(altarHeartsLayer, thing.pos, thing.hearts)
                  env.rewards[id] += env.config.heartReward
                  used = true
              of UseClayOven:
                if thing.cooldown == 0:
                  if buildingHasCraftStation(thing.kind) and env.tryCraftAtStation(agent, buildingCraftStation(thing.kind), thing):
                    used = true
                  elif agent.inventoryWheat > 0:
                    decInv(ItemWheat)
                    incInv(ItemBread)
                    thing.cooldown = 0
                    env.rewards[id] += env.config.foodReward
                    used = true
              of UseWeavingLoom:
                if thing.cooldown == 0 and agent.inventoryLantern == 0 and
                    (agent.inventoryWheat > 0 or agent.inventoryWood > 0):
                  if agent.inventoryWood > 0:
                    decInv(ItemWood)
                  else:
                    decInv(ItemWheat)
                  setInv(agent, ItemLantern, 1)
                  thing.cooldown = 0
                  env.rewards[id] += env.config.clothReward
                  used = true
                elif thing.cooldown == 0 and buildingHasCraftStation(thing.kind):
                  if env.tryCraftAtStation(agent, buildingCraftStation(thing.kind), thing):
                    used = true
              of UseBlacksmith:
                if thing.cooldown == 0:
                  if buildingHasCraftStation(thing.kind) and env.tryCraftAtStation(agent, buildingCraftStation(thing.kind), thing):
                    used = true
                if not used and isTeamInMask(thing.teamId, agentMask):
                  if env.useStorageBuilding(agent, thing, buildingStorageItems(thing.kind)):
                    used = true
                # If crafting and storage failed, try researching a Blacksmith upgrade
                if not used and thing.cooldown == 0 and isTeamInMask(thing.teamId, agentMask):
                  if env.tryResearchBlacksmithUpgrade(agent, thing):
                    used = true
              of UseMarket:
                # AoE2-style market trading with dynamic prices
                if thing.cooldown == 0:
                  if isTeamInMask(thing.teamId, agentMask):  # Same team check via bitwise
                    var traded = false
                    # Reuse arena buffer for inventory snapshot
                    env.arena.itemCounts.setLen(0)
                    for key, count in agent.inventory.pairs:
                      if count <= 0:
                        continue
                      if not isStockpileResourceKey(key):
                        continue
                      env.arena.itemCounts.add((key: key, count: count))
                    for entry in env.arena.itemCounts:
                      let key = entry.key
                      let count = entry.count
                      let stockpileRes = stockpileResourceForItem(key)
                      if stockpileRes == ResourceWater:
                        continue
                      if stockpileRes == ResourceGold:
                        # Buy food with gold (dynamic pricing)
                        when defined(eventLog):
                          let (goldSpent, foodGained) = env.marketBuyFood(agent, count)
                          if foodGained > 0:
                            logMarketTrade(agentTeamId, "Bought", "Food", foodGained, goldSpent, env.currentStep)
                            traded = true
                        else:
                          let (_, foodGained) = env.marketBuyFood(agent, count)
                          if foodGained > 0:
                            traded = true
                      else:
                        # Sell resources for gold (dynamic pricing)
                        when defined(eventLog):
                          let (amountSold, goldGained) = env.marketSellInventory(agent, key)
                          if amountSold > 0:
                            logMarketTrade(agentTeamId, "Sold", $stockpileRes, amountSold, goldGained, env.currentStep)
                            traded = true
                        else:
                          let (amountSold, _) = env.marketSellInventory(agent, key)
                          if amountSold > 0:
                            traded = true
                    if traded:
                      thing.cooldown = DefaultMarketCooldown
                      used = true
              of UseDropoff:
                if isTeamInMask(thing.teamId, agentMask):
                  if env.useDropoffBuilding(agent, buildingDropoffResources(thing.kind)):
                    used = true
                  # Economy tech research (AoE2-style) - villagers research at economy buildings
                  if not used and thing.cooldown == 0:
                    if env.tryResearchEconomyTech(agent, thing):
                      used = true
                  # Town Center garrison: villagers can garrison if no resources to drop off
                  if not used and thing.kind == TownCenter and agent.unitClass == UnitVillager:
                    if env.garrisonUnitInBuilding(agent, thing):
                      used = true
              of UseDropoffAndTrain:
                if isTeamInMask(thing.teamId, agentMask):
                  if env.useDropoffBuilding(agent, buildingDropoffResources(thing.kind)):
                    used = true
                  # Check production queue first (pre-paid training from fighter AI)
                  if not used and buildingHasTrain(thing.kind) and agent.unitClass == UnitVillager:
                    if env.tryConsumeProductionQueue(agent, thing):
                      if agent.unitClass == UnitTradeCog:
                        agent.tradeHomeDock = thing.pos
                      used = true
                  # Fallback: direct training (for gatherers visiting dock)
                  if not used and thing.cooldown == 0 and buildingHasTrain(thing.kind):
                    if env.tryTrainUnit(agent, thing, buildingTrainUnit(thing.kind, agentTeamId),
                        buildingTrainCosts(thing.kind), 0):
                      if agent.unitClass == UnitTradeCog:
                        agent.tradeHomeDock = thing.pos
                      used = true
              of UseDropoffAndStorage:
                if isTeamInMask(thing.teamId, agentMask):
                  if env.useDropoffBuilding(agent, buildingDropoffResources(thing.kind)):
                    used = true
                  if not used and env.useStorageBuilding(agent, thing, buildingStorageItems(thing.kind)):
                    used = true
              of UseStorage:
                if env.useStorageBuilding(agent, thing, buildingStorageItems(thing.kind)):
                  used = true
              of UseTrain:
                # Special case: Monks can deposit relics in Monastery for gold generation
                if thing.kind == Monastery and agent.unitClass == UnitMonk and agent.inventoryRelic > 0:
                  thing.garrisonedRelics = thing.garrisonedRelics + agent.inventoryRelic
                  agent.inventoryRelic = 0
                  used = true
                elif buildingHasTrain(thing.kind) and agent.unitClass == UnitVillager:
                  # If queue has a ready entry, convert villager immediately (pre-paid)
                  if env.tryConsumeProductionQueue(agent, thing):
                    used = true
                  # Try unit upgrade research if no ready queue entry
                  elif thing.cooldown == 0 and env.tryResearchUnitUpgrade(agent, thing):
                    used = true
                  # Otherwise queue a new training request (pay now, train later)
                  # Use effectiveTrainUnit to train the upgraded version
                  elif env.queueTrainUnit(thing, agentTeamId,
                      env.effectiveTrainUnit(thing.kind, agentTeamId),
                      buildingTrainCosts(thing.kind)):
                    used = true
              of UseTrainAndCraft:
                if thing.cooldown == 0:
                  if buildingHasCraftStation(thing.kind) and env.tryCraftAtStation(agent, buildingCraftStation(thing.kind), thing):
                    used = true
                  elif buildingHasTrain(thing.kind) and agent.unitClass == UnitVillager:
                    if env.tryConsumeProductionQueue(agent, thing):
                      used = true
                    elif env.queueTrainUnit(thing, agentTeamId,
                        env.effectiveTrainUnit(thing.kind, agentTeamId),
                        buildingTrainCosts(thing.kind)):
                      used = true
              of UseCraft:
                if env.tryCraftAtBuilding(agent, thing):
                  used = true
              of UseUniversity:
                # University: craft items first, then research techs (like Blacksmith)
                if env.tryCraftAtBuilding(agent, thing):
                  used = true
                # If crafting failed or not possible, try researching
                if not used and thing.cooldown == 0 and isTeamInMask(thing.teamId, agentMask):
                  if env.tryResearchUniversityTech(agent, thing):
                    used = true
              of UseCastle:
                # Castle: research unique techs first, then train unique units
                # Research takes priority (like AoE2 where research buttons are distinct)
                if thing.cooldown == 0 and isTeamInMask(thing.teamId, agentMask):
                  if env.tryResearchCastleTech(agent, thing):
                    used = true
                # If no research available, try training units
                if not used and buildingHasTrain(thing.kind) and agent.unitClass == UnitVillager:
                  if env.tryConsumeProductionQueue(agent, thing):
                    used = true
                  elif env.queueTrainUnit(thing, agentTeamId,
                      buildingTrainUnit(thing.kind, agentTeamId),
                      buildingTrainCosts(thing.kind)):
                    used = true
                # Castle garrison: military units can garrison if no other action
                if not used and isTeamInMask(thing.teamId, agentMask) and agent.unitClass != UnitVillager:
                  if env.garrisonUnitInBuilding(agent, thing):
                    used = true
              of UseNone:
                # Garrison: any unit can garrison in buildings with garrison capacity
                if isTeamInMask(thing.teamId, agentMask) and garrisonCapacity(thing.kind) > 0:
                  if env.garrisonUnitInBuilding(agent, thing):
                    used = true

        if not used:
          block pickupAttempt:
            if isBuildingKind(thing.kind):
              break pickupAttempt
            if thing.kind in {Agent, Tumor, Tree, Wheat, Fish, Relic, Stubble, Stone, Gold, Bush, Cactus, Stalagmite,
                              Cow, Bear, Wolf, Corpse, Skeleton, Spawner, Stump, Wall, Magma, Lantern} or
                thing.kind in CliffKinds:
              break pickupAttempt

            let key = thingItem($thing.kind)
            let current = getInv(agent, key)
            if current >= MapObjectAgentMaxInventory:
              break pickupAttempt
            var resourceNeeded = 0
            for itemKey, count in thing.inventory.pairs:
              if isStockpileResourceKey(itemKey):
                resourceNeeded += count
              else:
                let capacity = MapObjectAgentMaxInventory - getInv(agent, itemKey)
                if capacity < count:
                  break pickupAttempt
            if resourceNeeded > stockpileCapacityLeft(agent):
              break pickupAttempt
            for itemKey, count in thing.inventory.pairs:
              setInv(agent, itemKey, getInv(agent, itemKey) + count)
            setInv(agent, key, current + 1)
            if isValidPos(thing.pos):
              env.updateObservations(ThingAgentLayer, thing.pos, 0)
            removeThing(env, thing)
            used = true

        if used:
          inc env.stats[id].actionUse
          when defined(gatherHeatmap):
            if not thing.isNil:
              let gk = thingToGatherKind(thing.kind)
              if gk != grNone:
                recordGatherEvent(targetPos, gk)
        else:
          inc env.stats[id].actionInvalid
    of 4:
      block swapAction:
        ## Swap
        if argument > 7:
          invalidAndBreak(swapAction)
        let dir = Orientation(argument)
        agent.orientation = dir
        env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
        let targetPos = agent.pos + orientationToVec(dir)
        let target = env.getThing(targetPos)
        if isNil(target) or target.kind != Agent or isThingFrozen(target, env):
          inc env.stats[id].actionInvalid
          break swapAction
        let agentOld = agent.pos
        let targetOld = target.pos
        agent.pos = targetOld
        target.pos = agentOld
        env.grid[agentOld.x][agentOld.y] = target
        env.grid[targetOld.x][targetOld.y] = agent
        updateSpatialIndex(env, agent, agentOld)
        updateSpatialIndex(env, target, targetOld)
        env.updateObservations(AgentLayer, agentOld, getTeamId(target) + 1)
        env.updateObservations(AgentLayer, targetOld, getTeamId(agent) + 1)
        env.updateObservations(AgentOrientationLayer, agentOld, target.orientation.int)
        env.updateObservations(AgentOrientationLayer, targetOld, agent.orientation.int)
        inc env.stats[id].actionSwap
    of 5:
      block putAction:
        ## Give items to adjacent teammate in the given direction.
        if argument > 7:
          invalidAndBreak(putAction)
        let dir = Orientation(argument)
        agent.orientation = dir
        env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
        let delta = orientationToVec(dir)
        let targetPos = agent.pos + delta
        if not isValidPos(targetPos):
          inc env.stats[id].actionInvalid
          break putAction
        let target = env.getThing(targetPos)
        if isNil(target):
          inc env.stats[id].actionInvalid
          break putAction
        if target.kind != Agent or isThingFrozen(target, env):
          inc env.stats[id].actionInvalid
          break putAction
        var transferred = false
        # Give armor if we have any and target has none
        if agent.inventoryArmor > 0 and target.inventoryArmor == 0:
          target.inventoryArmor = agent.inventoryArmor
          agent.inventoryArmor = 0
          transferred = true
        # Otherwise give food if possible (no obs layer yet)
        elif agent.inventoryBread > 0:
          let capacity = stockpileCapacityLeft(target)
          let giveAmt = min(agent.inventoryBread, capacity)
          if giveAmt > 0:
            agent.inventoryBread = agent.inventoryBread - giveAmt
            target.inventoryBread = target.inventoryBread + giveAmt
            transferred = true
        else:
          let stockpileCapacityLeftTarget = stockpileCapacityLeft(target)
          var bestKey = ItemNone
          var bestCount = 0
          for key, count in agent.inventory.pairs:
            if count <= 0:
              continue
            let capacity =
              if isStockpileResourceKey(key):
                stockpileCapacityLeftTarget
              else:
                MapObjectAgentMaxInventory - getInv(target, key)
            if capacity <= 0:
              continue
            if count > bestCount:
              bestKey = key
              bestCount = count
          if bestKey != ItemNone and bestCount > 0:
            let capacity =
              if isStockpileResourceKey(bestKey):
                stockpileCapacityLeftTarget
              else:
                max(0, MapObjectAgentMaxInventory - getInv(target, bestKey))
            if capacity > 0:
              let moved = min(bestCount, capacity)
              setInv(agent, bestKey, bestCount - moved)
              setInv(target, bestKey, getInv(target, bestKey) + moved)
              transferred = true
        if transferred:
          inc env.stats[id].actionPut
        else:
          inc env.stats[id].actionInvalid
    of 6:
      block plantAction:
        ## Plant lantern in the given direction.
        if argument > 7:
          inc env.stats[id].actionInvalid
          break plantAction
        let plantOrientation = Orientation(argument)
        agent.orientation = plantOrientation
        env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
        let delta = orientationToVec(plantOrientation)
        let targetPos = agent.pos + delta

        # Check if position is empty and not water
        if not env.isEmpty(targetPos) or env.hasDoor(targetPos) or isBlockedTerrain(env.terrain[targetPos.x][targetPos.y]) or isTileFrozen(targetPos, env):
          inc env.stats[id].actionInvalid
          break plantAction

        if agent.inventoryLantern > 0:
          # Calculate team ID directly from the planting agent's ID
          let teamId = getTeamId(agent)

          # Plant the lantern
          let lantern = acquireThing(env, Lantern)
          lantern.pos = targetPos
          lantern.teamId = teamId
          lantern.lanternHealthy = true

          env.add(lantern)

          # Consume the lantern from agent's inventory
          agent.inventoryLantern = 0

          # Give reward for planting
          env.rewards[id] += env.config.clothReward * 0.5  # Half reward for planting

          inc env.stats[id].actionPlant
        else:
          inc env.stats[id].actionInvalid
    of 7:
      block plantResourceAction:
        ## Plant wheat (args 0-3) or tree (args 4-7) onto an adjacent fertile tile.
        let plantingTree =
          if argument <= 7:
            argument >= 4
          else:
            (argument mod 2) == 1
        let dirIndex =
          if argument <= 7:
            (if plantingTree: argument - 4 else: argument)
          else:
            (if argument mod 2 == 1: (argument div 2) mod 4 else: argument mod 4)
        if dirIndex < 0 or dirIndex > 7:
          inc env.stats[id].actionInvalid
          break plantResourceAction
        let orientation = Orientation(dirIndex)
        agent.orientation = orientation
        env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
        let delta = orientationToVec(orientation)
        let targetPos = agent.pos + delta

        # Occupancy checks
        if not env.isEmpty(targetPos) or not isNil(env.getBackgroundThing(targetPos)) or env.hasDoor(targetPos) or
            isBlockedTerrain(env.terrain[targetPos.x][targetPos.y]) or isTileFrozen(targetPos, env):
          inc env.stats[id].actionInvalid
          break plantResourceAction
        if env.terrain[targetPos.x][targetPos.y] != Fertile:
          inc env.stats[id].actionInvalid
          break plantResourceAction

        if plantingTree:
          if agent.inventoryWood <= 0:
            inc env.stats[id].actionInvalid
            break plantResourceAction
          agent.inventoryWood = max(0, agent.inventoryWood - 1)
          let tree = Thing(kind: Tree, pos: targetPos)
          tree.inventory = emptyInventory()
          setInv(tree, ItemWood, ResourceNodeInitial)
          env.add(tree)
        else:
          if agent.inventoryWheat <= 0:
            inc env.stats[id].actionInvalid
            break plantResourceAction
          agent.inventoryWheat = max(0, agent.inventoryWheat - 1)
          let crop = Thing(kind: Wheat, pos: targetPos)
          crop.inventory = emptyInventory()
          setInv(crop, ItemWheat, ResourceNodeInitial)
          env.add(crop)

        env.terrain[targetPos.x][targetPos.y] = Empty
        env.resetTileColor(targetPos)
        env.updateObservations(ThingAgentLayer, targetPos, 0)

        # Consuming fertility (terrain replaced above)
        inc env.stats[id].actionPlantResource
    of 8:
      block buildFromChoices:
        let key = BuildChoices[argument]
        var buildKind: ThingKind
        let buildKindValid = parseThingKey(key, buildKind)
        let isDock = buildKindValid and buildKind == Dock

        # Check if building is disabled for this team
        if buildKindValid:
          let buildTeamId = getTeamId(agent)
          if buildTeamId >= 0 and buildTeamId < MapRoomObjectsTeams:
            if buildKind in env.teamModifiers[buildTeamId].disabledBuildings:
              invalidAndBreak(buildFromChoices)

        var offsets: array[9, IVec2]
        var offsetCount = 0
        for offset in [
          orientationToVec(agent.orientation),
          ivec2(0, -1), ivec2(1, 0), ivec2(0, 1), ivec2(-1, 0),
          ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1)
        ]:
          if offset.x == 0'i32 and offset.y == 0'i32:
            continue
          var duplicate = false
          for i in 0 ..< offsetCount:
            if offsets[i] == offset:
              duplicate = true
              break
          if duplicate:
            continue
          offsets[offsetCount] = offset
          inc offsetCount

        var targetPos = ivec2(-1, -1)
        for i in 0 ..< offsetCount:
          let offset = offsets[i]
          let pos = agent.pos + offset
          if (if isDock: env.canPlaceDock(pos) else: env.canPlace(pos)):
            targetPos = pos
            break
        if targetPos.x < 0:
          invalidAndBreak(buildFromChoices)

        let teamId = getTeamId(agent)
        var costs = buildCostsForKey(key)
        if costs.len == 0:
          invalidAndBreak(buildFromChoices)
        # Apply per-building cost multiplier
        if buildKindValid and teamId >= 0 and teamId < MapRoomObjectsTeams:
          let mult = env.teamModifiers[teamId].buildingCostMultiplier[buildKind]
          if mult != 0.0'f32 and mult != 1.0'f32:
            for i in 0 ..< costs.len:
              costs[i].count = max(1, int(float32(costs[i].count) * mult + 0.5))
        # Apply CivBonus wood/food cost multipliers for building costs
        if teamId >= 0 and teamId < MapRoomObjectsTeams:
          let civBonus = env.teamCivBonuses[teamId]
          for i in 0 ..< costs.len:
            let res = stockpileResourceForItem(costs[i].key)
            if res == ResourceWood and civBonus.woodCostMultiplier != 0.0'f32 and civBonus.woodCostMultiplier != 1.0'f32:
              costs[i].count = max(1, int(float32(costs[i].count) * civBonus.woodCostMultiplier + 0.5))
            elif res == ResourceFood and civBonus.foodCostMultiplier != 0.0'f32 and civBonus.foodCostMultiplier != 1.0'f32:
              costs[i].count = max(1, int(float32(costs[i].count) * civBonus.foodCostMultiplier + 0.5))
        let payment = choosePayment(env, agent, costs)
        if payment == PayNone:
          invalidAndBreak(buildFromChoices)

        var placedOk = false
        var placedKind: ThingKind
        var placedKindValid = false
        block placeThing:
          if isThingKey(key) and key.name == "Road":
            if not isBuildableTerrain(env.terrain[targetPos.x][targetPos.y]):
              break placeThing
            env.terrain[targetPos.x][targetPos.y] = Road
            env.resetTileColor(targetPos)
            env.updateObservations(ThingAgentLayer, targetPos, 0)
            placedOk = true
            break placeThing
          if not parseThingKey(key, placedKind):
            break placeThing
          placedKindValid = true
          let isBuilding = isBuildingKind(placedKind)
          let placed = Thing(
            kind: placedKind,
            pos: targetPos
          )
          if isBuilding and placedKind != Barrel:
            placed.teamId = getTeamId(agent)
          case placedKind
          of Lantern:
            placed.teamId = getTeamId(agent)
            placed.lanternHealthy = true
          of Altar:
            placed.inventory = emptyInventory()
            placed.hearts = 0
          of Spawner:
            placed.homeSpawner = targetPos
          else:
            discard
          if isBuilding:
            let capacity = buildingBarrelCapacity(placedKind)
            if capacity > 0:
              placed.barrelCapacity = capacity
          env.add(placed)
          # Apply Masonry and Architecture HP bonuses for buildings
          # Each tech grants +10% building HP
          if isBuilding and placed.maxHp > 0 and placed.teamId >= 0:
            var hpMultiplier = 1.0'f32
            if env.hasUniversityTech(placed.teamId, TechMasonry):
              hpMultiplier += 0.1
            if env.hasUniversityTech(placed.teamId, TechArchitecture):
              hpMultiplier += 0.1
            # Apply CivBonus building HP multiplier
            if placed.teamId < MapRoomObjectsTeams:
              let civBuildHp = env.teamCivBonuses[placed.teamId].buildingHpMultiplier
              if civBuildHp != 0.0'f32 and civBuildHp != 1.0'f32:
                hpMultiplier = hpMultiplier * civBuildHp
            if hpMultiplier > 1.0 or hpMultiplier < 1.0:
              placed.maxHp = max(1, int(float32(placed.maxHp) * hpMultiplier + 0.5))
          # Player-built buildings start under construction (hp=1)
          # They need villagers to complete construction
          if isBuilding and placed.maxHp > 0:
            placed.hp = 1
            placed.constructed = false
          if isBuilding:
            let radius = buildingFertileRadius(placedKind)
            if radius > 0:
              env.applyFertileRadius(placed.pos, radius)
          if isValidPos(targetPos):
            env.updateObservations(ThingAgentLayer, targetPos, 0)
          if placedKind == Altar:
            let teamId = placed.teamId
            if teamId >= 0 and teamId < env.teamColors.len:
              env.altarColors[targetPos] = env.teamColors[teamId]
          when defined(eventLog):
            if isBuilding:
              logEvent(
                ecBuildStart,
                placed.teamId,
                "Started building " & $placedKind & " at (" & $placed.pos.x & "," & $placed.pos.y & ")",
                env.currentStep,
              )
          placedOk = true

        if placedOk:
          discard spendCosts(env, agent, payment, costs)
          when defined(econAudit):
            if payment == PayStockpile:
              # Convert ItemKey costs to StockpileResource costs for tracking
              for cost in costs:
                let res = stockpileResourceForItem(cost.key)
                if res != ResourceNone:
                  recordFlow(teamId, res, -cost.count, rfsBuildingCost, env.currentStep)
          if placedKindValid and placedKind in {Mill, LumberCamp, MiningCamp}:
            # Use spatial query instead of O(n) scan for nearest team anchor
            var anchor = ivec2(-1, -1)
            var bestDist = int.high
            for kind in [TownCenter, Altar]:
              let nearest = findNearestFriendlyThingSpatial(env, targetPos, teamId, kind, 1000)
              if not nearest.isNil:
                let dist = abs(nearest.pos.x - targetPos.x) + abs(nearest.pos.y - targetPos.y)
                if dist < bestDist:
                  bestDist = dist
                  anchor = nearest.pos
            if anchor.x < 0:
              anchor = targetPos
            var pos = targetPos
            while pos.x != anchor.x:
              pos.x += (if anchor.x < pos.x: -1'i32 elif anchor.x > pos.x: 1'i32 else: 0'i32)
              if env.canPlace(pos, checkFrozen = false):
                env.terrain[pos.x][pos.y] = Road
                env.resetTileColor(pos)
                env.updateObservations(ThingAgentLayer, pos, 0)
            while pos.y != anchor.y:
              pos.y += (if anchor.y < pos.y: -1'i32 elif anchor.y > pos.y: 1'i32 else: 0'i32)
              if env.canPlace(pos, checkFrozen = false):
                env.terrain[pos.x][pos.y] = Road
                env.resetTileColor(pos)
                env.updateObservations(ThingAgentLayer, pos, 0)
          inc env.stats[id].actionBuild
        else:
          inc env.stats[id].actionInvalid
    of 9:
      block orientAction:
        ## Change orientation without moving.
        if argument < 0 or argument > 7:
          invalidAndBreak(orientAction)
        let newOrientation = Orientation(argument)
        if agent.orientation != newOrientation:
          agent.orientation = newOrientation
          env.updateObservations(AgentOrientationLayer, agent.pos, agent.orientation.int)
        inc env.stats[id].actionOrient
    of 10:
      block setRallyPointAction:
        ## Set rally point on an adjacent friendly building.
        ## The argument (0-7) is the direction toward the target building.
        ## The rally point is set to the agent's current position.
        if argument < 0 or argument > 7:
          invalidAndBreak(setRallyPointAction)
        let dir = Orientation(argument)
        let delta = orientationToVec(dir)
        let buildingPos = agent.pos + delta
        if not isValidPos(buildingPos):
          invalidAndBreak(setRallyPointAction)
        var thing = env.getThing(buildingPos)
        if isNil(thing) or not isBuildingKind(thing.kind):
          thing = env.getBackgroundThing(buildingPos)
        if isNil(thing) or not isBuildingKind(thing.kind):
          invalidAndBreak(setRallyPointAction)
        if thing.teamId != getTeamId(agent):
          invalidAndBreak(setRallyPointAction)
        thing.setRallyPoint(agent.pos)
        inc env.stats[id].actionSetRallyPoint
    else:
      inc env.stats[id].actionInvalid

  # Apply multi-builder construction/repair speed bonus
  # Repair uses RepairHpPerAction (faster), construction uses ConstructionHpPerAction
  # Treadmill Crane: +20% construction speed from University tech
  for pos, builderCount in env.constructionBuilders.pairs:
    var thing = env.getThing(pos)
    if thing.isNil:
      thing = env.getBackgroundThing(pos)
    if not thing.hasValue or thing.maxHp <= 0 or thing.hp >= thing.maxHp:
      continue
    # Calculate effective HP gain with diminishing returns
    # ConstructionBonusTable: [1.0, 1.0, 1.5, 1.83, 2.08, 2.28, 2.45, 2.59, 2.72]
    let tableIdx = min(builderCount, ConstructionBonusTable.high)
    var multiplier = ConstructionBonusTable[tableIdx]
    # Treadmill Crane: +20% construction speed
    if thing.teamId >= 0 and env.hasUniversityTech(thing.teamId, TechTreadmillCrane):
      multiplier = multiplier * 1.2'f32
    # Apply CivBonus build speed multiplier
    if thing.teamId >= 0 and thing.teamId < MapRoomObjectsTeams:
      let civBuild = env.teamCivBonuses[thing.teamId].buildSpeedMultiplier
      if civBuild != 0.0'f32 and civBuild != 1.0'f32:
        multiplier = multiplier * civBuild
    # Repair (previously constructed buildings) uses faster rate than initial construction
    let baseHp = if thing.constructed: RepairHpPerAction else: ConstructionHpPerAction
    let hpGain = int(float32(baseHp) * multiplier + 0.5)
    when defined(eventLog):
      let wasBelowMax = thing.hp < thing.maxHp
    when defined(audio):
      let wasBelowMaxAudio = thing.hp < thing.maxHp
    thing.hp = min(thing.maxHp, thing.hp + hpGain)
    # Mark building as constructed when it first reaches maxHp
    if thing.hp >= thing.maxHp:
      thing.constructed = true
    # Spawn construction dust particles while building is under construction
    if thing.hp < thing.maxHp:
      env.spawnConstructionDust(thing.pos)
    when defined(eventLog):
      if wasBelowMax and thing.hp >= thing.maxHp:
        logEvent(
          ecBuildDone,
          thing.teamId,
          "Completed " & $thing.kind & " at (" & $thing.pos.x & "," & $thing.pos.y & ")",
          env.currentStep,
        )
    when defined(audio):
      if wasBelowMaxAudio and thing.hp >= thing.maxHp:
        audioOnBuildingComplete(thing.pos)

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tActionsMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[3] = msBetweenPerfTiming(prfStart, prfNow)  # actions
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[3] = usBetween(fgStart, fgNow)  # actions
    fgStart = fgNow

  # Per-kind object updates: iterate each type separately for cache locality.
  # Same-type objects share field access patterns, so grouping them avoids
  # polymorphic dispatch overhead and reduces cache line waste from loading
  # irrelevant fields of mixed-type objects.
  env.tempTumorsToSpawn.setLen(0)
  env.tempTumorsToProcess.setLen(0)
  env.tempTowerRemovals.clear()

  # Pop caps already pre-computed at step start in env.stepTeamPopCaps

  # -------------------------------------------------------------------------
  # Building Updates
  # Each building type is processed separately for cache locality.
  # Defensive buildings attack enemies; production buildings spawn units.
  # -------------------------------------------------------------------------

  # Defensive buildings: process tower attacks first to populate tempTowerRemovals
  for thing in env.thingsByKind[GuardTower]:
    env.stepTryTowerAttack(thing, GuardTowerRange, env.tempTowerRemovals)

  for thing in env.thingsByKind[Castle]:
    env.stepTryTowerAttack(thing, CastleRange, env.tempTowerRemovals)

  for thing in env.thingsByKind[TownCenter]:
    env.stepTryTownCenterAttack(thing, env.tempTowerRemovals)

  # Resource and economy buildings
  for thing in env.thingsByKind[Altar]:
    if thing.cooldown > 0:
      thing.cooldown -= 1
    if env.currentStep == env.config.maxSteps:
      # Use teamVillagers cache instead of iterating all agents (O(team_villagers) vs O(all_agents))
      let teamId = thing.teamId
      if teamId >= 0 and teamId < MapRoomObjectsTeams:
        let altarHearts = thing.hearts.float32
        let perAgentReward = altarHearts / MapAgentsPerTeam.float32
        for agent in env.teamVillagers[teamId]:
          if agent.homeAltar == thing.pos:
            env.rewards[agent.agentId] += perAgentReward

  # Mill: cooldown + fertility + farm queue (complex logic, separate loop)
  for thing in env.thingsByKind[Mill]:
    if thing.cooldown > 0:
      thing.cooldown -= 1
    else:
      env.applyFertileRadius(thing.pos, max(0, buildingFertileRadius(thing.kind)))
      thing.cooldown = MillFertileCooldown
    if thing.farmQueue.len > 0:
      discard env.tryAutoReseedFarm(thing)

  # Monastery: relic gold generation (complex logic, separate loop)
  for thing in env.thingsByKind[Monastery]:
    if thing.garrisonedRelics > 0:
      if thing.cooldown > 0:
        dec thing.cooldown
      else:
        let teamId = thing.teamId
        if teamId >= 0 and teamId < MapRoomObjectsTeams:
          let goldAmount = thing.garrisonedRelics * MonasteryRelicGoldAmount
          env.teamStockpiles[teamId].counts[ResourceGold] += goldAmount
          when defined(econAudit):
            recordFlow(teamId, ResourceGold, goldAmount, rfsRelicGold, env.currentStep)
        thing.cooldown = MonasteryRelicGoldInterval
    else:
      if thing.cooldown > 0:
        dec thing.cooldown
    # Training queue for Monastery (no cooldown - handled above)
    if thing.constructed:
      thing.processProductionQueue()

  # Cooldown-only buildings: consolidated single loop for better instruction cache efficiency
  # Includes: Magma, Temple, economy tech buildings (ClayOven, WeavingLoom, Blacksmith, Market),
  # and drop-off buildings (LumberCamp, MiningCamp, Quarry, TownCenter)
  for kind in [Magma, Temple, ClayOven, WeavingLoom, Blacksmith, Market, LumberCamp, MiningCamp, Quarry, TownCenter]:
    for thing in env.thingsByKind[kind]:
      if thing.cooldown > 0:
        dec thing.cooldown

  # Production buildings with training queues (cooldown + queue processing)
  # Monastery excluded - handled above with relic gold logic
  for kind in [Barracks, ArcheryRange, Stable, SiegeWorkshop, MangonelWorkshop, TrebuchetWorkshop, Castle, Dock]:
    for thing in env.thingsByKind[kind]:
      if thing.cooldown > 0:
        dec thing.cooldown
      if thing.constructed:
        thing.processProductionQueue()

  # Hoist tower removal check outside loops for efficiency
  let hasTowerRemovals = env.tempTowerRemovals.len > 0

  # Spawners: check tempTowerRemovals since towers can target spawners
  for thing in env.thingsByKind[Spawner]:
    if hasTowerRemovals and thing in env.tempTowerRemovals:
      continue
    if thing.cooldown > 0:
      thing.cooldown -= 1
    else:
      let nearbyTumorCount = countUnclaimedTumorsInRangeSpatial(env, thing.pos, 5)
      if nearbyTumorCount < MaxTumorsPerSpawner and
          env.thingsByKind[Tumor].len < MaxGlobalTumors:
        let spawnPos = env.findFirstEmptyPositionAround(thing.pos, 2)
        if spawnPos.x >= 0:
          let newTumor = createTumor(env, spawnPos, thing.pos, stepRng)
          env.tempTumorsToSpawn.add(newTumor)
          when defined(tumorAudit):
            recordTumorSpawned()
          let cooldown = if env.config.tumorSpawnRate > 0.0:
            max(1, int(TumorSpawnCooldownBase / env.config.tumorSpawnRate))
          else:
            TumorSpawnDisabledCooldown
          thing.cooldown = cooldown

  # Agent state ticks (frozen, trebuchet cooldown)
  for thing in env.thingsByKind[Agent]:
    if thing.frozen > 0:
      thing.frozen -= 1
    if thing.unitClass == UnitTrebuchet and thing.cooldown > 0:
      thing.cooldown -= 1
      if thing.cooldown == 0:
        thing.packed = not thing.packed

  # Tumor collection: check tempTowerRemovals since towers can target tumors
  for thing in env.thingsByKind[Tumor]:
    if hasTowerRemovals and thing in env.tempTowerRemovals:
      continue
    if not thing.hasClaimedTerritory:
      env.tempTumorsToProcess.add(thing)

  # Pop cap clamping already done in pre-computation at step start

  if hasTowerRemovals:
    for target in env.tempTowerRemovals:
      removeThing(env, target)

  # -------------------------------------------------------------------------
  # Wildlife Movement (cows, wolves, bears)
  # -------------------------------------------------------------------------
  env.stepAnimalAI(stepRng)

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tThingsMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[4] = msBetweenPerfTiming(prfStart, prfNow)  # things
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[4] = usBetween(fgStart, fgNow)  # things
    fgStart = fgNow

  env.stepProcessTumors(env.tempTumorsToProcess, env.tempTumorsToSpawn, stepRng)

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tTumorsMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[5] = msBetweenPerfTiming(prfStart, prfNow)  # tumors
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[5] = usBetween(fgStart, fgNow)  # tumors
    fgStart = fgNow

  env.stepApplyTumorDamage(stepRng)

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tTumorDamageMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[6] = msBetweenPerfTiming(prfStart, prfNow)  # tumorDamage
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[6] = usBetween(fgStart, fgNow)  # tumorDamage
    fgStart = fgNow

  # Tank aura tints
  env.stepApplyTankAuras()

  # Monk aura tints + healing
  env.stepApplyMonkAuras()

  # Recharge monk faith over time
  env.stepRechargeMonkFaith()

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tAurasMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[7] = msBetweenPerfTiming(prfStart, prfNow)  # auras
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[7] = usBetween(fgStart, fgNow)  # auras
    fgStart = fgNow

  # Population respawn: altar respawn and temple hybrid spawn
  env.stepPopRespawn()

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tPopRespawnMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[8] = msBetweenPerfTiming(prfStart, prfNow)  # popRespawn
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[8] = usBetween(fgStart, fgNow)  # popRespawn
    fgStart = fgNow

  # Apply per-step survival penalty to all living agents
  env.stepApplySurvivalPenalty()

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tSurvivalMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[9] = msBetweenPerfTiming(prfStart, prfNow)  # survival
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[9] = usBetween(fgStart, fgNow)  # survival
    fgStart = fgNow

  # Update tint modifications and frozen tile cache
  # RGB color computation is deferred (lazy) until rendering or territory scoring.
  # Only frozen state is computed eagerly for game logic (isTileFrozen).
  env.updateTintModifications()  # Collect entity contributions, update frozen cache

  # Mark observations as dirty for lazy rebuilding
  # This replaces the previous approach of rebuilding every step. Now we only
  # rebuild when observations are actually accessed (via FFI or getObservations).
  # This saves O(agents * observation_tiles) work when observations aren't needed.
  env.observationsDirty = true

  # Spatial index is now maintained incrementally during position updates,
  # so no rebuild needed here. This eliminates O(things) work every step.

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tTintMs = msBetween(tStart, tNow)
      tStart = tNow

  when defined(perfRegression):
    prfNow = getMonoTime()
    prfSubsystems[10] = msBetweenPerfTiming(prfStart, prfNow)  # tintObs
    prfStart = prfNow

  when defined(flameGraph):
    fgNow = getMonoTime()
    fgSubsystems[10] = usBetween(fgStart, fgNow)  # tintObs
    fgStart = fgNow

  # Check victory conditions
  if env.config.victoryCondition != VictoryNone and env.victoryWinner < 0:
    env.checkVictoryConditions()

  # Check if episode should end (victory or time limit)
  if env.victoryWinner >= 0:
    if not env.territoryScored:
      env.territoryScore = env.scoreTerritory()
      env.territoryScored = true
    # Terminate losing teams, truncate winning teams (including allies) and award victory reward
    for i in 0..<MapAgents:
      if env.terminated[i] == 0.0:
        let teamId = getTeamId(i)
        if isTeamInMask(teamId, env.victoryWinners):
          env.rewards[i] += VictoryReward
          env.truncated[i] = 1.0  # Winners: episode ended (truncated, not dead)
        else:
          env.terminated[i] = 1.0  # Losers: eliminated
    env.shouldReset = true
  elif env.currentStep >= env.config.maxSteps:
    if not env.territoryScored:
      env.territoryScore = env.scoreTerritory()
      env.territoryScored = true
    # Team altar rewards already applied in main loop above
    # Mark all living agents as truncated (episode ended due to time limit)
    for i in 0..<MapAgents:
      if env.terminated[i] == 0.0:
        env.truncated[i] = 1.0
    env.shouldReset = true

  when defined(stepTiming):
    if timing:
      tNow = getMonoTime()
      tEndMs = msBetween(tStart, tNow)

      let totalMs = msBetween(tTotalStart, tNow)

      # Per-step echo (original behavior, only when step target is set)
      if perStepTiming:
        let countTumor = env.thingsByKind[Tumor].len
        let countCorpse = env.thingsByKind[Corpse].len
        let countSkeleton = env.thingsByKind[Skeleton].len
        let countCow = env.thingsByKind[Cow].len
        let countStump = env.thingsByKind[Stump].len

        echo "step=", env.currentStep,
          " total_ms=", totalMs,
          " actionTint_ms=", tActionTintMs,
          " shields_ms=", tShieldsMs,
          " preDeaths_ms=", tPreDeathsMs,
          " actions_ms=", tActionsMs,
          " things_ms=", tThingsMs,
          " tumor_ms=", tTumorsMs,
          " tumorDamage_ms=", tTumorDamageMs,
          " auras_ms=", tAurasMs,
          " pop_respawn_ms=", tPopRespawnMs,
          " survival_ms=", tSurvivalMs,
          " tint_ms=", tTintMs,
          " end_ms=", tEndMs,
          " things=", env.things.len,
          " agents=", env.agents.len,
          " tints=", env.actionTintPositions.len,
          " tumors=", countTumor,
          " corpses=", countCorpse,
          " skeletons=", countSkeleton,
          " cows=", countCow,
          " stumps=", countStump

      # Aggregate timing report
      if aggregateTiming:
        let systemMs = [tActionTintMs, tShieldsMs, tPreDeathsMs, tActionsMs,
                        tThingsMs, tTumorsMs, tTumorDamageMs, tAurasMs,
                        tPopRespawnMs, tSurvivalMs, tTintMs + tEndMs]
        for i in 0 ..< TimingSystemCount:
          recordTimingSample(i, systemMs[i])
        timingCumTotal += totalMs
        inc timingStepCount
        if timingStepCount >= stepTimingInterval:
          printTimingReport(env.currentStep)

  when defined(spatialStats):
    printSpatialReport()

  when defined(perfRegression):
    let prfTotal = msBetweenPerfTiming(prfTotalStart, getMonoTime())
    recordPerfStep(prfSubsystems, prfTotal)
    checkPerfRegression(env.currentStep)

  when defined(flameGraph):
    let fgTotalUs = usBetween(fgTotalStart, getMonoTime())
    recordFlameStep(env.currentStep, fgSubsystems, fgTotalUs)

  # Check if all agents are terminated/truncated
  var allDone = true
  for i in 0..<MapAgents:
    if env.terminated[i] == 0.0 and env.truncated[i] == 0.0:
      allDone = false
      break
  if allDone:
    # Team altar rewards already applied in main loop if needed
    if not env.territoryScored:
      env.territoryScore = env.scoreTerritory()
      env.territoryScored = true
    env.shouldReset = true

  # Sync contiguous rewards array back to agent objects for backward compatibility
  when defined(rewardBatch):
    let rbStart = getMonoTime()
  for i in 0 ..< MapAgents:
    env.agents[i].reward = env.rewards[i]
  when defined(rewardBatch):
    let rbEnd = getMonoTime()
    rewardBatchCumMs += rewardBatchMsBetween(rbStart, rbEnd)
    inc rewardBatchSteps
    if rewardBatchSteps >= RewardBatchReportInterval:
      reportRewardBatch()

  when defined(combatAudit):
    printCombatReport(env.currentStep)

  when defined(tumorAudit):
    env.printTumorReport()

  when defined(actionAudit):
    printActionAuditReport(env.currentStep)

  when defined(actionFreqCounter):
    printActionFreqReport(env.currentStep)

  when defined(eventLog):
    flushEventSummary(env.currentStep)

  when defined(settlerMetrics):
    if shouldUpdateMetrics(env.currentStep):
      updateSettlerMetrics(env)

  when defined(techAudit):
    maybePrintTechSummary(env, env.currentStep)

  when defined(econAudit):
    maybePrintEconDashboard(env, env.currentStep)

  when defined(stateDiff):
    comparePostStep(env)

  maybeLogReplayStep(env, actions)
  maybeDumpState(env)
  if env.shouldReset:
    maybeFinalizeReplay(env)

  if logRenderEnabled and (env.currentStep mod logRenderEvery == 0):
    var logEntry = "STEP " & $env.currentStep & "\n"
    var teamSeen: array[MapRoomObjectsTeams, bool]
    for agent in env.liveAgents:
      let teamId = getTeamId(agent)
      if teamId >= 0 and teamId < teamSeen.len:
        teamSeen[teamId] = true
    logEntry.add("Stockpiles:\n")
    for teamId, seen in teamSeen:
      if not seen:
        continue
      logEntry.add(
        "  t" & $teamId &
        " food=" & $env.stockpileCount(teamId, ResourceFood) &
        " wood=" & $env.stockpileCount(teamId, ResourceWood) &
        " stone=" & $env.stockpileCount(teamId, ResourceStone) &
        " gold=" & $env.stockpileCount(teamId, ResourceGold) & "\n"
      )
    logEntry.add("Agents:\n")
    for id, agent in env.liveAgentsWithId:
      let actionValue = actions[][id]
      let verb = actionValue.int div ActionArgumentCount
      let arg = actionValue.int mod ActionArgumentCount
      var invParts: seq[string] = @[]
      for key in ObservedItemKeys:
        let count = getInv(agent, key)
        if count > 0:
          invParts.add($key & "=" & $count)
      let invSummary = if invParts.len > 0: invParts.join(",") else: "-"
      logEntry.add(
        "  a" & $id &
        " t" & $getTeamId(agent) &
        " " & (case agent.agentId mod MapAgentsPerTeam:
          of 0, 1: "gatherer"
          of 2, 3: "builder"
          of 4, 5: "fighter"
          else: "gatherer") &
        " pos=(" & $agent.pos.x & "," & $agent.pos.y & ")" &
        " ori=" & $agent.orientation &
        " act=" & (case verb:
          of 0: "noop"
          of 1: "move"
          of 2: "attack"
          of 3: "use"
          of 4: "swap"
          of 5: "put"
          of 6: "plant_lantern"
          of 7: "plant_resource"
          of 8: "build"
          of 9: "orient"
          else: "unknown") & ":" &
        (if verb in [1, 2, 3, 9]:
          (case arg:
            of 0: "N"
            of 1: "S"
            of 2: "W"
            of 3: "E"
            of 4: "NW"
            of 5: "NE"
            of 6: "SW"
            of 7: "SE"
            else: $arg)
        else:
          $arg) &
        " hp=" & $agent.hp & "/" & $agent.maxHp &
        " inv=" & invSummary & "\n"
      )
    logEntry.add("Map:\n")
    logEntry.add(env.render())
    if logRenderBuffer.len < logRenderWindow:
      logRenderBuffer.add(logEntry)
    else:
      logRenderBuffer[logRenderHead] = logEntry
      logRenderHead = (logRenderHead + 1) mod logRenderWindow
    logRenderCount = min(logRenderBuffer.len, logRenderWindow)

    if logRenderCount > 0:
      var output = newStringOfCap(logRenderCount * 512)
      output.add("=== tribal-village log window (" & $logRenderCount & " steps) ===\n")
      for i in 0 ..< logRenderCount:
        let renderIdx = (logRenderHead + i) mod logRenderCount
        output.add(logRenderBuffer[renderIdx])
        output.add("\n")
      writeFile(logRenderPath, output)

  env.maybeRenderConsole()
  when defined(gatherHeatmap):
    env.maybeRenderGatherHeatmap()

proc reset*(env: Environment, seed: int = 0) =
  maybeFinalizeReplay(env)
  env.currentStep = 0
  env.shouldReset = false
  env.rewards.clear()
  env.terminated.clear()
  env.truncated.clear()
  env.things.setLen(0)
  env.agents.setLen(0)
  env.stats.setLen(0)
  env.templeInteractions.setLen(0)
  env.templeHybridRequests.setLen(0)
  env.grid.clear()
  # Skip env.observations.clear() - rebuildObservations will zero when accessed
  # This is a lazy init optimization to reduce startup overhead
  env.observationsInitialized = false
  env.observationsDirty = true
  # Clear tint arrays in-place via zeroMem (avoids stack-allocated default() copies)
  env.tintMods.clear()
  env.tintStrength.clear()
  env.activeTiles.positions.setLen(0)
  env.activeTiles.flags.clear()
  env.tumorTintMods.clear()
  env.tumorStrength.clear()
  env.tumorActiveTiles.positions.setLen(0)
  env.tumorActiveTiles.flags.clear()
  env.stepDirtyPositions.setLen(0)
  env.stepDirtyFlags.clear()
  env.resetVisualEffects()
  # Reset herd/pack tracking
  env.cowHerdCounts.setLen(0)
  env.cowHerdSumX.setLen(0)
  env.cowHerdSumY.setLen(0)
  env.cowHerdDrift.setLen(0)
  env.cowHerdTargets.setLen(0)
  env.wolfPackCounts.setLen(0)
  env.wolfPackSumX.setLen(0)
  env.wolfPackSumY.setLen(0)
  env.wolfPackDrift.setLen(0)
  env.wolfPackTargets.setLen(0)
  env.wolfPackLeaders.setLen(0)
  # Reset team state (upgrades, techs, modifiers persist across resets without this)
  env.teamModifiers.clear()
  env.teamBlacksmithUpgrades.clear()
  env.teamUniversityTechs.clear()
  env.teamCastleTechs.clear()
  env.teamUnitUpgrades.clear()
  env.teamEconomyTechs = default(array[MapRoomObjectsTeams, EconomyTechs])
  when defined(techAudit):
    resetTechAudit()
  # Clear colors
  env.agentColors.setLen(0)
  env.teamColors.setLen(0)
  env.altarColors.clear()
  env.territoryScore = default(TerritoryScore)
  env.territoryScored = false
  # Reset tribute tracking and town bell state
  env.teamTributesSent = default(array[MapRoomObjectsTeams, int])
  env.teamTributesReceived = default(array[MapRoomObjectsTeams, int])
  env.townBellActive = default(array[MapRoomObjectsTeams, bool])
  # Reset victory conditions
  env.resetVictoryState()
  # Clear fog of war (revealed maps) via zeroMem
  env.revealedMaps.clear()
  # Clear UI selection and control groups to prevent stale references
  selection = @[]
  for i in 0 ..< ControlGroupCount:
    controlGroups[i] = @[]
  # Reset formation state for all control groups
  resetAllFormations()
  env.init(seed)  # init() handles terrain, activeTiles, and tile colors
