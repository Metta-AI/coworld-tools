## Ultra-Fast Direct Buffer Interface
## Zero-copy numpy buffer communication - no conversions

import ./environment, agent_control

type
  ## C-compatible environment config passed from Python.
  ## Use NaN for float fields (or <=0 for maxSteps) to keep Nim defaults.
  CEnvironmentConfig* = object
    maxSteps*: int32
    victoryCondition*: int32  ## Maps to VictoryCondition enum (0=None, 1=Conquest, 2=Wonder, 3=Relic, 4=KingOfTheHill, 5=All)
    tumorSpawnRate*: float32
    heartReward*: float32
    oreReward*: float32
    barReward*: float32
    woodReward*: float32
    waterReward*: float32
    wheatReward*: float32
    spearReward*: float32
    armorReward*: float32
    foodReward*: float32
    clothReward*: float32
    tumorKillReward*: float32
    survivalPenalty*: float32
    deathPenalty*: float32

var globalEnv: Environment = nil

# --- AI Controller nil-check templates ---
# These eliminate repeated boilerplate for checking globalController.aiController

template checkAIController(defaultVal: typed) =
  ## Early return with defaultVal if AI controller is not initialized
  if isNil(globalController) or isNil(globalController.aiController):
    return defaultVal

template checkAIControllerVoid() =
  ## Early return if AI controller is not initialized (for void procs)
  if isNil(globalController) or isNil(globalController.aiController):
    return

const
  ObscuredLayerIndex = ord(ObscuredLayer)
  ObsTileStride = ObservationWidth * ObservationHeight
  ObsAgentStride = ObservationLayers * ObsTileStride

proc applyObscuredMask(env: Environment, obs_buffer: ptr UncheckedArray[uint8]) =
  ## Mask tiles above the observer elevation and mark the ObscuredLayer.
  let radius = ObservationRadius
  for agentId in 0 ..< MapAgents:
    let agent = env.agents[agentId]
    if not isAgentAlive(env, agent):
      continue
    let agentPos = agent.pos
    let baseElevation = env.elevation[agentPos.x][agentPos.y]
    let agentBase = agentId * ObsAgentStride
    for x in 0 ..< ObservationWidth:
      let worldX = agentPos.x + (x - radius)
      let xOffset = x * ObservationHeight
      for y in 0 ..< ObservationHeight:
        let worldY = agentPos.y + (y - radius)
        let inBounds = worldX >= 0 and worldX < MapWidth and worldY >= 0 and worldY < MapHeight
        let obscured = inBounds and env.elevation[worldX][worldY] > baseElevation
        let obscuredIndex = agentBase + ObscuredLayerIndex * ObsTileStride + xOffset + y
        obs_buffer[obscuredIndex] = (if obscured: 1'u8 else: 0'u8)
        if obscured:
          for layer in 0 ..< ObservationLayers:
            if layer == ObscuredLayerIndex:
              continue
            let bufferIdx = agentBase + layer * ObsTileStride + xOffset + y
            obs_buffer[bufferIdx] = 0

proc tribal_village_create(): pointer {.exportc, dynlib.} =
  ## Create environment for direct buffer interface
  try:
    let config = defaultEnvironmentConfig()
    globalEnv = newEnvironment(config)
    initGlobalController(ExternalNN)
    return cast[pointer](globalEnv)
  except CatchableError:
    return nil

proc tribal_village_set_ai_mode(mode: int32): int32 {.exportc, dynlib.} =
  ## Set the AI controller mode. Call after tribal_village_create, before reset.
  ## Mode 0 = ExternalNN (Python controls all actions — default for FFI)
  ## Mode 1 = BuiltinAI (scripted AI drives all behavior)
  ## Mode 2 = HybridAI (scripted AI runs, Python can override non-NOOP)
  ## Returns 1 on success, 0 on invalid mode.
  try:
    case mode:
    of 0:
      initGlobalController(ExternalNN)
      return 1
    of 1:
      initGlobalController(BuiltinAI)
      return 1
    of 2:
      initGlobalController(HybridAI)
      return 1
    else:
      return 0
  except CatchableError:
    return 0

proc tribal_village_set_config(
  env: pointer,
  cfg: ptr CEnvironmentConfig
): int32 {.exportc, dynlib.} =
  ## Update runtime config (rewards, spawn rates, max steps) from Python.
  try:
    discard env
    let incoming = cfg[]
    var config = defaultEnvironmentConfig()
    if incoming.maxSteps > 0:
      config.maxSteps = incoming.maxSteps.int
    if incoming.victoryCondition >= 0 and incoming.victoryCondition <= ord(VictoryAll):
      config.victoryCondition = VictoryCondition(incoming.victoryCondition)

    template applyFloat(field: untyped, value: float32) =
      if value == value:
        config.field = value.float

    applyFloat(tumorSpawnRate, incoming.tumorSpawnRate)
    applyFloat(heartReward, incoming.heartReward)
    applyFloat(oreReward, incoming.oreReward)
    applyFloat(barReward, incoming.barReward)
    applyFloat(woodReward, incoming.woodReward)
    applyFloat(waterReward, incoming.waterReward)
    applyFloat(wheatReward, incoming.wheatReward)
    applyFloat(spearReward, incoming.spearReward)
    applyFloat(armorReward, incoming.armorReward)
    applyFloat(foodReward, incoming.foodReward)
    applyFloat(clothReward, incoming.clothReward)
    applyFloat(tumorKillReward, incoming.tumorKillReward)
    applyFloat(survivalPenalty, incoming.survivalPenalty)
    applyFloat(deathPenalty, incoming.deathPenalty)
    globalEnv.config = config
    return 1
  except CatchableError:
    return 0

proc tribal_village_reset_and_get_obs(
  env: pointer,
  obs_buffer: ptr UncheckedArray[uint8],    # [MapAgents, ObservationLayers, 11, 11] direct
  rewards_buffer: ptr UncheckedArray[float32],
  terminals_buffer: ptr UncheckedArray[uint8],
  truncations_buffer: ptr UncheckedArray[uint8],
  seed: int32 = 0
): int32 {.exportc, dynlib.} =
  ## Reset and write directly to buffers - no conversions.
  ## When seed > 0, uses deterministic world generation; seed=0 uses current time.
  try:
    globalEnv.reset(int(seed))
    # Observations are lazily built - rebuild now since we're returning them
    globalEnv.ensureObservations()

    # Direct memory copy of observations (zero conversion)
    copyMem(obs_buffer, globalEnv.observations.addr,
      MapAgents * ObservationLayers * ObservationWidth * ObservationHeight)
    applyObscuredMask(globalEnv, obs_buffer)

    # Clear rewards/terminals/truncations
    for i in 0..<MapAgents:
      rewards_buffer[i] = 0.0
      terminals_buffer[i] = 0
      truncations_buffer[i] = 0

    return 1
  except CatchableError:
    return 0

proc tribal_village_step_with_pointers(
  env: pointer,
  actions_buffer: ptr UncheckedArray[uint16],   # [MapAgents] direct read
  obs_buffer: ptr UncheckedArray[uint8],        # [MapAgents, ObservationLayers, 11, 11] direct write
  rewards_buffer: ptr UncheckedArray[float32],
  terminals_buffer: ptr UncheckedArray[uint8],
  truncations_buffer: ptr UncheckedArray[uint8]
): int32 {.exportc, dynlib.} =
  ## Ultra-fast step with direct buffer access
  try:
    var actions: array[MapAgents, uint16]

    # When BuiltinAI or HybridAI is active, let the scripted AI generate actions
    # instead of reading from the Python buffer (which would be all-zeros/NOOPs).
    if not isNil(globalController) and
       globalController.controllerType in {BuiltinAI, HybridAI}:
      actions = getActions(globalEnv)
    else:
      # Read actions directly from buffer (no conversion)
      copyMem(addr actions[0], actions_buffer, sizeof(actions))

    # Step environment
    globalEnv.step(unsafeAddr actions)

    # Lazy rebuild: only rebuild observations if dirty and being accessed
    globalEnv.ensureObservations()

    # Direct memory copy of observations (zero conversion overhead)
    copyMem(obs_buffer, globalEnv.observations.addr,
      MapAgents * ObservationLayers * ObservationWidth * ObservationHeight)
    applyObscuredMask(globalEnv, obs_buffer)

    # Direct buffer writes from contiguous rewards array (SIMD-friendly)
    copyMem(rewards_buffer, globalEnv.rewards.addr, MapAgents * sizeof(float32))
    zeroMem(globalEnv.rewards.addr, MapAgents * sizeof(float32))
    for i in 0..<MapAgents:
      terminals_buffer[i] = if globalEnv.terminated[i] > 0.0: 1 else: 0
      truncations_buffer[i] = if globalEnv.truncated[i] > 0.0: 1 else: 0

    return 1
  except CatchableError:
    return 0

proc tribal_village_get_num_agents(): int32 {.exportc, dynlib.} =
  MapAgents.int32

proc tribal_village_get_obs_layers(): int32 {.exportc, dynlib.} =
  ObservationLayers.int32

proc tribal_village_get_obs_width(): int32 {.exportc, dynlib.} =
  ObservationWidth.int32


proc tribal_village_get_map_width(): int32 {.exportc, dynlib.} =
  MapWidth.int32

proc tribal_village_get_map_height(): int32 {.exportc, dynlib.} =
  MapHeight.int32

# Render full map as HxWx3 RGB (uint8)
proc toByte(value: float32): uint8 =
  let iv = max(0, min(255, int(value * 255.0)))
  uint8(iv)

proc tribal_village_render_rgb(
  env: pointer,
  out_buffer: ptr UncheckedArray[uint8],
  out_w: int32,
  out_h: int32
): int32 {.exportc, dynlib.} =
  # Ensure tint colors are up-to-date before rendering
  globalEnv.ensureTintColors()
  proc thingTintBytes(thing: Thing): tuple[r, g, b: uint8] =
    if isBuildingKind(thing.kind):
      let tint = BuildingRegistry[thing.kind].renderColor
      return (tint.r, tint.g, tint.b)
    case thing.kind
    of Agent: (255'u8, 255'u8, 0'u8)
    of Wall: (96'u8, 96'u8, 96'u8)
    of Tree: (34'u8, 139'u8, 34'u8)
    of Wheat: (200'u8, 180'u8, 90'u8)
    of Stubble: (175'u8, 150'u8, 70'u8)
    of Stone: (140'u8, 140'u8, 140'u8)
    of Gold: (220'u8, 190'u8, 80'u8)
    of Bush: (60'u8, 120'u8, 60'u8)
    of Cactus: (80'u8, 140'u8, 60'u8)
    of Stalagmite: (150'u8, 150'u8, 170'u8)
    of Magma: (0'u8, 200'u8, 200'u8)
    of Spawner: (255'u8, 170'u8, 0'u8)
    of Tumor: (160'u8, 32'u8, 240'u8)
    of Cow: (230'u8, 230'u8, 230'u8)
    of Bear: (140'u8, 90'u8, 40'u8)
    of Wolf: (130'u8, 130'u8, 130'u8)
    of Skeleton: (210'u8, 210'u8, 210'u8)
    of Stump: (110'u8, 85'u8, 55'u8)
    of Lantern: (255'u8, 240'u8, 128'u8)
    else: (180'u8, 180'u8, 180'u8)

  let width = int(out_w)
  let height = int(out_h)

  let scaleX = width div MapWidth
  let scaleY = height div MapHeight
  try:
    for y in 0 ..< MapHeight:
      for sy in 0 ..< scaleY:
        for x in 0 ..< MapWidth:
          let thing = globalEnv.grid[x][y]
          let (rByte, gByte, bByte) =
            if not isNil(thing):
              thingTintBytes(thing)
            elif globalEnv.actionTintCountdown[x][y] > 0:
              let tint = globalEnv.actionTintColor[x][y]
              (toByte(tint.r), toByte(tint.g), toByte(tint.b))
            else:
              let color = combinedTileTint(globalEnv, x, y)
              (toByte(color.r), toByte(color.g), toByte(color.b))

          let xBase = (y * scaleY + sy) * (width * 3) + x * scaleX * 3
          for sx in 0 ..< scaleX:
            let bufferIdx = xBase + sx * 3
            out_buffer[bufferIdx] = rByte
            out_buffer[bufferIdx + 1] = gByte
            out_buffer[bufferIdx + 2] = bByte
    return 1
  except CatchableError:
    return 0
proc tribal_village_get_obs_height(): int32 {.exportc, dynlib.} =
  ObservationHeight.int32

proc tribal_village_destroy(env: pointer) {.exportc, dynlib.} =
  ## Clean up environment
  when defined(flameGraph):
    closeFlameGraph()
  globalEnv = nil

# --- Rendering interface (ANSI) ---
proc tribal_village_render_ansi(
  env: pointer,
  out_buffer: ptr UncheckedArray[char],
  buf_len: int32
): int32 {.exportc, dynlib.} =
  ## Write an ANSI string render into out_buffer (null-terminated).
  ## Returns number of bytes written (excluding terminator). 0 on error.
  try:
    let rendered = render(globalEnv)  # environment.render*(env: Environment): string
    let n = min(rendered.len, max(0, buf_len - 1).int)
    copyMem(out_buffer, cast[pointer](rendered.cstring), n)
    out_buffer[n] = '\0'  # null-terminate
    return n.int32
  except CatchableError:
    return 0

# ============== FFI Error Query Functions ==============

proc tribal_village_has_error*(): int32 {.exportc, dynlib.} =
  ## Check if an error occurred during the last operation
  ## Returns 1 if error, 0 otherwise
  if lastFFIError.hasError: 1 else: 0

proc tribal_village_get_error_code*(): int32 {.exportc, dynlib.} =
  ## Get the error code from the last operation
  ## Returns the TribalErrorKind as an integer
  ord(lastFFIError.errorCode).int32

proc tribal_village_get_error_message*(buffer: ptr char, bufferSize: int32): int32 {.exportc, dynlib.} =
  ## Copy the error message to the provided buffer
  ## Returns the actual length written, or -1 if buffer too small
  let msg = lastFFIError.errorMessage
  if msg.len >= bufferSize:
    return -1
  if msg.len > 0:
    copyMem(buffer, unsafeAddr msg[0], msg.len)
  cast[ptr char](cast[uint](buffer) + msg.len.uint)[] = '\0'
  msg.len.int32

proc tribal_village_clear_error*() {.exportc, dynlib.} =
  ## Clear the error state
  clearFFIError()

# ============== Agent Control FFI Functions ==============

# --- Attack-Move ---

proc tribal_village_set_attack_move*(agentId: int32, x: int32, y: int32) {.exportc, dynlib.} =
  ## Set an attack-move target for an agent.
  setAgentAttackMoveTarget(agentId, ivec2(x, y))

proc tribal_village_clear_attack_move*(agentId: int32) {.exportc, dynlib.} =
  ## Clear the attack-move target for an agent.
  clearAgentAttackMoveTarget(agentId)

proc tribal_village_get_attack_move_x*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the x coordinate of an agent's attack-move target. -1 if inactive.
  getAgentAttackMoveTarget(agentId).x

proc tribal_village_get_attack_move_y*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the y coordinate of an agent's attack-move target. -1 if inactive.
  getAgentAttackMoveTarget(agentId).y

proc tribal_village_is_attack_move_active*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Check if an agent has an active attack-move target. Returns 1 if active, 0 otherwise.
  if isAgentAttackMoveActive(agentId): 1 else: 0

# --- Patrol ---

proc tribal_village_set_patrol*(agentId: int32, x1: int32, y1: int32, x2: int32, y2: int32) {.exportc, dynlib.} =
  ## Set patrol waypoints for an agent.
  setAgentPatrol(agentId, ivec2(x1, y1), ivec2(x2, y2))

proc tribal_village_clear_patrol*(agentId: int32) {.exportc, dynlib.} =
  ## Clear patrol mode for an agent.
  clearAgentPatrol(agentId)

proc tribal_village_get_patrol_target_x*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the x coordinate of an agent's current patrol target. -1 if inactive.
  getAgentPatrolTarget(agentId).x

proc tribal_village_get_patrol_target_y*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the y coordinate of an agent's current patrol target. -1 if inactive.
  getAgentPatrolTarget(agentId).y

proc tribal_village_is_patrol_active*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Check if an agent has patrol mode active. Returns 1 if active, 0 otherwise.
  if isAgentPatrolActive(agentId): 1 else: 0

# --- Stance ---

proc tribal_village_set_stance*(env: pointer, agentId: int32, stance: int32) {.exportc, dynlib.} =
  ## Set the combat stance for an agent.
  ## stance: 0=Aggressive, 1=Defensive, 2=StandGround, 3=NoAttack
  if stance >= 0 and stance <= ord(AgentStance.high):
    setAgentStance(globalEnv, agentId, AgentStance(stance))

proc tribal_village_get_stance*(env: pointer, agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the combat stance for an agent.
  ## Returns: 0=Aggressive, 1=Defensive, 2=StandGround, 3=NoAttack
  ord(getAgentStance(globalEnv, agentId)).int32

# --- Garrison ---

proc tribal_village_garrison*(env: pointer, agentId: int32, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Garrison an agent into a building. Returns 1 on success, 0 on failure.
  if garrisonAgentInBuilding(globalEnv, agentId, buildingX, buildingY): 1 else: 0

proc tribal_village_ungarrison*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Ungarrison all units from a building. Returns the number of units ungarrisoned.
  ungarrisonAllFromBuilding(globalEnv, buildingX, buildingY)

proc tribal_village_garrison_count*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Get the number of units garrisoned in a building.
  getGarrisonCount(globalEnv, buildingX, buildingY)

# --- Production Queue ---

proc tribal_village_queue_train*(env: pointer, buildingX: int32, buildingY: int32, teamId: int32): int32 {.exportc, dynlib.} =
  ## Queue a unit for training at a building. Returns 1 on success, 0 on failure.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if queueUnitTraining(globalEnv, buildingX, buildingY, teamId): 1 else: 0

proc tribal_village_cancel_train*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Cancel the last queued unit at a building. Returns 1 on success, 0 on failure.
  if cancelLastQueuedUnit(globalEnv, buildingX, buildingY): 1 else: 0

proc tribal_village_queue_size*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Get the number of units in the production queue at a building.
  getProductionQueueSize(globalEnv, buildingX, buildingY)

proc tribal_village_queue_progress*(env: pointer, buildingX: int32, buildingY: int32, index: int32): int32 {.exportc, dynlib.} =
  ## Get remaining steps for a production queue entry. Returns -1 if invalid.
  getProductionQueueEntryProgress(globalEnv, buildingX, buildingY, index)

proc tribal_village_can_train_unit*(env: pointer, buildingX: int32, buildingY: int32, unitClass: int32, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if a building can train the specified unit class. Returns 1 if yes, 0 if no.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if canBuildingTrainUnit(globalEnv, buildingX, buildingY, unitClass, teamId): 1 else: 0

proc tribal_village_queue_train_class*(env: pointer, buildingX: int32, buildingY: int32, teamId: int32, unitClass: int32): int32 {.exportc, dynlib.} =
  ## Queue a specific unit class for training. Validates building can train this class. Returns 1 on success, 0 on failure.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if queueUnitTrainingWithClass(globalEnv, buildingX, buildingY, teamId, unitClass): 1 else: 0

proc tribal_village_cancel_all_train*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Cancel all units in the production queue. Returns the number of units cancelled.
  cancelAllTrainingQueue(globalEnv, buildingX, buildingY)

proc tribal_village_queue_entry_unit_class*(env: pointer, buildingX: int32, buildingY: int32, index: int32): int32 {.exportc, dynlib.} =
  ## Get the unit class for a production queue entry. Returns -1 if invalid.
  getProductionQueueEntryUnitClass(globalEnv, buildingX, buildingY, index)

proc tribal_village_queue_entry_total_steps*(env: pointer, buildingX: int32, buildingY: int32, index: int32): int32 {.exportc, dynlib.} =
  ## Get the total training steps for a production queue entry. Returns -1 if invalid.
  getProductionQueueEntryTotalSteps(globalEnv, buildingX, buildingY, index)

proc tribal_village_queue_ready*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Check if the production queue has a ready entry. Returns 1 if ready, 0 if not.
  if isProductionQueueReady(globalEnv, buildingX, buildingY): 1 else: 0

# --- Research ---

proc tribal_village_research_blacksmith*(env: pointer, agentId: int32, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Research the next blacksmith upgrade. Returns 1 on success, 0 on failure.
  if researchBlacksmithUpgrade(globalEnv, agentId, buildingX, buildingY): 1 else: 0

proc tribal_village_research_university*(env: pointer, agentId: int32, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Research the next university tech. Returns 1 on success, 0 on failure.
  if researchUniversityTech(globalEnv, agentId, buildingX, buildingY): 1 else: 0

proc tribal_village_research_castle*(env: pointer, agentId: int32, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Research the next castle unique tech. Returns 1 on success, 0 on failure.
  if researchCastleTech(globalEnv, agentId, buildingX, buildingY): 1 else: 0

proc tribal_village_research_unit_upgrade*(env: pointer, agentId: int32, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Research the next unit upgrade. Returns 1 on success, 0 on failure.
  if researchUnitUpgrade(globalEnv, agentId, buildingX, buildingY): 1 else: 0

proc tribal_village_has_blacksmith_upgrade*(env: pointer, teamId: int32, upgradeType: int32): int32 {.exportc, dynlib.} =
  ## Get the current level of a blacksmith upgrade for a team.
  ## upgradeType: 0=MeleeAttack, 1=ArcherAttack, 2=InfantryArmor, 3=CavalryArmor, 4=ArcherArmor
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  hasBlacksmithUpgrade(globalEnv, teamId, upgradeType)

proc tribal_village_has_university_tech*(env: pointer, teamId: int32, techType: int32): int32 {.exportc, dynlib.} =
  ## Check if a university tech has been researched. Returns 1 if researched, 0 otherwise.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if hasUniversityTechResearched(globalEnv, teamId, techType): 1 else: 0

proc tribal_village_has_castle_tech*(env: pointer, teamId: int32, techType: int32): int32 {.exportc, dynlib.} =
  ## Check if a castle tech has been researched. Returns 1 if researched, 0 otherwise.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if hasCastleTechResearched(globalEnv, teamId, techType): 1 else: 0

proc tribal_village_has_unit_upgrade*(env: pointer, teamId: int32, upgradeType: int32): int32 {.exportc, dynlib.} =
  ## Check if a unit upgrade has been researched. Returns 1 if researched, 0 otherwise.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if hasUnitUpgradeResearched(globalEnv, teamId, upgradeType): 1 else: 0

# --- Scout Mode ---

proc tribal_village_set_scout_mode*(agentId: int32, active: int32) {.exportc, dynlib.} =
  ## Enable or disable scout mode for an agent. active: 1=enable, 0=disable.
  setAgentScoutMode(agentId, active != 0)

proc tribal_village_is_scout_mode_active*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Check if scout mode is active for an agent. Returns 1 if active, 0 otherwise.
  if isAgentScoutModeActive(agentId): 1 else: 0

proc tribal_village_get_scout_explore_radius*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the current scout exploration radius for an agent.
  getAgentScoutExploreRadius(agentId)

# --- Fog of War ---

proc tribal_village_is_tile_revealed*(env: pointer, teamId: int32, x: int32, y: int32): int32 {.exportc, dynlib.} =
  ## Check if a tile has been revealed by the specified team.
  ## Returns 1 if revealed, 0 otherwise.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if isRevealed(globalEnv, teamId, ivec2(x, y)): 1 else: 0

proc tribal_village_get_revealed_tile_count*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Count how many tiles have been revealed by a team (exploration progress).
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  getRevealedTileCount(globalEnv, teamId).int32

proc tribal_village_clear_revealed_map*(env: pointer, teamId: int32) {.exportc, dynlib.} =
  ## Clear the revealed map for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  clearRevealedMap(globalEnv, teamId)

# --- Rally Point ---

proc tribal_village_set_rally_point*(env: pointer, buildingX: int32, buildingY: int32, rallyX: int32, rallyY: int32) {.exportc, dynlib.} =
  ## Set a rally point for a building.
  setBuildingRallyPoint(globalEnv, buildingX, buildingY, rallyX, rallyY)

proc tribal_village_clear_rally_point*(env: pointer, buildingX: int32, buildingY: int32) {.exportc, dynlib.} =
  ## Clear the rally point for a building.
  clearBuildingRallyPoint(globalEnv, buildingX, buildingY)

proc tribal_village_get_rally_point_x*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Get the x coordinate of a building's rally point. -1 if not set.
  getBuildingRallyPoint(globalEnv, buildingX, buildingY).x

proc tribal_village_get_rally_point_y*(env: pointer, buildingX: int32, buildingY: int32): int32 {.exportc, dynlib.} =
  ## Get the y coordinate of a building's rally point. -1 if not set.
  getBuildingRallyPoint(globalEnv, buildingX, buildingY).y

# --- Stop Command ---

proc tribal_village_stop*(agentId: int32) {.exportc, dynlib.} =
  ## Stop an agent, clearing all active orders (attack-move, patrol, scout, hold, follow).
  stopAgent(agentId)

# --- Hold Position ---

proc tribal_village_hold_position*(agentId: int32, x: int32, y: int32) {.exportc, dynlib.} =
  ## Set hold position for an agent at the given coordinates.
  ## The agent stays at the position, attacks enemies in range, but won't chase.
  setAgentHoldPosition(agentId, ivec2(x, y))

proc tribal_village_clear_hold_position*(agentId: int32) {.exportc, dynlib.} =
  ## Clear hold position for an agent.
  clearAgentHoldPosition(agentId)

proc tribal_village_get_hold_position_x*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get x coordinate of hold position. -1 if not active.
  getAgentHoldPosition(agentId).x

proc tribal_village_get_hold_position_y*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get y coordinate of hold position. -1 if not active.
  getAgentHoldPosition(agentId).y

proc tribal_village_is_hold_position_active*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Check if hold position is active. Returns 1 if active, 0 if not.
  if isAgentHoldPositionActive(agentId): 1 else: 0

# --- Follow ---

proc tribal_village_follow_agent*(agentId: int32, targetAgentId: int32) {.exportc, dynlib.} =
  ## Set an agent to follow another agent.
  setAgentFollowTarget(agentId, targetAgentId)

proc tribal_village_clear_follow*(agentId: int32) {.exportc, dynlib.} =
  ## Clear follow target for an agent.
  clearAgentFollowTarget(agentId)

proc tribal_village_get_follow_target*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the follow target agent ID. -1 if not active.
  getAgentFollowTargetId(agentId).int32

proc tribal_village_is_follow_active*(agentId: int32): int32 {.exportc, dynlib.} =
  ## Check if follow mode is active. Returns 1 if active, 0 if not.
  if isAgentFollowActive(agentId): 1 else: 0

# --- Formation (per control group) ---

proc tribal_village_set_formation*(env: pointer, controlGroupId: int32, formationType: int32) {.exportc, dynlib.} =
  ## Set formation type for a control group.
  ## formationType: 0=None, 1=Line, 2=Box, 3=Wedge(reserved), 4=Scatter
  setControlGroupFormation(controlGroupId, formationType)

proc tribal_village_get_formation*(env: pointer, controlGroupId: int32): int32 {.exportc, dynlib.} =
  ## Get formation type for a control group.
  ## Returns: 0=None, 1=Line, 2=Box, 3=Wedge, 4=Scatter
  getControlGroupFormation(controlGroupId)

proc tribal_village_clear_formation*(env: pointer, controlGroupId: int32) {.exportc, dynlib.} =
  ## Clear formation for a control group.
  clearFormation(controlGroupId)

proc tribal_village_set_formation_rotation*(env: pointer, controlGroupId: int32, rotation: int32) {.exportc, dynlib.} =
  ## Set formation rotation for a control group (0-7 for 8 compass directions).
  setFormationRotation(controlGroupId, rotation.int)

proc tribal_village_get_formation_rotation*(env: pointer, controlGroupId: int32): int32 {.exportc, dynlib.} =
  ## Get formation rotation for a control group.
  getFormationRotation(controlGroupId).int32

# --- Market Trading ---

proc tribal_village_init_market_prices*(env: pointer) {.exportc, dynlib.} =
  ## Initialize market prices to base rates for all teams.
  initMarketPrices(globalEnv)

proc tribal_village_get_building_count*(env: pointer, teamId: int32, kindOrd: int32): int32 {.exportc, dynlib.} =
  ## Get count of buildings of a given kind owned by a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if kindOrd < 0 or kindOrd > ord(ThingKind.high):
    return 0
  let kind = ThingKind(kindOrd)
  var count = 0'i32
  for thing in globalEnv.thingsByKind[kind]:
    if thing.teamId == teamId:
      inc count
  count

proc tribal_village_get_stockpile*(env: pointer, teamId: int32, resource: int32): int32 {.exportc, dynlib.} =
  ## Get team stockpile count for a resource.
  ## resource: 0=Food, 1=Wood, 2=Gold, 3=Stone, 4=Water
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if resource < 0 or resource > ord(StockpileResource.high):
    return 0
  stockpileCount(globalEnv, teamId, StockpileResource(resource)).int32

proc tribal_village_get_market_price*(env: pointer, teamId: int32, resource: int32): int32 {.exportc, dynlib.} =
  ## Get current market price for a resource (gold cost per 100 units).
  ## resource: 0=Food, 1=Wood, 2=Gold, 3=Stone, 4=Water, 5=None
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if resource < 0 or resource > ord(StockpileResource.high):
    return 0
  getMarketPrice(globalEnv, teamId, StockpileResource(resource)).int32

proc tribal_village_set_market_price*(env: pointer, teamId: int32, resource: int32, price: int32) {.exportc, dynlib.} =
  ## Set market price for a resource (clamped to min/max bounds).
  ## resource: 0=Food, 1=Wood, 2=Gold, 3=Stone, 4=Water, 5=None
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if resource < 0 or resource > ord(StockpileResource.high):
    return
  setMarketPrice(globalEnv, teamId, StockpileResource(resource), price)

proc tribal_village_market_buy*(env: pointer, teamId: int32, resource: int32, amount: int32, outGoldCost: ptr int32, outResourceGained: ptr int32): int32 {.exportc, dynlib.} =
  ## Buy resources from market using gold from stockpile.
  ## Returns 1 on success, 0 on failure. Writes gold cost and resource gained to output pointers.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if resource < 0 or resource > ord(StockpileResource.high):
    return 0
  let buyResult = marketBuyResource(globalEnv, teamId, StockpileResource(resource), amount)
  if not outGoldCost.isNil:
    outGoldCost[] = buyResult.goldCost.int32
  if not outResourceGained.isNil:
    outResourceGained[] = buyResult.resourceGained.int32
  if buyResult.resourceGained > 0: 1 else: 0

proc tribal_village_market_sell*(env: pointer, teamId: int32, resource: int32, amount: int32, outResourceSold: ptr int32, outGoldGained: ptr int32): int32 {.exportc, dynlib.} =
  ## Sell resources to market for gold.
  ## Returns 1 on success, 0 on failure. Writes resource sold and gold gained to output pointers.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if resource < 0 or resource > ord(StockpileResource.high):
    return 0
  let sellResult = marketSellResource(globalEnv, teamId, StockpileResource(resource), amount)
  if not outResourceSold.isNil:
    outResourceSold[] = sellResult.resourceSold.int32
  if not outGoldGained.isNil:
    outGoldGained[] = sellResult.goldGained.int32
  if sellResult.goldGained > 0: 1 else: 0

proc tribal_village_market_sell_inventory*(env: pointer, agentId: int32, itemKind: int32, outAmountSold: ptr int32, outGoldGained: ptr int32): int32 {.exportc, dynlib.} =
  ## Sell all of an item from agent's inventory to their team's market.
  ## itemKind maps to ItemKind enum ordinal. Returns 1 on success, 0 on failure.
  if agentId < 0 or agentId >= MapAgents:
    return 0
  if itemKind < 0 or itemKind > ord(ItemKind.high):
    return 0
  let agent = globalEnv.agents[agentId]
  let itemKey = ItemKey(kind: ItemKeyItem, item: ItemKind(itemKind))
  let invSellResult = marketSellInventory(globalEnv, agent, itemKey)
  if not outAmountSold.isNil:
    outAmountSold[] = invSellResult.amountSold.int32
  if not outGoldGained.isNil:
    outGoldGained[] = invSellResult.goldGained.int32
  if invSellResult.goldGained > 0: 1 else: 0

proc tribal_village_market_buy_food*(env: pointer, agentId: int32, goldAmount: int32, outGoldSpent: ptr int32, outFoodGained: ptr int32): int32 {.exportc, dynlib.} =
  ## Buy food with gold from agent's inventory.
  ## Returns 1 on success, 0 on failure. Writes gold spent and food gained to output pointers.
  if agentId < 0 or agentId >= MapAgents:
    return 0
  let agent = globalEnv.agents[agentId]
  let foodBuyResult = marketBuyFood(globalEnv, agent, goldAmount)
  if not outGoldSpent.isNil:
    outGoldSpent[] = foodBuyResult.goldSpent.int32
  if not outFoodGained.isNil:
    outFoodGained[] = foodBuyResult.foodGained.int32
  if foodBuyResult.foodGained > 0: 1 else: 0

proc tribal_village_decay_market_prices*(env: pointer) {.exportc, dynlib.} =
  ## Slowly drift market prices back toward base rate.
  decayMarketPrices(globalEnv)

# --- Selection API ---

proc tribal_village_select_units*(env: pointer, agentIds: ptr int32, count: int32) {.exportc, dynlib.} =
  ## Replace current selection with the specified agent IDs.
  var ids: seq[int] = @[]
  for i in 0 ..< count:
    ids.add(int(cast[ptr UncheckedArray[int32]](agentIds)[i]))
  selectUnits(globalEnv, ids)

proc tribal_village_add_to_selection*(env: pointer, agentId: int32) {.exportc, dynlib.} =
  ## Add a single agent to the current selection.
  addToSelection(globalEnv, int(agentId))

proc tribal_village_remove_from_selection*(agentId: int32) {.exportc, dynlib.} =
  ## Remove a single agent from the current selection.
  removeFromSelection(int(agentId))

proc tribal_village_clear_selection*() {.exportc, dynlib.} =
  ## Clear the current selection.
  clearSelection()

proc tribal_village_get_selection_count*(): int32 {.exportc, dynlib.} =
  ## Get the number of currently selected units.
  int32(getSelectionCount())

proc tribal_village_get_selected_agent_id*(index: int32): int32 {.exportc, dynlib.} =
  ## Get the agent ID of a selected unit by index. Returns -1 if invalid.
  int32(getSelectedAgentId(int(index)))

# --- Control Group API ---

proc tribal_village_create_control_group*(env: pointer, groupIndex: int32, agentIds: ptr int32, count: int32) {.exportc, dynlib.} =
  ## Assign agents to a control group (0-9).
  var ids: seq[int] = @[]
  for i in 0 ..< count:
    ids.add(int(cast[ptr UncheckedArray[int32]](agentIds)[i]))
  createControlGroup(globalEnv, int(groupIndex), ids)

proc tribal_village_recall_control_group*(env: pointer, groupIndex: int32) {.exportc, dynlib.} =
  ## Recall a control group into the current selection.
  recallControlGroup(globalEnv, int(groupIndex))

proc tribal_village_get_control_group_count*(groupIndex: int32): int32 {.exportc, dynlib.} =
  ## Get the number of units in a control group.
  int32(getControlGroupCount(int(groupIndex)))

proc tribal_village_get_control_group_agent_id*(groupIndex: int32, index: int32): int32 {.exportc, dynlib.} =
  ## Get the agent ID at a position in a control group. Returns -1 if invalid.
  int32(getControlGroupAgentId(int(groupIndex), int(index)))

# --- Command to Selection ---

proc tribal_village_issue_command_to_selection*(env: pointer, commandType: int32, targetX: int32, targetY: int32) {.exportc, dynlib.} =
  ## Issue a command to all selected units.
  ## commandType: 0=attack-move, 1=patrol, 2=stop
  issueCommandToSelection(globalEnv, commandType, targetX, targetY)

# ============== Threat Map Query FFI Functions ==============

proc tribal_village_has_known_threats*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if a team has any known (non-stale) threats.
  ## Returns 1 if threats exist, 0 otherwise.
  try:
    checkAIController(0)
    let currentStep = globalEnv.currentStep.int32
    if hasKnownThreats(globalController.aiController, teamId.int, currentStep): 1 else: 0
  except CatchableError:
    return 0

proc tribal_village_get_nearest_threat*(env: pointer, agentId: int32,
    outX: ptr int32, outY: ptr int32, outStrength: ptr int32): int32 {.exportc, dynlib.} =
  ## Get the nearest threat to an agent's current position.
  ## Writes threat x, y, strength to output pointers.
  ## Returns 1 if a threat was found, 0 otherwise.
  try:
    checkAIController(0)
    if agentId < 0 or agentId >= MapAgents:
      return 0
    let agent = globalEnv.agents[agentId]
    if not isAgentAlive(globalEnv, agent):
      return 0
    let teamId = agent.getTeamId()
    let currentStep = globalEnv.currentStep.int32
    let (pos, _, found) = getNearestThreat(globalController.aiController, teamId, agent.pos, currentStep)
    if not found:
      return 0
    if not outX.isNil:
      outX[] = pos.x
    if not outY.isNil:
      outY[] = pos.y
    if not outStrength.isNil:
      # Look up the actual strength from the threat map entry
      let threats = getThreatsInRange(globalController.aiController, teamId, pos, 0, currentStep)
      outStrength[] = if threats.len > 0: threats[0].strength else: 0
    return 1
  except CatchableError:
    return 0

proc tribal_village_get_threats_in_range*(env: pointer, agentId: int32, radius: int32): int32 {.exportc, dynlib.} =
  ## Get the number of threats within radius of an agent's position.
  ## Returns the count of non-stale threats in range.
  try:
    checkAIController(0)
    if agentId < 0 or agentId >= MapAgents:
      return 0
    let agent = globalEnv.agents[agentId]
    if not isAgentAlive(globalEnv, agent):
      return 0
    let teamId = agent.getTeamId()
    let currentStep = globalEnv.currentStep.int32
    let threats = getThreatsInRange(globalController.aiController, teamId, agent.pos, radius, currentStep)
    return threats.len.int32
  except CatchableError:
    return 0

proc tribal_village_get_threat_at*(env: pointer, teamId: int32, x: int32, y: int32): int32 {.exportc, dynlib.} =
  ## Get the threat strength at a specific map position for a team.
  ## Returns the strength value, or 0 if no threat at that position.
  try:
    checkAIController(0)
    if teamId < 0 or teamId >= MapRoomObjectsTeams:
      return 0
    let currentStep = globalEnv.currentStep.int32
    let pos = ivec2(x, y)
    let threats = getThreatsInRange(globalController.aiController, teamId.int, pos, 0, currentStep)
    for entry in threats:
      if entry.pos == pos:
        return entry.strength
    return 0
  except CatchableError:
    return 0

# ============== Team Modifiers FFI Functions ==============

proc tribal_village_get_gather_rate_multiplier*(env: pointer, teamId: int32): float32 {.exportc, dynlib.} =
  ## Get the gather rate multiplier for a team. 1.0 = normal.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1.0'f32
  globalEnv.teamModifiers[teamId].gatherRateMultiplier

proc tribal_village_set_gather_rate_multiplier*(env: pointer, teamId: int32, value: float32) {.exportc, dynlib.} =
  ## Set the gather rate multiplier for a team. 1.0 = normal.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  globalEnv.teamModifiers[teamId].gatherRateMultiplier = value

proc tribal_village_get_build_cost_multiplier*(env: pointer, teamId: int32): float32 {.exportc, dynlib.} =
  ## Get the build cost multiplier for a team. 1.0 = normal.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1.0'f32
  globalEnv.teamModifiers[teamId].buildCostMultiplier

proc tribal_village_set_build_cost_multiplier*(env: pointer, teamId: int32, value: float32) {.exportc, dynlib.} =
  ## Set the build cost multiplier for a team. 1.0 = normal.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  globalEnv.teamModifiers[teamId].buildCostMultiplier = value

proc tribal_village_get_unit_hp_bonus*(env: pointer, teamId: int32, unitClass: int32): int32 {.exportc, dynlib.} =
  ## Get the bonus HP for a unit class on a team.
  ## unitClass: ordinal of AgentUnitClass enum.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return 0
  globalEnv.teamModifiers[teamId].unitHpBonus[AgentUnitClass(unitClass)].int32

proc tribal_village_set_unit_hp_bonus*(env: pointer, teamId: int32, unitClass: int32, bonus: int32) {.exportc, dynlib.} =
  ## Set the bonus HP for a unit class on a team.
  ## unitClass: ordinal of AgentUnitClass enum.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return
  globalEnv.teamModifiers[teamId].unitHpBonus[AgentUnitClass(unitClass)] = bonus.int

proc tribal_village_get_unit_attack_bonus*(env: pointer, teamId: int32, unitClass: int32): int32 {.exportc, dynlib.} =
  ## Get the bonus attack for a unit class on a team.
  ## unitClass: ordinal of AgentUnitClass enum.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return 0
  globalEnv.teamModifiers[teamId].unitAttackBonus[AgentUnitClass(unitClass)].int32

proc tribal_village_set_unit_attack_bonus*(env: pointer, teamId: int32, unitClass: int32, bonus: int32) {.exportc, dynlib.} =
  ## Set the bonus attack for a unit class on a team.
  ## unitClass: ordinal of AgentUnitClass enum.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return
  globalEnv.teamModifiers[teamId].unitAttackBonus[AgentUnitClass(unitClass)] = bonus.int

proc tribal_village_get_num_unit_classes*(): int32 {.exportc, dynlib.} =
  ## Get the number of AgentUnitClass values (for iterating over bonus arrays).
  int32(ord(AgentUnitClass.high) + 1)

# ============== Territory Scoring FFI Functions ==============

proc tribal_village_score_territory*(env: pointer) {.exportc, dynlib.} =
  ## Recompute territory scores. Results stored in env.territoryScore.
  globalEnv.territoryScore = globalEnv.scoreTerritory()

proc tribal_village_get_territory_team_tiles*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Get the number of tiles owned by a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  globalEnv.territoryScore.teamTiles[teamId].int32

proc tribal_village_get_territory_clippy_tiles*(env: pointer): int32 {.exportc, dynlib.} =
  ## Get the number of tiles owned by clippy (NPC).
  globalEnv.territoryScore.clippyTiles.int32

proc tribal_village_get_territory_neutral_tiles*(env: pointer): int32 {.exportc, dynlib.} =
  ## Get the number of neutral (unclaimed) tiles.
  globalEnv.territoryScore.neutralTiles.int32

proc tribal_village_get_territory_scored_tiles*(env: pointer): int32 {.exportc, dynlib.} =
  ## Get the total number of scored tiles.
  globalEnv.territoryScore.scoredTiles.int32

proc tribal_village_get_num_teams*(): int32 {.exportc, dynlib.} =
  ## Get the number of teams (MapRoomObjectsTeams).
  MapRoomObjectsTeams.int32

# ============== AI Difficulty Control FFI Functions ==============

proc tribal_village_get_difficulty_level*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Get the difficulty level for a team.
  ## Returns ordinal: 0=Easy, 1=Normal, 2=Hard, 3=Brutal
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1  # Default to Normal
  checkAIController(1)
  ord(globalController.aiController.getDifficulty(teamId.int).level).int32

proc tribal_village_set_difficulty_level*(env: pointer, teamId: int32, level: int32) {.exportc, dynlib.} =
  ## Set the difficulty level for a team.
  ## level: 0=Easy, 1=Normal, 2=Hard, 3=Brutal
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  if level < 0 or level > ord(DifficultyLevel.high):
    return
  globalController.aiController.setDifficulty(teamId.int, DifficultyLevel(level))

proc tribal_village_get_difficulty*(env: pointer, teamId: int32): float32 {.exportc, dynlib.} =
  ## Get the difficulty for a team as a float.
  ## Returns: 0.0=Easy, 1.0=Normal, 2.0=Hard, 3.0=Brutal
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1.0'f32  # Default to Normal
  checkAIController(1.0'f32)
  float32(ord(globalController.aiController.getDifficulty(teamId.int).level))

proc tribal_village_set_difficulty*(env: pointer, teamId: int32, difficulty: float32) {.exportc, dynlib.} =
  ## Set the difficulty for a team using a float value.
  ## difficulty: 0.0=Easy, 1.0=Normal, 2.0=Hard, 3.0=Brutal (rounded to nearest)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  let levelInt = clamp(int(difficulty + 0.5), 0, ord(DifficultyLevel.high))
  globalController.aiController.setDifficulty(teamId.int, DifficultyLevel(levelInt))

proc tribal_village_set_adaptive_difficulty*(env: pointer, teamId: int32, enabled: int32) {.exportc, dynlib.} =
  ## Enable or disable adaptive difficulty for a team.
  ## enabled: 1=enable (with default 0.5 territory target), 0=disable
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  if enabled != 0:
    globalController.aiController.enableAdaptiveDifficulty(teamId.int, 0.5'f32)
  else:
    globalController.aiController.disableAdaptiveDifficulty(teamId.int)

proc tribal_village_get_decision_delay_chance*(env: pointer, teamId: int32): float32 {.exportc, dynlib.} =
  ## Get the decision delay chance for a team (0.0-1.0).
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0.1  # Default to Normal (10%)
  checkAIController(0.1)
  globalController.aiController.getDifficulty(teamId.int).decisionDelayChance

proc tribal_village_set_decision_delay_chance*(env: pointer, teamId: int32, chance: float32) {.exportc, dynlib.} =
  ## Set a custom decision delay chance for a team (0.0-1.0).
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  globalController.aiController.difficulty[teamId].decisionDelayChance = clamp(chance, 0.0'f32, 1.0'f32)

proc tribal_village_enable_adaptive_difficulty*(env: pointer, teamId: int32, targetTerritory: float32) {.exportc, dynlib.} =
  ## Enable adaptive difficulty for a team.
  ## targetTerritory: target territory percentage (0.0-1.0, typically 0.5 for balanced)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  globalController.aiController.enableAdaptiveDifficulty(teamId.int, clamp(targetTerritory, 0.0'f32, 1.0'f32))

proc tribal_village_disable_adaptive_difficulty*(env: pointer, teamId: int32) {.exportc, dynlib.} =
  ## Disable adaptive difficulty for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  globalController.aiController.disableAdaptiveDifficulty(teamId.int)

proc tribal_village_is_adaptive_difficulty_enabled*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if adaptive difficulty is enabled for a team.
  ## Returns 1 if enabled, 0 if disabled.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  checkAIController(0)
  if globalController.aiController.getDifficulty(teamId.int).adaptive: 1 else: 0

proc tribal_village_get_adaptive_difficulty_target*(env: pointer, teamId: int32): float32 {.exportc, dynlib.} =
  ## Get the target territory percentage for adaptive difficulty.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0.5
  checkAIController(0.5)
  globalController.aiController.getDifficulty(teamId.int).adaptiveTarget

proc tribal_village_get_threat_response_enabled*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if threat response is enabled for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  checkAIController(0)
  if globalController.aiController.getDifficulty(teamId.int).threatResponseEnabled: 1 else: 0

proc tribal_village_set_threat_response_enabled*(env: pointer, teamId: int32, enabled: int32) {.exportc, dynlib.} =
  ## Enable or disable threat response for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  globalController.aiController.difficulty[teamId].threatResponseEnabled = enabled != 0

proc tribal_village_get_advanced_targeting_enabled*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if advanced targeting is enabled for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  checkAIController(0)
  if globalController.aiController.getDifficulty(teamId.int).advancedTargetingEnabled: 1 else: 0

proc tribal_village_set_advanced_targeting_enabled*(env: pointer, teamId: int32, enabled: int32) {.exportc, dynlib.} =
  ## Enable or disable advanced targeting for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  globalController.aiController.difficulty[teamId].advancedTargetingEnabled = enabled != 0

proc tribal_village_get_coordination_enabled*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if coordination is enabled for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  checkAIController(0)
  if globalController.aiController.getDifficulty(teamId.int).coordinationEnabled: 1 else: 0

proc tribal_village_set_coordination_enabled*(env: pointer, teamId: int32, enabled: int32) {.exportc, dynlib.} =
  ## Enable or disable coordination for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  globalController.aiController.difficulty[teamId].coordinationEnabled = enabled != 0

proc tribal_village_get_optimal_build_order_enabled*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if optimal build order is enabled for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  checkAIController(0)
  if globalController.aiController.getDifficulty(teamId.int).optimalBuildOrderEnabled: 1 else: 0

proc tribal_village_set_optimal_build_order_enabled*(env: pointer, teamId: int32, enabled: int32) {.exportc, dynlib.} =
  ## Enable or disable optimal build order for a team.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  checkAIControllerVoid()
  globalController.aiController.difficulty[teamId].optimalBuildOrderEnabled = enabled != 0

# ============== Building/Unit Availability Configuration FFI Functions ==============

proc tribal_village_set_building_enabled*(env: pointer, teamId: int32, buildingKind: int32, enabled: int32) {.exportc, dynlib.} =
  ## Enable or disable a building type for a team.
  ## buildingKind: ordinal of ThingKind enum
  ## enabled: 1=enabled (can build), 0=disabled (cannot build)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if buildingKind < 0 or buildingKind > ord(ThingKind.high):
    return
  let kind = ThingKind(buildingKind)
  if enabled != 0:
    globalEnv.teamModifiers[teamId].disabledBuildings.excl(kind)
  else:
    globalEnv.teamModifiers[teamId].disabledBuildings.incl(kind)

proc tribal_village_is_building_enabled*(env: pointer, teamId: int32, buildingKind: int32): int32 {.exportc, dynlib.} =
  ## Check if a building type is enabled for a team.
  ## Returns 1 if enabled, 0 if disabled.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1  # Default to enabled
  if buildingKind < 0 or buildingKind > ord(ThingKind.high):
    return 1
  let kind = ThingKind(buildingKind)
  if kind in globalEnv.teamModifiers[teamId].disabledBuildings: 0 else: 1

proc tribal_village_set_unit_enabled*(env: pointer, teamId: int32, unitClass: int32, enabled: int32) {.exportc, dynlib.} =
  ## Enable or disable a unit class for a team.
  ## unitClass: ordinal of AgentUnitClass enum
  ## enabled: 1=enabled (can train), 0=disabled (cannot train)
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return
  let uc = AgentUnitClass(unitClass)
  if enabled != 0:
    globalEnv.teamModifiers[teamId].disabledUnits.excl(uc)
  else:
    globalEnv.teamModifiers[teamId].disabledUnits.incl(uc)

proc tribal_village_is_unit_enabled*(env: pointer, teamId: int32, unitClass: int32): int32 {.exportc, dynlib.} =
  ## Check if a unit class is enabled for a team.
  ## Returns 1 if enabled, 0 if disabled.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1  # Default to enabled
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return 1
  let uc = AgentUnitClass(unitClass)
  if uc in globalEnv.teamModifiers[teamId].disabledUnits: 0 else: 1

proc tribal_village_set_unit_base_hp*(env: pointer, teamId: int32, unitClass: int32, baseHp: int32) {.exportc, dynlib.} =
  ## Set the base HP for a unit class on a team.
  ## baseHp: 0 = use default, >0 = override value
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return
  globalEnv.teamModifiers[teamId].unitBaseHpOverride[AgentUnitClass(unitClass)] = max(0, baseHp.int)

proc tribal_village_get_unit_base_hp*(env: pointer, teamId: int32, unitClass: int32): int32 {.exportc, dynlib.} =
  ## Get the base HP override for a unit class on a team.
  ## Returns 0 if using default, >0 if overridden.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return 0
  globalEnv.teamModifiers[teamId].unitBaseHpOverride[AgentUnitClass(unitClass)].int32

proc tribal_village_set_unit_base_attack*(env: pointer, teamId: int32, unitClass: int32, baseAttack: int32) {.exportc, dynlib.} =
  ## Set the base attack for a unit class on a team.
  ## baseAttack: 0 = use default, >0 = override value
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return
  globalEnv.teamModifiers[teamId].unitBaseAttackOverride[AgentUnitClass(unitClass)] = max(0, baseAttack.int)

proc tribal_village_get_unit_base_attack*(env: pointer, teamId: int32, unitClass: int32): int32 {.exportc, dynlib.} =
  ## Get the base attack override for a unit class on a team.
  ## Returns 0 if using default, >0 if overridden.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return 0
  globalEnv.teamModifiers[teamId].unitBaseAttackOverride[AgentUnitClass(unitClass)].int32

proc tribal_village_set_building_cost_multiplier*(env: pointer, teamId: int32, buildingKind: int32, multiplier: float32) {.exportc, dynlib.} =
  ## Set the cost multiplier for a building type on a team.
  ## multiplier: 1.0 = normal cost, 0.5 = half cost, 2.0 = double cost
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if buildingKind < 0 or buildingKind > ord(ThingKind.high):
    return
  globalEnv.teamModifiers[teamId].buildingCostMultiplier[ThingKind(buildingKind)] = max(0.0'f32, multiplier)

proc tribal_village_get_building_cost_multiplier*(env: pointer, teamId: int32, buildingKind: int32): float32 {.exportc, dynlib.} =
  ## Get the cost multiplier for a building type on a team.
  ## Returns 1.0 if normal cost.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1.0'f32
  if buildingKind < 0 or buildingKind > ord(ThingKind.high):
    return 1.0'f32
  let mult = globalEnv.teamModifiers[teamId].buildingCostMultiplier[ThingKind(buildingKind)]
  if mult == 0.0'f32: 1.0'f32 else: mult

proc tribal_village_set_train_cost_multiplier*(env: pointer, teamId: int32, unitClass: int32, multiplier: float32) {.exportc, dynlib.} =
  ## Set the training cost multiplier for a unit class on a team.
  ## multiplier: 1.0 = normal cost, 0.5 = half cost, 2.0 = double cost
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return
  globalEnv.teamModifiers[teamId].trainCostMultiplier[AgentUnitClass(unitClass)] = max(0.0'f32, multiplier)

proc tribal_village_get_train_cost_multiplier*(env: pointer, teamId: int32, unitClass: int32): float32 {.exportc, dynlib.} =
  ## Get the training cost multiplier for a unit class on a team.
  ## Returns 1.0 if normal cost.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 1.0'f32
  if unitClass < 0 or unitClass > ord(AgentUnitClass.high):
    return 1.0'f32
  let mult = globalEnv.teamModifiers[teamId].trainCostMultiplier[AgentUnitClass(unitClass)]
  if mult == 0.0'f32: 1.0'f32 else: mult

proc tribal_village_get_num_building_kinds*(): int32 {.exportc, dynlib.} =
  ## Get the number of ThingKind values (for iterating over building types).
  int32(ord(ThingKind.high) + 1)

# --- Economy Priority Override API ---

proc tribal_village_set_gatherer_priority*(env: pointer, agentId: int32, resource: int32) {.exportc, dynlib.} =
  ## Set an individual gatherer to prioritize collecting a specific resource.
  ## resource: 0=Food, 1=Wood, 2=Gold, 3=Stone
  if resource < 0 or resource > ord(StockpileResource.high).int32:
    return
  setGathererPriority(agentId, StockpileResource(resource))

proc tribal_village_clear_gatherer_priority*(env: pointer, agentId: int32) {.exportc, dynlib.} =
  ## Clear the individual gatherer priority override.
  clearGathererPriority(agentId)

proc tribal_village_get_gatherer_priority*(env: pointer, agentId: int32): int32 {.exportc, dynlib.} =
  ## Get the current gatherer priority for an agent.
  ## Returns -1 if no priority is set, otherwise 0=Food, 1=Wood, 2=Gold, 3=Stone
  let resource = getGathererPriority(agentId)
  if resource == ResourceNone:
    return -1
  ord(resource).int32

proc tribal_village_is_gatherer_priority_active*(env: pointer, agentId: int32): int32 {.exportc, dynlib.} =
  ## Check if an individual gatherer priority is active.
  ## Returns 1 if active, 0 if not.
  if isGathererPriorityActive(agentId): 1 else: 0

proc tribal_village_set_team_economy_focus*(env: pointer, teamId: int32, resource: int32) {.exportc, dynlib.} =
  ## Set a team-level economy focus to bias all gatherers toward a resource.
  ## resource: 0=Food, 1=Wood, 2=Gold, 3=Stone
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  if resource < 0 or resource > ord(StockpileResource.high).int32:
    return
  setTeamEconomyFocus(teamId, StockpileResource(resource))

proc tribal_village_clear_team_economy_focus*(env: pointer, teamId: int32) {.exportc, dynlib.} =
  ## Clear the team-level economy focus.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return
  clearTeamEconomyFocus(teamId)

proc tribal_village_get_team_economy_focus*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Get the current team economy focus.
  ## Returns -1 if no focus is set, otherwise 0=Food, 1=Wood, 2=Gold, 3=Stone
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return -1
  let resource = getTeamEconomyFocus(teamId)
  if resource == ResourceNone:
    return -1
  ord(resource).int32

proc tribal_village_is_team_economy_focus_active*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Check if a team economy focus is active.
  ## Returns 1 if active, 0 if not.
  if teamId < 0 or teamId >= MapRoomObjectsTeams:
    return 0
  if isTeamEconomyFocusActive(teamId): 1 else: 0

# --- Civilization Bonus API ---

type
  CCivBonus* = object
    ## C-compatible CivBonus structure for FFI.
    gatherRateMultiplier*: float32
    buildSpeedMultiplier*: float32
    unitHpMultiplier*: float32
    unitAttackMultiplier*: float32
    buildingHpMultiplier*: float32
    woodCostMultiplier*: float32
    foodCostMultiplier*: float32

proc tribal_village_set_civ_bonus*(env: pointer, teamId: int32, bonus: ptr CCivBonus): int32 {.exportc, dynlib.} =
  ## Set the civilization bonus for a team.
  ## All multiplier fields default to 1.0 (no effect).
  ## Returns 1 on success, 0 on failure.
  try:
    if teamId < 0 or teamId >= MapRoomObjectsTeams:
      return 0
    if isNil(globalEnv):
      return 0
    let b = bonus[]
    globalEnv.teamCivBonuses[teamId] = CivBonus(
      gatherRateMultiplier: b.gatherRateMultiplier,
      buildSpeedMultiplier: b.buildSpeedMultiplier,
      unitHpMultiplier: b.unitHpMultiplier,
      unitAttackMultiplier: b.unitAttackMultiplier,
      buildingHpMultiplier: b.buildingHpMultiplier,
      woodCostMultiplier: b.woodCostMultiplier,
      foodCostMultiplier: b.foodCostMultiplier
    )
    return 1
  except CatchableError:
    return 0

proc tribal_village_get_civ_bonus*(env: pointer, teamId: int32, bonus: ptr CCivBonus): int32 {.exportc, dynlib.} =
  ## Get the current civilization bonus for a team.
  ## Returns 1 on success, 0 on failure.
  try:
    if teamId < 0 or teamId >= MapRoomObjectsTeams:
      return 0
    if isNil(globalEnv):
      return 0
    let cb = globalEnv.teamCivBonuses[teamId]
    bonus[].gatherRateMultiplier = cb.gatherRateMultiplier
    bonus[].buildSpeedMultiplier = cb.buildSpeedMultiplier
    bonus[].unitHpMultiplier = cb.unitHpMultiplier
    bonus[].unitAttackMultiplier = cb.unitAttackMultiplier
    bonus[].buildingHpMultiplier = cb.buildingHpMultiplier
    bonus[].woodCostMultiplier = cb.woodCostMultiplier
    bonus[].foodCostMultiplier = cb.foodCostMultiplier
    return 1
  except CatchableError:
    return 0

proc tribal_village_reset_civ_bonus*(env: pointer, teamId: int32): int32 {.exportc, dynlib.} =
  ## Reset the civilization bonus for a team to neutral (all 1.0).
  ## Returns 1 on success, 0 on failure.
  try:
    if teamId < 0 or teamId >= MapRoomObjectsTeams:
      return 0
    if isNil(globalEnv):
      return 0
    globalEnv.teamCivBonuses[teamId] = defaultCivBonus()
    return 1
  except CatchableError:
    return 0

# ============== Environment Info FFI Functions ==============
# Environment-aware lazy initialization pattern (mettascope-style)
# Allows external callers to query and validate environment dimensions

type
  CEnvironmentInfo* = object
    ## C-compatible environment info structure for FFI.
    ## Contains runtime environment parameters for lazy initialization.
    mapWidth*: int32
    mapHeight*: int32
    obsWidth*: int32
    obsHeight*: int32
    obsLayers*: int32
    numAgents*: int32
    numTeams*: int32
    agentsPerTeam*: int32
    numActionVerbs*: int32
    numActionArgs*: int32
    numActions*: int32

proc tribal_village_get_env_info*(info: ptr CEnvironmentInfo): int32 {.exportc, dynlib.} =
  ## Get current environment info (compile-time dimensions).
  ## Writes environment parameters to the provided struct.
  ## Returns 1 on success, 0 on failure.
  ##
  ## This enables external callers (Python/neural networks) to query
  ## environment dimensions for policy initialization and portability.
  try:
    if info.isNil:
      return 0
    info[].mapWidth = MapWidth.int32
    info[].mapHeight = MapHeight.int32
    info[].obsWidth = ObservationWidth.int32
    info[].obsHeight = ObservationHeight.int32
    info[].obsLayers = ObservationLayers.int32
    info[].numAgents = MapAgents.int32
    info[].numTeams = MapRoomObjectsTeams.int32
    info[].agentsPerTeam = MapAgentsPerTeam.int32
    info[].numActionVerbs = ActionVerbCount.int32
    info[].numActionArgs = ActionArgumentCount.int32
    info[].numActions = int32(ActionVerbCount * ActionArgumentCount)
    return 1
  except CatchableError:
    return 0

proc tribal_village_validate_env_info*(info: ptr CEnvironmentInfo): int32 {.exportc, dynlib.} =
  ## Validate that provided environment info matches compile-time dimensions.
  ## Returns 1 if compatible, 0 if incompatible.
  ##
  ## This is the FFI equivalent of Controller.initializeToEnvironment() validation.
  ## Use this to check if a pre-trained policy is compatible with this environment.
  try:
    if info.isNil:
      return 0
    if info[].mapWidth != MapWidth.int32:
      return 0
    if info[].mapHeight != MapHeight.int32:
      return 0
    if info[].numAgents != MapAgents.int32:
      return 0
    if info[].numTeams != MapRoomObjectsTeams.int32:
      return 0
    if info[].obsWidth != ObservationWidth.int32:
      return 0
    if info[].obsHeight != ObservationHeight.int32:
      return 0
    if info[].obsLayers != ObservationLayers.int32:
      return 0
    return 1
  except CatchableError:
    return 0

proc tribal_village_initialize_controller_to_env*(
  env: pointer,
  numAgents: int32,
  numTeams: int32,
  mapWidth: int32,
  mapHeight: int32,
  outMessage: ptr char,
  messageSize: int32
): int32 {.exportc, dynlib.} =
  ## Initialize the AI controller to runtime environment parameters.
  ## Returns 1 on success, 0 on failure.
  ## If outMessage is provided, writes the result message to it.
  ##
  ## This is the FFI interface for the initializeToEnvironment() pattern.
  try:
    if isNil(globalController) or isNil(globalController.aiController):
      if not outMessage.isNil and messageSize > 0:
        let msg = "Controller not initialized"
        let copyLen = min(msg.len, messageSize - 1)
        copyMem(outMessage, unsafeAddr msg[0], copyLen)
        cast[ptr char](cast[uint](outMessage) + copyLen.uint)[] = '\0'
      return 0

    let initResult = globalController.aiController.initializeToEnvironment(
      numAgents.int, numTeams.int, mapWidth.int, mapHeight.int
    )

    if not outMessage.isNil and messageSize > 0:
      let copyLen = min(initResult.message.len, messageSize - 1)
      if copyLen > 0:
        copyMem(outMessage, unsafeAddr initResult.message[0], copyLen)
      cast[ptr char](cast[uint](outMessage) + copyLen.uint)[] = '\0'

    if initResult.success: 1 else: 0
  except CatchableError:
    return 0

proc tribal_village_get_feature_count*(): int32 {.exportc, dynlib.} =
  ## Get the number of observation feature layers.
  ## For use in policy initialization to determine observation dimensions.
  ObservationLayers.int32

proc tribal_village_get_feature_name*(
  featureId: int32,
  outName: ptr char,
  nameSize: int32
): int32 {.exportc, dynlib.} =
  ## Get the name of an observation feature by ID.
  ## Writes the name to outName buffer.
  ## Returns the length written, or -1 if invalid feature ID.
  ##
  ## This enables external code to build feature mappings for policy portability.
  try:
    if featureId < 0 or featureId >= ObservationLayers:
      return -1
    if outName.isNil or nameSize <= 0:
      return -1
    let name = $ObservationName(featureId)
    let copyLen = min(name.len, nameSize - 1)
    if copyLen > 0:
      copyMem(outName, unsafeAddr name[0], copyLen)
    cast[ptr char](cast[uint](outName) + copyLen.uint)[] = '\0'
    copyLen.int32
  except CatchableError:
    return -1
