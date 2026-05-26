## Action-log replay serialization.
##
## A replay is the initial deterministic setup plus one raw uint16 action row
## per simulation step. Object timelines are derived from that log on demand by
## replay tooling rather than maintained inside the live game loop.

import
  std/[base64, json, os],
  zippy,
  common_types, replay_common, types

const
  DefaultReplayBaseName = "tribal_village"
  DefaultReplayLabel = "Tribal Village Replay"
  ReplayFileExtension = ".json.z"

type
  ReplayWriter* = ref object
    enabled*: bool
    baseDir: string
    basePath: string
    baseName: string
    label: string
    episodeIndex: int
    outputPath: string
    fileName: string
    seed: int
    maxStep: int
    actionBytes: string
    active: bool

var
  replayWriter*: ReplayWriter = nil

proc buildEpisodePath(writer: ReplayWriter): string =
  ## Return the output path for the current replay episode.
  if writer.basePath.len > 0:
    return writer.basePath

  let
    suffix = "_" & $writer.episodeIndex
    fileName = writer.baseName & suffix & ReplayFileExtension
  if writer.baseDir.len > 0:
    return writer.baseDir / fileName
  fileName

proc appendActionRow(
  writer: ReplayWriter,
  actions: ptr array[MapAgents, uint16]
) =
  ## Append one little-endian uint16 action row.
  writer.actionBytes.setLen(writer.actionBytes.len + MapAgents * sizeof(uint16))
  var offset = writer.actionBytes.len - MapAgents * sizeof(uint16)
  for agentId in 0 ..< MapAgents:
    let value = actions[][agentId]
    writer.actionBytes[offset] = char(value and 0xff'u16)
    writer.actionBytes[offset + 1] = char((value shr 8) and 0xff'u16)
    offset += 2

proc maybeStartReplayEpisode*(env: Environment) =
  ## Initialize replay logging for a new episode when configured.
  var writer = replayWriter
  if writer.isNil:
    let
      basePath = getEnv("TV_REPLAY_PATH", "")
      baseDir = getEnv("TV_REPLAY_DIR", "")
    if basePath.len == 0 and baseDir.len == 0:
      return
    let
      baseName = getEnv("TV_REPLAY_NAME", DefaultReplayBaseName)
      label = getEnv("TV_REPLAY_LABEL", DefaultReplayLabel)
    writer = ReplayWriter(
      enabled: true,
      baseDir: baseDir,
      basePath: basePath,
      baseName: baseName,
      label: label
    )
    replayWriter = writer

  inc writer.episodeIndex
  writer.maxStep = -1
  writer.seed = env.gameSeed
  writer.actionBytes.setLen(0)
  writer.active = true
  writer.outputPath = buildEpisodePath(writer)
  writer.fileName = extractFilename(writer.outputPath)

proc maybeLogReplayStep*(
  env: Environment,
  actions: ptr array[MapAgents, uint16]
) =
  ## Record one action row into the active replay.
  let writer = replayWriter
  if writer.isNil or not writer.active:
    return

  let stepIndex = env.currentStep - 1
  if stepIndex < 0:
    return
  writer.maxStep = max(writer.maxStep, stepIndex)
  writer.appendActionRow(actions)

proc buildReplayJson(writer: ReplayWriter): JsonNode =
  ## Build the compressed action-log replay JSON document.
  result = newJObject()
  result["version"] = newJInt(ReplayVersion)
  result["format"] = newJString("tribalcog-action-log-v1")

  var actionNames = newJArray()
  for name in ActionNames:
    actionNames.add(newJString(name))
  result["action_names"] = actionNames
  result["action_argument_count"] = newJInt(ActionArgumentCount)

  result["num_agents"] = newJInt(MapAgents)
  let steps =
    if writer.maxStep >= 0:
      writer.maxStep + 1
    else:
      0
  result["max_steps"] = newJInt(steps)

  var mapSize = newJArray()
  mapSize.add(newJInt(MapWidth))
  mapSize.add(newJInt(MapHeight))
  result["map_size"] = mapSize
  result["file_name"] = newJString(writer.fileName)

  var initial = newJObject()
  initial["seed"] = newJInt(writer.seed)
  initial["label"] = newJString(writer.label)
  result["initial_state"] = initial

  var actions = newJObject()
  actions["encoding"] = newJString("u16le-base64")
  actions["shape"] = %*[steps, MapAgents]
  actions["data"] = newJString(encode(writer.actionBytes))
  result["actions"] = actions

proc maybeFinalizeReplay*(env: Environment) =
  ## Flush the active action-log replay to disk and close the episode.
  discard env
  let writer = replayWriter
  if writer.isNil or not writer.active:
    return

  let
    replayJson = buildReplayJson(writer)
    jsonData = $replayJson
    compressed = zippy.compress(jsonData, dataFormat = dfZlib)
  if writer.outputPath.len > 0:
    let dir = parentDir(writer.outputPath)
    if dir.len > 0:
      createDir(dir)
    writeFile(writer.outputPath, compressed)
  writer.active = false
