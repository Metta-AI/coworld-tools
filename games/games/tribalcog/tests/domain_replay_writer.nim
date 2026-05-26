## Tests replay writer episode recording and action-log JSON output.

import
  std/[base64, json, os, unittest],
  zippy,
  environment, test_utils, types

import replay_writer as rw

proc readReplayJson(path: string): JsonNode =
  ## Read and decompress a replay JSON file.
  let compressed = readFile(path)
  let decompressed = zippy.uncompress(compressed, dataFormat = dfZlib)
  parseJson(decompressed)

suite "Replay Writer - Episode Lifecycle":
  test "maybeStartReplayEpisode no-ops without env vars":
    delEnv("TV_REPLAY_PATH")
    delEnv("TV_REPLAY_DIR")
    rw.replayWriter = nil

    let env = makeEmptyEnv()
    rw.maybeStartReplayEpisode(env)

    check rw.replayWriter.isNil

  test "maybeStartReplayEpisode creates writer with TV_REPLAY_PATH":
    let tmpPath = getTempDir() / "test_replay_create.json.z"
    putEnv("TV_REPLAY_PATH", tmpPath)
    delEnv("TV_REPLAY_DIR")
    rw.replayWriter = nil

    let env = makeEmptyEnv()
    rw.maybeStartReplayEpisode(env)

    check not rw.replayWriter.isNil
    check rw.replayWriter.enabled

    delEnv("TV_REPLAY_PATH")
    rw.replayWriter = nil

  test "maybeStartReplayEpisode creates writer with TV_REPLAY_DIR":
    let tmpDir = getTempDir() / "replay_test_dir"
    createDir(tmpDir)
    putEnv("TV_REPLAY_DIR", tmpDir)
    delEnv("TV_REPLAY_PATH")
    rw.replayWriter = nil

    let env = makeEmptyEnv()
    rw.maybeStartReplayEpisode(env)

    check not rw.replayWriter.isNil
    check rw.replayWriter.enabled

    delEnv("TV_REPLAY_DIR")
    removeDir(tmpDir)
    rw.replayWriter = nil

suite "Replay Writer - No-Op Safety":
  test "maybeLogReplayStep safe with nil writer":
    rw.replayWriter = nil
    let env = makeEmptyEnv()
    var actions: array[MapAgents, uint16]
    rw.maybeLogReplayStep(env, addr actions)

  test "maybeFinalizeReplay safe with nil writer":
    rw.replayWriter = nil
    let env = makeEmptyEnv()
    rw.maybeFinalizeReplay(env)

  test "maybeLogReplayStep safe at step 0":
    let tmpPath = getTempDir() / "test_step0.json.z"
    putEnv("TV_REPLAY_PATH", tmpPath)
    delEnv("TV_REPLAY_DIR")
    rw.replayWriter = nil

    let env = makeEmptyEnv()
    rw.maybeStartReplayEpisode(env)
    env.currentStep = 0

    var actions: array[MapAgents, uint16]
    rw.maybeLogReplayStep(env, addr actions)

    delEnv("TV_REPLAY_PATH")
    rw.replayWriter = nil

suite "Replay Writer - Full Replay Output":
  test "complete episode produces compact action-log JSON":
    let tmpPath = getTempDir() / "test_full_replay.json.z"
    putEnv("TV_REPLAY_PATH", tmpPath)
    delEnv("TV_REPLAY_DIR")
    rw.replayWriter = nil

    let env = newEnvironment()
    rw.maybeStartReplayEpisode(env)

    for _ in 0 ..< 5:
      var actions: array[MapAgents, uint16]
      env.step(addr actions)

    rw.maybeFinalizeReplay(env)

    check fileExists(tmpPath)

    let replay = readReplayJson(tmpPath)
    check replay.hasKey("version")
    check replay["version"].getInt() == 3
    check replay["format"].getStr() == "tribalcog-action-log-v1"
    check replay.hasKey("num_agents")
    check replay["num_agents"].getInt() == MapAgents
    check replay.hasKey("max_steps")
    check replay["max_steps"].getInt() == 5
    check replay.hasKey("map_size")
    check replay["map_size"][0].getInt() == MapWidth
    check replay["map_size"][1].getInt() == MapHeight
    check replay.hasKey("action_names")
    check replay["action_argument_count"].getInt() == ActionArgumentCount
    check replay.hasKey("file_name")
    check replay.hasKey("initial_state")
    check replay["initial_state"]["seed"].getInt() == env.gameSeed
    check replay.hasKey("actions")
    check replay["actions"]["encoding"].getStr() == "u16le-base64"
    check replay["actions"]["shape"][0].getInt() == 5
    check replay["actions"]["shape"][1].getInt() == MapAgents
    check decode(replay["actions"]["data"].getStr()).len == 5 * MapAgents * sizeof(uint16)

    let bytes = decode(replay["actions"]["data"].getStr())
    check uint8(bytes[0]) == 0'u8
    check uint8(bytes[1]) == 0'u8

    removeFile(tmpPath)
    delEnv("TV_REPLAY_PATH")
    rw.replayWriter = nil

  test "replay with custom label":
    let tmpPath = getTempDir() / "test_replay_label.json.z"
    putEnv("TV_REPLAY_PATH", tmpPath)
    putEnv("TV_REPLAY_LABEL", "Custom Test Label")
    delEnv("TV_REPLAY_DIR")
    rw.replayWriter = nil

    let env = newEnvironment()
    rw.maybeStartReplayEpisode(env)

    var actions: array[MapAgents, uint16]
    env.step(addr actions)
    rw.maybeFinalizeReplay(env)

    let replay = readReplayJson(tmpPath)
    check replay["initial_state"]["label"].getStr() == "Custom Test Label"

    removeFile(tmpPath)
    delEnv("TV_REPLAY_PATH")
    delEnv("TV_REPLAY_LABEL")
    rw.replayWriter = nil

  test "multi-step replay records all steps":
    let tmpPath = getTempDir() / "test_replay_multistep.json.z"
    putEnv("TV_REPLAY_PATH", tmpPath)
    delEnv("TV_REPLAY_DIR")
    rw.replayWriter = nil

    let env = newEnvironment()
    rw.maybeStartReplayEpisode(env)

    let numSteps = 10
    for _ in 0 ..< numSteps:
      var actions: array[MapAgents, uint16]
      env.step(addr actions)

    rw.maybeFinalizeReplay(env)

    let replay = readReplayJson(tmpPath)
    check replay["max_steps"].getInt() == numSteps
    check replay["actions"]["shape"][0].getInt() == numSteps
    check decode(replay["actions"]["data"].getStr()).len ==
      numSteps * MapAgents * sizeof(uint16)

    removeFile(tmpPath)
    delEnv("TV_REPLAY_PATH")
    rw.replayWriter = nil
