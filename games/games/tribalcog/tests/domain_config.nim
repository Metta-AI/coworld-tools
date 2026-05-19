## domain_config.nim - Unit tests for config.nim
##
## Tests the self-documenting configuration system including:
## - Loading from environment
## - Default values
## - JSON serialization/deserialization
## - Validation
## - Override/update functionality
## - Help generation

import std/[unittest, os, json, strutils, tables]
import ../src/config

suite "Config - Default Values":
  test "defaultConfig returns expected defaults":
    let cfg = defaultConfig()
    check cfg.stepTimingTarget == -1
    check cfg.stepTimingWindow == 0
    check cfg.timingInterval == 100
    check cfg.logRenderEnabled == false
    check cfg.logRenderWindow == 100
    check cfg.logRenderEvery == 1
    check cfg.consoleVizEnabled == false
    check cfg.consoleVizInterval == 10
    check cfg.perfThreshold == 10.0
    check cfg.replayPath == "data/replay.json"
    check cfg.debugAI == false

  test "defaultConfig has all boolean flags disabled":
    let cfg = defaultConfig()
    check cfg.logRenderEnabled == false
    check cfg.consoleVizEnabled == false
    check cfg.combatVerbose == false
    check cfg.perfFailOnRegression == false
    check cfg.stateDumpEnabled == false
    check cfg.replayEnabled == false
    check cfg.scorecardEnabled == false
    check cfg.eventLogEnabled == false
    check cfg.debugPathfinding == false
    check cfg.debugCombat == false
    check cfg.debugEconomy == false
    check cfg.debugAI == false

suite "Config - Environment Loading":
  setup:
    # Clear any test env vars
    delEnv("TV_STEP_TIMING")
    delEnv("TV_CONSOLE_VIZ")
    delEnv("TV_PERF_THRESHOLD")
    delEnv("TV_REPLAY_PATH")

  teardown:
    delEnv("TV_STEP_TIMING")
    delEnv("TV_CONSOLE_VIZ")
    delEnv("TV_PERF_THRESHOLD")
    delEnv("TV_REPLAY_PATH")

  test "loadConfig uses defaults when env vars not set":
    let cfg = loadConfig()
    check cfg.stepTimingTarget == -1
    check cfg.consoleVizEnabled == false

  test "loadConfig reads int from environment":
    putEnv("TV_STEP_TIMING", "500")
    let cfg = loadConfig()
    check cfg.stepTimingTarget == 500

  test "loadConfig reads bool from environment (true variants)":
    for trueVal in ["1", "true", "yes", "on", "TRUE", "True"]:
      putEnv("TV_CONSOLE_VIZ", trueVal)
      let cfg = loadConfig()
      check cfg.consoleVizEnabled == true

  test "loadConfig reads bool from environment (false variants)":
    for falseVal in ["0", "false", "no", "off", "FALSE", "False"]:
      putEnv("TV_CONSOLE_VIZ", falseVal)
      let cfg = loadConfig()
      check cfg.consoleVizEnabled == false

  test "loadConfig reads float from environment":
    putEnv("TV_PERF_THRESHOLD", "25.5")
    let cfg = loadConfig()
    check cfg.perfThreshold == 25.5

  test "loadConfig reads string from environment":
    putEnv("TV_REPLAY_PATH", "/custom/path.json")
    let cfg = loadConfig()
    check cfg.replayPath == "/custom/path.json"

  test "loadConfig uses default for invalid int":
    putEnv("TV_STEP_TIMING", "not_a_number")
    let cfg = loadConfig()
    check cfg.stepTimingTarget == -1

  test "loadConfig uses default for invalid float":
    putEnv("TV_PERF_THRESHOLD", "not_a_float")
    let cfg = loadConfig()
    check cfg.perfThreshold == 10.0

suite "Config - JSON Serialization":
  test "toJson produces valid JSON":
    let cfg = defaultConfig()
    let node = cfg.toJson()
    check node.kind == JObject
    check node.hasKey("stepTimingTarget")
    check node.hasKey("consoleVizEnabled")
    check node.hasKey("perfThreshold")
    check node.hasKey("replayPath")

  test "toJson preserves int values":
    var cfg = defaultConfig()
    cfg.stepTimingTarget = 42
    cfg.timingInterval = 200
    let node = cfg.toJson()
    check node["stepTimingTarget"].getInt() == 42
    check node["timingInterval"].getInt() == 200

  test "toJson preserves bool values":
    var cfg = defaultConfig()
    cfg.consoleVizEnabled = true
    cfg.debugAI = true
    let node = cfg.toJson()
    check node["consoleVizEnabled"].getBool() == true
    check node["debugAI"].getBool() == true

  test "toJson preserves float values":
    var cfg = defaultConfig()
    cfg.perfThreshold = 15.5
    let node = cfg.toJson()
    check node["perfThreshold"].getFloat() == 15.5

  test "toJson preserves string values":
    var cfg = defaultConfig()
    cfg.replayPath = "/custom/replay.json"
    let node = cfg.toJson()
    check node["replayPath"].getStr() == "/custom/replay.json"

  test "toJsonString produces valid JSON string":
    let cfg = defaultConfig()
    let jsonStr = cfg.toJsonString(pretty = false)
    let parsed = parseJson(jsonStr)
    check parsed.kind == JObject

  test "JSON keys are sorted alphabetically":
    let cfg = defaultConfig()
    let jsonStr = cfg.toJsonString(pretty = false)
    # Check that actionAuditInterval comes before stepTimingTarget
    let aIdx = jsonStr.find("\"actionAuditInterval\"")
    let sIdx = jsonStr.find("\"stepTimingTarget\"")
    check aIdx < sIdx

suite "Config - JSON Deserialization":
  test "configFromJson creates config with defaults for missing keys":
    let node = %*{"stepTimingTarget": 100}
    let cfg = configFromJson(node)
    check cfg.stepTimingTarget == 100
    check cfg.timingInterval == 100  # default
    check cfg.consoleVizEnabled == false  # default

  test "configFromJson reads all field types":
    let node = %*{
      "stepTimingTarget": 42,
      "consoleVizEnabled": true,
      "perfThreshold": 20.0,
      "replayPath": "/test/path.json"
    }
    let cfg = configFromJson(node)
    check cfg.stepTimingTarget == 42
    check cfg.consoleVizEnabled == true
    check cfg.perfThreshold == 20.0
    check cfg.replayPath == "/test/path.json"

  test "configFromJsonString works":
    let jsonStr = """{"stepTimingTarget": 999, "debugAI": true}"""
    let cfg = configFromJsonString(jsonStr)
    check cfg.stepTimingTarget == 999
    check cfg.debugAI == true

  test "JSON roundtrip preserves values":
    var original = defaultConfig()
    original.stepTimingTarget = 123
    original.consoleVizEnabled = true
    original.perfThreshold = 25.5
    original.replayPath = "/roundtrip/test.json"

    let jsonStr = original.toJsonString()
    let restored = configFromJsonString(jsonStr)

    check restored.stepTimingTarget == 123
    check restored.consoleVizEnabled == true
    check restored.perfThreshold == 25.5
    check restored.replayPath == "/roundtrip/test.json"

suite "Config - Validation":
  test "defaultConfig passes validation":
    let cfg = defaultConfig()
    let errors = cfg.validate()
    check errors.len == 0

  test "validation catches out-of-range int":
    var cfg = defaultConfig()
    cfg.timingInterval = -5  # violates minInt: 1
    let errors = cfg.validate()
    check errors.len >= 1
    check errors[0].field == "timingInterval"

  test "validation catches out-of-range float":
    var cfg = defaultConfig()
    cfg.perfThreshold = -1.0  # violates minFloat: 0.1
    let errors = cfg.validate()
    check errors.len >= 1
    check errors[0].field == "perfThreshold"

  test "validation allows edge values":
    var cfg = defaultConfig()
    cfg.stepTimingTarget = -1  # minimum allowed
    cfg.timingInterval = 1  # minimum allowed
    cfg.perfThreshold = 0.1  # minimum allowed
    let errors = cfg.validate()
    check errors.len == 0

suite "Config - Override":
  test "override changes int field":
    var cfg = defaultConfig()
    let success = cfg.override("stepTimingTarget", "500")
    check success == true
    check cfg.stepTimingTarget == 500

  test "override changes bool field":
    var cfg = defaultConfig()
    let success = cfg.override("consoleVizEnabled", "true")
    check success == true
    check cfg.consoleVizEnabled == true

  test "override changes float field":
    var cfg = defaultConfig()
    let success = cfg.override("perfThreshold", "25.5")
    check success == true
    check cfg.perfThreshold == 25.5

  test "override changes string field":
    var cfg = defaultConfig()
    let success = cfg.override("replayPath", "/new/path.json")
    check success == true
    check cfg.replayPath == "/new/path.json"

  test "override returns false for unknown field":
    var cfg = defaultConfig()
    let success = cfg.override("unknownField", "value")
    check success == false

  test "override returns false for invalid int":
    var cfg = defaultConfig()
    let success = cfg.override("stepTimingTarget", "not_a_number")
    check success == false
    check cfg.stepTimingTarget == -1  # unchanged

  test "update applies multiple overrides":
    var cfg = defaultConfig()
    let failures = cfg.update([
      ("stepTimingTarget", "100"),
      ("consoleVizEnabled", "true"),
      ("perfThreshold", "30.0")
    ])
    check failures.len == 0
    check cfg.stepTimingTarget == 100
    check cfg.consoleVizEnabled == true
    check cfg.perfThreshold == 30.0

  test "update returns failed keys":
    var cfg = defaultConfig()
    let failures = cfg.update([
      ("stepTimingTarget", "100"),
      ("unknownField", "value"),
      ("anotherUnknown", "value")
    ])
    check failures.len == 2
    check "unknownField" in failures
    check "anotherUnknown" in failures

suite "Config - Diff":
  test "diff returns empty for identical configs":
    let a = defaultConfig()
    let b = defaultConfig()
    let differences = diff(a, b)
    check differences.len == 0

  test "diff detects int changes":
    var a = defaultConfig()
    var b = defaultConfig()
    b.stepTimingTarget = 100
    let differences = diff(a, b)
    check differences.len == 1
    check differences[0][0] == "stepTimingTarget"
    check differences[0][1] == "-1"
    check differences[0][2] == "100"

  test "diff detects bool changes":
    var a = defaultConfig()
    var b = defaultConfig()
    b.debugAI = true
    let differences = diff(a, b)
    check differences.len == 1
    check differences[0][0] == "debugAI"
    check differences[0][1] == "false"
    check differences[0][2] == "true"

  test "diff detects multiple changes":
    var a = defaultConfig()
    var b = defaultConfig()
    b.stepTimingTarget = 100
    b.consoleVizEnabled = true
    b.perfThreshold = 20.0
    let differences = diff(a, b)
    check differences.len == 3

suite "Config - Field Descriptors":
  test "ConfigFieldDescs contains all expected fields":
    check ConfigFieldDescs.len > 0

    var fieldNames: seq[string] = @[]
    for desc in ConfigFieldDescs:
      fieldNames.add desc.name

    check "stepTimingTarget" in fieldNames
    check "consoleVizEnabled" in fieldNames
    check "perfThreshold" in fieldNames
    check "replayPath" in fieldNames

  test "all field descriptors have non-empty names":
    for desc in ConfigFieldDescs:
      check desc.name.len > 0

  test "all field descriptors have non-empty env vars":
    for desc in ConfigFieldDescs:
      check desc.envVar.len > 0
      check desc.envVar.startsWith("TV_")

  test "all field descriptors have non-empty descriptions":
    for desc in ConfigFieldDescs:
      check desc.description.len > 0

  test "all field descriptors have categories":
    for desc in ConfigFieldDescs:
      check desc.category.len > 0

  test "getFieldDesc finds existing field":
    let desc = getFieldDesc("stepTimingTarget")
    check desc.name == "stepTimingTarget"
    check desc.envVar == "TV_STEP_TIMING"

  test "getFieldDesc raises for unknown field":
    expect KeyError:
      discard getFieldDesc("unknownField")

  test "getFieldDescByEnvVar finds existing field":
    let desc = getFieldDescByEnvVar("TV_STEP_TIMING")
    check desc.name == "stepTimingTarget"

  test "getFieldDescByEnvVar raises for unknown var":
    expect KeyError:
      discard getFieldDescByEnvVar("UNKNOWN_VAR")

suite "Config - Help Generation":
  test "help generates non-empty output":
    let helpText = help()
    check helpText.len > 0
    check "Tribal Village Configuration" in helpText

  test "help includes environment variables":
    let helpText = help()
    check "TV_STEP_TIMING" in helpText
    check "TV_CONSOLE_VIZ" in helpText
    check "TV_PERF_THRESHOLD" in helpText

  test "help includes categories":
    let helpText = help()
    check "[Performance]" in helpText
    check "[Debug]" in helpText
    check "[Visualization]" in helpText

  test "help includes type info":
    let helpText = help()
    check "Type: int" in helpText
    check "Type: bool" in helpText
    check "Type: float" in helpText
    check "Type: string" in helpText

  test "helpMarkdown generates markdown output":
    let md = helpMarkdown()
    check md.len > 0
    check "# Tribal Village Configuration" in md
    check "| Environment Variable |" in md

  test "helpMarkdown includes all categories":
    let md = helpMarkdown()
    check "## Performance" in md
    check "## Debug" in md
    check "## Visualization" in md

suite "Config - envVars":
  test "envVars returns all environment variable names":
    let vars = envVars()
    check vars.len == ConfigFieldDescs.len
    check "TV_STEP_TIMING" in vars
    check "TV_CONSOLE_VIZ" in vars
    check "TV_REPLAY_PATH" in vars

  test "all envVars start with TV_":
    for v in envVars():
      check v.startsWith("TV_")

suite "Config - Integration":
  test "full workflow: load, modify, validate, serialize, restore":
    # Load from environment (with defaults)
    var cfg = loadConfig()

    # Modify
    discard cfg.override("stepTimingTarget", "200")
    discard cfg.override("debugAI", "true")
    discard cfg.override("perfThreshold", "15.0")

    # Validate
    let errors = cfg.validate()
    check errors.len == 0

    # Serialize
    let jsonStr = cfg.toJsonString()

    # Restore
    let restored = configFromJsonString(jsonStr)

    # Verify
    check restored.stepTimingTarget == 200
    check restored.debugAI == true
    check restored.perfThreshold == 15.0

  test "config can detect differences after modification":
    var original = loadConfig()
    var modified = loadConfig()

    discard modified.override("stepTimingTarget", "999")
    discard modified.override("debugAI", "true")

    let differences = diff(original, modified)
    check differences.len == 2
