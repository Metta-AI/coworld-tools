## Cache wrappers for scalar, per-agent, and per-team scripted state.

import
  vmath,
  ../types

export IVec2

const
  CacheInvalid* = -1'i32

type
  CacheLifecyclePhase* = enum
    ## Track cache wrapper lifecycle state.
    phaseUnallocated
    phaseAllocated
    phaseActive
    phaseCleaned

  CacheWrapper*[T] = object
    ## Store one cached value with lifecycle tracking.
    phase*: CacheLifecyclePhase
    generation*: int32
    validGen*: int32
    value*: T

  PerAgentCacheWrapper*[T] = object
    ## Store one cached value per agent.
    phase*: CacheLifecyclePhase
    stepGeneration*: int32
    agentGen*: array[MapAgents, int32]
    values*: array[MapAgents, T]

  PerTeamCacheWrapper*[T] = object
    ## Store one cached value per team.
    phase*: CacheLifecyclePhase
    stepGeneration*: int32
    teamGen*: array[MapRoomObjectsTeams, int32]
    values*: array[MapRoomObjectsTeams, T]

  AgentStateLifecycle* = object
    ## Track active agents and pending cleanup.
    activeAgents*: array[MapAgents, bool]
    lastActiveStep*: array[MapAgents, int32]
    needsCleanup*: array[MapAgents, bool]

proc isValidAgentId(agentId: int): bool {.inline.} =
  ## Returns true when the agent ID is inside the valid agent range.
  agentId >= 0 and agentId < MapAgents

proc isValidTeamId(teamId: int): bool {.inline.} =
  ## Returns true when the team ID is inside the valid team range.
  teamId >= 0 and teamId < MapRoomObjectsTeams

proc invalidateAgentEntries[T](cache: var PerAgentCacheWrapper[T]) =
  ## Clears every per-agent cache generation marker.
  for i in 0 ..< MapAgents:
    cache.agentGen[i] = CacheInvalid

proc invalidateTeamEntries[T](cache: var PerTeamCacheWrapper[T]) =
  ## Clears every per-team cache generation marker.
  for i in 0 ..< MapRoomObjectsTeams:
    cache.teamGen[i] = CacheInvalid

proc alloc*[T](cache: var CacheWrapper[T]) =
  ## Initialize one scalar cache wrapper.
  cache.phase = phaseAllocated
  cache.generation = 0
  cache.validGen = CacheInvalid

proc reset*[T](cache: var CacheWrapper[T]) =
  ## Reset one scalar cache for a new step.
  assert cache.phase in {phaseAllocated, phaseActive}, "Cannot reset unallocated cache"
  inc cache.generation
  cache.phase = phaseActive

proc cleanup*[T](cache: var CacheWrapper[T]) =
  ## Mark one scalar cache as cleaned up.
  cache.phase = phaseCleaned
  cache.validGen = CacheInvalid

proc isValid*[T](cache: CacheWrapper[T]): bool {.inline.} =
  ## Return whether the scalar cache is valid this generation.
  cache.validGen == cache.generation

proc get*[T](cache: var CacheWrapper[T], compute: proc(): T): T =
  ## Read or compute one scalar cached value.
  if cache.validGen != cache.generation:
    cache.value = compute()
    cache.validGen = cache.generation
  cache.value

proc set*[T](cache: var CacheWrapper[T], value: T) =
  ## Store one scalar cached value.
  cache.value = value
  cache.validGen = cache.generation

proc invalidate*[T](cache: var CacheWrapper[T]) {.inline.} =
  ## Invalidate one scalar cached value.
  cache.validGen = CacheInvalid

proc alloc*[T](cache: var PerAgentCacheWrapper[T]) =
  ## Initialize one per-agent cache wrapper.
  cache.phase = phaseAllocated
  cache.stepGeneration = 0
  invalidateAgentEntries(cache)

proc reset*[T](cache: var PerAgentCacheWrapper[T]) =
  ## Reset one per-agent cache for a new step.
  assert cache.phase in {phaseAllocated, phaseActive}, "Cannot reset unallocated cache"
  inc cache.stepGeneration
  cache.phase = phaseActive

proc cleanup*[T](cache: var PerAgentCacheWrapper[T]) =
  ## Mark one per-agent cache as cleaned up.
  cache.phase = phaseCleaned
  invalidateAgentEntries(cache)

proc isValid*[T](cache: PerAgentCacheWrapper[T], agentId: int): bool {.inline.} =
  ## Return whether one agent cache entry is valid this generation.
  if not isValidAgentId(agentId):
    return false
  cache.agentGen[agentId] == cache.stepGeneration

proc get*[T](cache: var PerAgentCacheWrapper[T], agentId: int,
             compute: proc(agentId: int): T): T =
  ## Read or compute one per-agent cached value.
  if not isValidAgentId(agentId):
    return compute(agentId)
  if cache.agentGen[agentId] != cache.stepGeneration:
    cache.values[agentId] = compute(agentId)
    cache.agentGen[agentId] = cache.stepGeneration
  cache.values[agentId]

proc set*[T](cache: var PerAgentCacheWrapper[T], agentId: int, value: T) =
  ## Store one per-agent cached value.
  if isValidAgentId(agentId):
    cache.values[agentId] = value
    cache.agentGen[agentId] = cache.stepGeneration

proc invalidate*[T](cache: var PerAgentCacheWrapper[T], agentId: int) {.inline.} =
  ## Invalidate one per-agent cached value.
  if isValidAgentId(agentId):
    cache.agentGen[agentId] = CacheInvalid

proc alloc*[T](cache: var PerTeamCacheWrapper[T]) =
  ## Initialize one per-team cache wrapper.
  cache.phase = phaseAllocated
  cache.stepGeneration = 0
  invalidateTeamEntries(cache)

proc reset*[T](cache: var PerTeamCacheWrapper[T]) =
  ## Reset one per-team cache for a new step.
  assert cache.phase in {phaseAllocated, phaseActive}, "Cannot reset unallocated cache"
  inc cache.stepGeneration
  cache.phase = phaseActive

proc cleanup*[T](cache: var PerTeamCacheWrapper[T]) =
  ## Mark one per-team cache as cleaned up.
  cache.phase = phaseCleaned
  invalidateTeamEntries(cache)

proc isValid*[T](cache: PerTeamCacheWrapper[T], teamId: int): bool {.inline.} =
  ## Return whether one team cache entry is valid this generation.
  if not isValidTeamId(teamId):
    return false
  cache.teamGen[teamId] == cache.stepGeneration

proc get*[T](cache: var PerTeamCacheWrapper[T], teamId: int,
             compute: proc(teamId: int): T): T =
  ## Read or compute one per-team cached value.
  if not isValidTeamId(teamId):
    return compute(teamId)
  if cache.teamGen[teamId] != cache.stepGeneration:
    cache.values[teamId] = compute(teamId)
    cache.teamGen[teamId] = cache.stepGeneration
  cache.values[teamId]

proc set*[T](cache: var PerTeamCacheWrapper[T], teamId: int, value: T) =
  ## Store one per-team cached value.
  if isValidTeamId(teamId):
    cache.values[teamId] = value
    cache.teamGen[teamId] = cache.stepGeneration

proc invalidate*[T](cache: var PerTeamCacheWrapper[T], teamId: int) {.inline.} =
  ## Invalidate one per-team cached value.
  if isValidTeamId(teamId):
    cache.teamGen[teamId] = CacheInvalid

proc init*(lifecycle: var AgentStateLifecycle) =
  ## Initialize agent lifecycle tracking.
  for i in 0 ..< MapAgents:
    lifecycle.activeAgents[i] = false
    lifecycle.lastActiveStep[i] = 0
    lifecycle.needsCleanup[i] = false

proc markActive*(
  lifecycle: var AgentStateLifecycle,
  agentId: int,
  currentStep: int32
) =
  ## Mark one agent active at the current step.
  if isValidAgentId(agentId):
    lifecycle.activeAgents[agentId] = true
    lifecycle.lastActiveStep[agentId] = currentStep
    lifecycle.needsCleanup[agentId] = false

proc markInactive*(lifecycle: var AgentStateLifecycle, agentId: int) =
  ## Mark one agent inactive and queue cleanup when needed.
  if isValidAgentId(agentId):
    if lifecycle.activeAgents[agentId]:
      lifecycle.needsCleanup[agentId] = true
    lifecycle.activeAgents[agentId] = false

proc isActive*(lifecycle: AgentStateLifecycle, agentId: int): bool {.inline.} =
  ## Return whether one agent is currently active.
  if not isValidAgentId(agentId):
    return false
  lifecycle.activeAgents[agentId]

proc needsCleanup*(lifecycle: AgentStateLifecycle, agentId: int): bool {.inline.} =
  ## Return whether one agent needs cleanup.
  if not isValidAgentId(agentId):
    return false
  lifecycle.needsCleanup[agentId]

proc clearCleanupFlag*(lifecycle: var AgentStateLifecycle, agentId: int) =
  ## Clear one agent cleanup flag.
  if isValidAgentId(agentId):
    lifecycle.needsCleanup[agentId] = false

proc getAgentsNeedingCleanup*(lifecycle: AgentStateLifecycle): seq[int] =
  ## Return the agent ids that still need cleanup.
  result = @[]
  for i in 0 ..< MapAgents:
    if lifecycle.needsCleanup[i]:
      result.add(i)

proc detectStaleAgents*(lifecycle: var AgentStateLifecycle, currentStep: int32,
                        staleThreshold: int32 = 100): seq[int] =
  ## Mark long-inactive agents for cleanup and return their ids.
  result = @[]
  for i in 0 ..< MapAgents:
    if lifecycle.activeAgents[i]:
      if currentStep - lifecycle.lastActiveStep[i] > staleThreshold:
        lifecycle.needsCleanup[i] = true
        lifecycle.activeAgents[i] = false
        result.add(i)
