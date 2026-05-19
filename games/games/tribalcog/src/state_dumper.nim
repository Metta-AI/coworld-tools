## Game state snapshot dumper for offline analysis.
##
## Controlled by `TV_DUMP_INTERVAL` and `TV_DUMP_DIR`.

import
  std/[json, os, strformat, strutils, times],
  envconfig,
  items, types

const
  DefaultDumpDir = "./dumps/"
  StateTimestampFormat = "yyyyMMdd'T'HHmmss'.'fff"
  AgentFieldNames = [
    "agentId", "x", "y", "hp", "maxHp",
    "teamId", "unitClass", "stance", "invCount", "alive"
  ]
  ThingFieldNames = [
    "kind", "x", "y", "hp", "maxHp", "teamId"
  ]
  TeamResourceFieldNames = [
    "food", "wood", "gold", "stone", "water", "none"
  ]

var
  dumpInterval*: int = 0
  dumpDir*: string = DefaultDumpDir
  dumpInitialized: bool = false

proc initDumper*() =
  ## Initialize dump settings from environment variables.
  dumpInterval = parseEnvInt("TV_DUMP_INTERVAL", 0)
  dumpDir = getEnv("TV_DUMP_DIR", DefaultDumpDir)
  if dumpInterval > 0:
    createDir(dumpDir)
  dumpInitialized = true

proc dumpAgents(env: Environment): JsonNode =
  ## Serialize live agents as compact arrays.
  var arr = newJArray()
  for agent in env.liveAgents:
    let alive = env.terminated[agent.agentId] == 0.0
    var agentNode = newJArray()
    agentNode.add(%agent.agentId)
    agentNode.add(%agent.pos.x)
    agentNode.add(%agent.pos.y)
    agentNode.add(%agent.hp)
    agentNode.add(%agent.maxHp)
    agentNode.add(%agent.getTeamId())
    agentNode.add(%ord(agent.unitClass))
    agentNode.add(%ord(agent.stance))
    agentNode.add(%agent.inventory.len)
    agentNode.add(%(if alive: 1 else: 0))
    arr.add(agentNode)
  arr

proc dumpThings(env: Environment): JsonNode =
  ## Serialize non-agent things as compact arrays.
  var arr = newJArray()
  for thing in env.things:
    if thing.isNil or thing.kind == Agent:
      continue
    var thingNode = newJArray()
    thingNode.add(%ord(thing.kind))
    thingNode.add(%thing.pos.x)
    thingNode.add(%thing.pos.y)
    thingNode.add(%thing.hp)
    thingNode.add(%thing.maxHp)
    thingNode.add(%thing.teamId)
    arr.add(thingNode)
  arr

proc dumpTeamResources(env: Environment): JsonNode =
  ## Serialize team stockpiles as resource arrays.
  var arr = newJArray()
  for teamId in 0 ..< MapRoomObjectsTeams:
    var teamNode = newJArray()
    for res in StockpileResource:
      teamNode.add(%env.teamStockpiles[teamId].counts[res])
    arr.add(teamNode)
  arr

proc dumpTeamPopulations(env: Environment): JsonNode =
  ## Count alive agents for each team.
  var counts: array[MapRoomObjectsTeams, int]
  for agent in env.liveAgents:
    if env.terminated[agent.agentId] == 0.0:
      let teamId = agent.getTeamId()
      if teamId >= 0 and teamId < MapRoomObjectsTeams:
        inc counts[teamId]
  var arr = newJArray()
  for teamId in 0 ..< MapRoomObjectsTeams:
    arr.add(%counts[teamId])
  arr

proc dumpSpatialIndexStats(env: Environment): JsonNode =
  ## Serialize summary statistics for spatial index occupancy.
  var
    nonEmpty = 0
    maxCount = 0
    totalThings = 0
  for cx in 0 ..< SpatialCellsX:
    for cy in 0 ..< SpatialCellsY:
      let count = env.spatialIndex.cells[cx][cy].things.len
      if count > 0:
        inc nonEmpty
        totalThings += count
        if count > maxCount:
          maxCount = count
  %*{
    "cells_total": SpatialCellsX * SpatialCellsY,
    "cells_occupied": nonEmpty,
    "things_indexed": totalThings,
    "max_per_cell": maxCount
  }

proc dumpState*(env: Environment) =
  ## Dump one full game state snapshot to a timestamped JSON file.
  if not dumpInitialized:
    initDumper()

  let
    currentTime = times.now()
    timestamp = currentTime.format(StateTimestampFormat)
    filename = dumpDir / &"state_step{env.currentStep:06d}_{timestamp}.json"

  var root = newJObject()
  root["step"] = %env.currentStep
  root["timestamp"] = %($currentTime)
  root["map_width"] = %MapWidth
  root["map_height"] = %MapHeight
  root["num_teams"] = %MapRoomObjectsTeams
  root["victory_winner"] = %env.victoryWinner

  root["agent_fields"] = %AgentFieldNames
  root["agents"] = dumpAgents(env)

  root["thing_fields"] = %ThingFieldNames
  root["things"] = dumpThings(env)

  root["team_resource_fields"] = %TeamResourceFieldNames
  root["team_resources"] = dumpTeamResources(env)
  root["team_populations"] = dumpTeamPopulations(env)
  root["spatial_index"] = dumpSpatialIndexStats(env)

  writeFile(filename, $root)

proc maybeDumpState*(env: Environment) =
  ## Dump state on configured step intervals.
  if not dumpInitialized:
    initDumper()
  if dumpInterval > 0 and env.currentStep mod dumpInterval == 0:
    dumpState(env)
