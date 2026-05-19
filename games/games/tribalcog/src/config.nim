## config.nim - Self-documenting configuration with validation
##
## Provides a Pydantic-style configuration system with:
## - Type hints and field descriptors
## - Validation constraints
## - Auto-generated help/docs
## - Deterministic JSON serialization for reproducible configs
## - Environment variable loading
##
## Usage:
##   let cfg = loadConfig()                    # Load from environment
##   echo cfg.help()                           # Show all config options
##   let json = cfg.toJson()                   # Serialize to JSON
##   let cfg2 = configFromJson(json)           # Deserialize from JSON
##   assert cfg.validate().len == 0            # Check for validation errors

import std/[algorithm, json, strformat, strutils, tables]

import envconfig

type
  ConfigFieldKind* = enum
    cfkInt
    cfkFloat
    cfkBool
    cfkString

  ConfigConstraint* = object
    ## Validation constraint for a configuration field
    case kind*: ConfigFieldKind
    of cfkInt:
      minInt*, maxInt*: int
    of cfkFloat:
      minFloat*, maxFloat*: float
    of cfkBool:
      discard
    of cfkString:
      allowedValues*: seq[string]

  ConfigFieldDesc* = object
    ## Metadata describing a configuration field
    name*: string           ## Field name (e.g., "stepTimingTarget")
    envVar*: string         ## Environment variable name (e.g., "TV_STEP_TIMING")
    description*: string    ## Human-readable description
    category*: string       ## Grouping category (e.g., "Performance", "Debug")
    kind*: ConfigFieldKind  ## Type of the field
    defaultInt*: int        ## Default value for int fields
    defaultFloat*: float    ## Default value for float fields
    defaultBool*: bool      ## Default value for bool fields
    defaultString*: string  ## Default value for string fields
    constraint*: ConfigConstraint  ## Validation constraint
    hasConstraint*: bool    ## Whether constraint is set

  Config* = object
    ## Central configuration object for tribal-village
    ##
    ## All runtime-configurable parameters live here. This replaces scattered
    ## parseEnvInt/parseEnvBool calls with a centralized, documented system.

    # Performance & Timing
    stepTimingTarget*: int        ## Target step for detailed timing analysis (-1 = disabled)
    stepTimingWindow*: int        ## Number of steps to analyze around target
    timingInterval*: int          ## Steps between timing reports

    # Rendering & Visualization
    logRenderEnabled*: bool       ## Enable render logging to file
    logRenderWindow*: int         ## Steps to capture in render log
    logRenderEvery*: int          ## Log every N frames

    # Console Visualization
    consoleVizEnabled*: bool      ## Enable ASCII console visualization
    consoleVizInterval*: int      ## Steps between console viz updates

    # Audit Systems
    actionAuditInterval*: int     ## Steps between action audit reports
    actionFreqInterval*: int      ## Steps between action frequency reports
    combatReportInterval*: int    ## Steps between combat audit reports
    combatVerbose*: bool          ## Enable verbose combat logging
    tumorReportInterval*: int     ## Steps between tumor audit reports
    econReportInterval*: int      ## Steps between economy audit reports
    techReportInterval*: int      ## Steps between tech audit reports
    settlerReportInterval*: int   ## Steps between settler metrics reports

    # Flame Graph Profiling
    flameInterval*: int           ## Steps between flame graph flushes
    flameSample*: int             ## Sample rate for flame graph

    # Performance Regression Detection
    perfWindow*: int              ## Window size for perf regression detection
    perfInterval*: int            ## Steps between perf reports
    perfThreshold*: float         ## Regression threshold percentage
    perfFailOnRegression*: bool   ## Exit with error on performance regression

    # Heatmap Generation
    heatmapInterval*: int         ## Steps between heatmap snapshots

    # State Dumping
    stateDumpEnabled*: bool       ## Enable periodic state dumps
    stateDumpInterval*: int       ## Steps between state dumps

    # Replay System
    replayEnabled*: bool          ## Enable replay recording
    replayPath*: string           ## Path to write replay file

    # Balance Scorecard
    scorecardEnabled*: bool       ## Enable balance scorecard generation
    scorecardPath*: string        ## Path to write scorecard

    # Event Logging
    eventLogEnabled*: bool        ## Enable event log output
    eventLogInterval*: int        ## Steps between event log flushes

    # Debug Flags
    debugPathfinding*: bool       ## Enable pathfinding debug output
    debugCombat*: bool            ## Enable combat debug output
    debugEconomy*: bool           ## Enable economy debug output
    debugAI*: bool                ## Enable AI decision debug output

const
  ConfigFieldDescs*: seq[ConfigFieldDesc] = @[
    # Performance & Timing
    ConfigFieldDesc(
      name: "stepTimingTarget",
      envVar: "TV_STEP_TIMING",
      description: "Target step for detailed timing analysis. Set to -1 to disable.",
      category: "Performance",
      kind: cfkInt,
      defaultInt: -1,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: -1, maxInt: high(int))
    ),
    ConfigFieldDesc(
      name: "stepTimingWindow",
      envVar: "TV_STEP_TIMING_WINDOW",
      description: "Number of steps to analyze around the timing target.",
      category: "Performance",
      kind: cfkInt,
      defaultInt: 0,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 0, maxInt: 10000)
    ),
    ConfigFieldDesc(
      name: "timingInterval",
      envVar: "TV_TIMING_INTERVAL",
      description: "Steps between timing report outputs.",
      category: "Performance",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),

    # Rendering & Visualization
    ConfigFieldDesc(
      name: "logRenderEnabled",
      envVar: "TV_LOG_RENDER",
      description: "Enable render logging to file for debugging rendering issues.",
      category: "Rendering",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "logRenderWindow",
      envVar: "TV_LOG_RENDER_WINDOW",
      description: "Number of steps to capture in render log.",
      category: "Rendering",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 100, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "logRenderEvery",
      envVar: "TV_LOG_RENDER_EVERY",
      description: "Log every N frames. Higher values reduce log size.",
      category: "Rendering",
      kind: cfkInt,
      defaultInt: 1,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 1000)
    ),

    # Console Visualization
    ConfigFieldDesc(
      name: "consoleVizEnabled",
      envVar: "TV_CONSOLE_VIZ",
      description: "Enable ASCII console visualization for headless debugging.",
      category: "Visualization",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "consoleVizInterval",
      envVar: "TV_VIZ_INTERVAL",
      description: "Steps between console visualization updates.",
      category: "Visualization",
      kind: cfkInt,
      defaultInt: 10,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 1000)
    ),

    # Audit Systems
    ConfigFieldDesc(
      name: "actionAuditInterval",
      envVar: "TV_ACTION_AUDIT_INTERVAL",
      description: "Steps between action audit reports.",
      category: "Audit",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "actionFreqInterval",
      envVar: "TV_ACTION_FREQ_INTERVAL",
      description: "Steps between action frequency reports.",
      category: "Audit",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "combatReportInterval",
      envVar: "TV_COMBAT_REPORT_INTERVAL",
      description: "Steps between combat audit reports.",
      category: "Audit",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "combatVerbose",
      envVar: "TV_COMBAT_VERBOSE",
      description: "Enable verbose combat logging with per-attack details.",
      category: "Audit",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "tumorReportInterval",
      envVar: "TV_TUMOR_REPORT_INTERVAL",
      description: "Steps between tumor audit reports.",
      category: "Audit",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "econReportInterval",
      envVar: "TV_ECON_REPORT_INTERVAL",
      description: "Steps between economy audit reports.",
      category: "Audit",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "techReportInterval",
      envVar: "TV_TECH_REPORT_INTERVAL",
      description: "Steps between tech tree audit reports.",
      category: "Audit",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "settlerReportInterval",
      envVar: "TV_SETTLER_REPORT_INTERVAL",
      description: "Steps between settler metrics reports.",
      category: "Audit",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),

    # Flame Graph Profiling
    ConfigFieldDesc(
      name: "flameInterval",
      envVar: "TV_FLAME_INTERVAL",
      description: "Steps between flame graph file flushes.",
      category: "Profiling",
      kind: cfkInt,
      defaultInt: 1000,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "flameSample",
      envVar: "TV_FLAME_SAMPLE",
      description: "Sample rate for flame graph (1 = every step).",
      category: "Profiling",
      kind: cfkInt,
      defaultInt: 1,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 1000)
    ),

    # Performance Regression Detection
    ConfigFieldDesc(
      name: "perfWindow",
      envVar: "TV_PERF_WINDOW",
      description: "Window size for performance regression detection.",
      category: "Profiling",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 10, maxInt: 10000)
    ),
    ConfigFieldDesc(
      name: "perfInterval",
      envVar: "TV_PERF_INTERVAL",
      description: "Steps between performance reports.",
      category: "Profiling",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),
    ConfigFieldDesc(
      name: "perfThreshold",
      envVar: "TV_PERF_THRESHOLD",
      description: "Regression threshold percentage. Values above trigger warnings.",
      category: "Profiling",
      kind: cfkFloat,
      defaultFloat: 10.0,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkFloat, minFloat: 0.1, maxFloat: 100.0)
    ),
    ConfigFieldDesc(
      name: "perfFailOnRegression",
      envVar: "TV_PERF_FAIL_ON_REGRESSION",
      description: "Exit with error code when performance regression is detected.",
      category: "Profiling",
      kind: cfkBool,
      defaultBool: false
    ),

    # Heatmap Generation
    ConfigFieldDesc(
      name: "heatmapInterval",
      envVar: "TV_HEATMAP_INTERVAL",
      description: "Steps between heatmap snapshot captures.",
      category: "Visualization",
      kind: cfkInt,
      defaultInt: 50,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 10000)
    ),

    # State Dumping
    ConfigFieldDesc(
      name: "stateDumpEnabled",
      envVar: "TV_STATE_DUMP",
      description: "Enable periodic state dumps for debugging.",
      category: "Debug",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "stateDumpInterval",
      envVar: "TV_STATE_DUMP_INTERVAL",
      description: "Steps between state dump outputs.",
      category: "Debug",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),

    # Replay System
    ConfigFieldDesc(
      name: "replayEnabled",
      envVar: "TV_REPLAY",
      description: "Enable replay recording for later playback.",
      category: "Replay",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "replayPath",
      envVar: "TV_REPLAY_PATH",
      description: "Path to write replay file.",
      category: "Replay",
      kind: cfkString,
      defaultString: "data/replay.json"
    ),

    # Balance Scorecard
    ConfigFieldDesc(
      name: "scorecardEnabled",
      envVar: "TV_SCORECARD",
      description: "Enable balance scorecard generation.",
      category: "Analysis",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "scorecardPath",
      envVar: "TV_SCORECARD_PATH",
      description: "Path to write scorecard output.",
      category: "Analysis",
      kind: cfkString,
      defaultString: "data/scorecard.json"
    ),

    # Event Logging
    ConfigFieldDesc(
      name: "eventLogEnabled",
      envVar: "TV_EVENT_LOG",
      description: "Enable structured event logging.",
      category: "Debug",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "eventLogInterval",
      envVar: "TV_EVENT_LOG_INTERVAL",
      description: "Steps between event log flushes.",
      category: "Debug",
      kind: cfkInt,
      defaultInt: 100,
      hasConstraint: true,
      constraint: ConfigConstraint(kind: cfkInt, minInt: 1, maxInt: 100000)
    ),

    # Debug Flags
    ConfigFieldDesc(
      name: "debugPathfinding",
      envVar: "TV_DEBUG_PATHFINDING",
      description: "Enable pathfinding debug output.",
      category: "Debug",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "debugCombat",
      envVar: "TV_DEBUG_COMBAT",
      description: "Enable combat system debug output.",
      category: "Debug",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "debugEconomy",
      envVar: "TV_DEBUG_ECONOMY",
      description: "Enable economy system debug output.",
      category: "Debug",
      kind: cfkBool,
      defaultBool: false
    ),
    ConfigFieldDesc(
      name: "debugAI",
      envVar: "TV_DEBUG_AI",
      description: "Enable AI decision-making debug output.",
      category: "Debug",
      kind: cfkBool,
      defaultBool: false
    )
  ]

proc loadConfig*(): Config =
  ## Load configuration from environment variables.
  ## Returns a Config object with all values populated from env vars or defaults.
  result = Config(
    # Performance & Timing
    stepTimingTarget: parseEnvInt("TV_STEP_TIMING", -1),
    stepTimingWindow: parseEnvInt("TV_STEP_TIMING_WINDOW", 0),
    timingInterval: parseEnvInt("TV_TIMING_INTERVAL", 100),

    # Rendering & Visualization
    logRenderEnabled: parseEnvBool("TV_LOG_RENDER", false),
    logRenderWindow: max(100, parseEnvInt("TV_LOG_RENDER_WINDOW", 100)),
    logRenderEvery: max(1, parseEnvInt("TV_LOG_RENDER_EVERY", 1)),

    # Console Visualization
    consoleVizEnabled: parseEnvBool("TV_CONSOLE_VIZ", false),
    consoleVizInterval: max(1, parseEnvInt("TV_VIZ_INTERVAL", 10)),

    # Audit Systems
    actionAuditInterval: max(1, parseEnvInt("TV_ACTION_AUDIT_INTERVAL", 100)),
    actionFreqInterval: max(1, parseEnvInt("TV_ACTION_FREQ_INTERVAL", 100)),
    combatReportInterval: max(1, parseEnvInt("TV_COMBAT_REPORT_INTERVAL", 100)),
    combatVerbose: parseEnvBool("TV_COMBAT_VERBOSE", false),
    tumorReportInterval: max(1, parseEnvInt("TV_TUMOR_REPORT_INTERVAL", 100)),
    econReportInterval: max(1, parseEnvInt("TV_ECON_REPORT_INTERVAL", 100)),
    techReportInterval: max(1, parseEnvInt("TV_TECH_REPORT_INTERVAL", 100)),
    settlerReportInterval: max(1, parseEnvInt("TV_SETTLER_REPORT_INTERVAL", 100)),

    # Flame Graph Profiling
    flameInterval: max(1, parseEnvInt("TV_FLAME_INTERVAL", 1000)),
    flameSample: max(1, parseEnvInt("TV_FLAME_SAMPLE", 1)),

    # Performance Regression Detection
    perfWindow: max(10, parseEnvInt("TV_PERF_WINDOW", 100)),
    perfInterval: max(1, parseEnvInt("TV_PERF_INTERVAL", 100)),
    perfThreshold: parseEnvFloat("TV_PERF_THRESHOLD", 10.0),
    perfFailOnRegression: parseEnvBool("TV_PERF_FAIL_ON_REGRESSION", false),

    # Heatmap Generation
    heatmapInterval: max(1, parseEnvInt("TV_HEATMAP_INTERVAL", 50)),

    # State Dumping
    stateDumpEnabled: parseEnvBool("TV_STATE_DUMP", false),
    stateDumpInterval: max(1, parseEnvInt("TV_STATE_DUMP_INTERVAL", 100)),

    # Replay System
    replayEnabled: parseEnvBool("TV_REPLAY", false),
    replayPath: parseEnvString("TV_REPLAY_PATH", "data/replay.json"),

    # Balance Scorecard
    scorecardEnabled: parseEnvBool("TV_SCORECARD", false),
    scorecardPath: parseEnvString("TV_SCORECARD_PATH", "data/scorecard.json"),

    # Event Logging
    eventLogEnabled: parseEnvBool("TV_EVENT_LOG", false),
    eventLogInterval: max(1, parseEnvInt("TV_EVENT_LOG_INTERVAL", 100)),

    # Debug Flags
    debugPathfinding: parseEnvBool("TV_DEBUG_PATHFINDING", false),
    debugCombat: parseEnvBool("TV_DEBUG_COMBAT", false),
    debugEconomy: parseEnvBool("TV_DEBUG_ECONOMY", false),
    debugAI: parseEnvBool("TV_DEBUG_AI", false)
  )

proc defaultConfig*(): Config =
  ## Return a Config with all default values (no environment loading).
  result = Config(
    stepTimingTarget: -1,
    stepTimingWindow: 0,
    timingInterval: 100,
    logRenderEnabled: false,
    logRenderWindow: 100,
    logRenderEvery: 1,
    consoleVizEnabled: false,
    consoleVizInterval: 10,
    actionAuditInterval: 100,
    actionFreqInterval: 100,
    combatReportInterval: 100,
    combatVerbose: false,
    tumorReportInterval: 100,
    econReportInterval: 100,
    techReportInterval: 100,
    settlerReportInterval: 100,
    flameInterval: 1000,
    flameSample: 1,
    perfWindow: 100,
    perfInterval: 100,
    perfThreshold: 10.0,
    perfFailOnRegression: false,
    heatmapInterval: 50,
    stateDumpEnabled: false,
    stateDumpInterval: 100,
    replayEnabled: false,
    replayPath: "data/replay.json",
    scorecardEnabled: false,
    scorecardPath: "data/scorecard.json",
    eventLogEnabled: false,
    eventLogInterval: 100,
    debugPathfinding: false,
    debugCombat: false,
    debugEconomy: false,
    debugAI: false
  )

# =============================================================================
# Validation
# =============================================================================

type
  ValidationError* = object
    field*: string
    message*: string

proc validate*(cfg: Config): seq[ValidationError] =
  ## Validate configuration values against constraints.
  ## Returns a sequence of validation errors (empty if valid).
  result = @[]

  for desc in ConfigFieldDescs:
    if not desc.hasConstraint:
      continue

    case desc.kind
    of cfkInt:
      var value: int
      case desc.name
      of "stepTimingTarget": value = cfg.stepTimingTarget
      of "stepTimingWindow": value = cfg.stepTimingWindow
      of "timingInterval": value = cfg.timingInterval
      of "logRenderWindow": value = cfg.logRenderWindow
      of "logRenderEvery": value = cfg.logRenderEvery
      of "consoleVizInterval": value = cfg.consoleVizInterval
      of "actionAuditInterval": value = cfg.actionAuditInterval
      of "actionFreqInterval": value = cfg.actionFreqInterval
      of "combatReportInterval": value = cfg.combatReportInterval
      of "tumorReportInterval": value = cfg.tumorReportInterval
      of "econReportInterval": value = cfg.econReportInterval
      of "techReportInterval": value = cfg.techReportInterval
      of "settlerReportInterval": value = cfg.settlerReportInterval
      of "flameInterval": value = cfg.flameInterval
      of "flameSample": value = cfg.flameSample
      of "perfWindow": value = cfg.perfWindow
      of "perfInterval": value = cfg.perfInterval
      of "heatmapInterval": value = cfg.heatmapInterval
      of "stateDumpInterval": value = cfg.stateDumpInterval
      of "eventLogInterval": value = cfg.eventLogInterval
      else: continue

      if value < desc.constraint.minInt or value > desc.constraint.maxInt:
        result.add ValidationError(
          field: desc.name,
          message: fmt"{desc.name} ({value}) must be between {desc.constraint.minInt} and {desc.constraint.maxInt}"
        )

    of cfkFloat:
      var value: float
      case desc.name
      of "perfThreshold": value = cfg.perfThreshold
      else: continue

      if value < desc.constraint.minFloat or value > desc.constraint.maxFloat:
        result.add ValidationError(
          field: desc.name,
          message: fmt"{desc.name} ({value}) must be between {desc.constraint.minFloat} and {desc.constraint.maxFloat}"
        )

    of cfkString:
      if desc.constraint.allowedValues.len > 0:
        var value: string
        case desc.name
        of "replayPath": value = cfg.replayPath
        of "scorecardPath": value = cfg.scorecardPath
        else: continue

        if value notin desc.constraint.allowedValues:
          result.add ValidationError(
            field: desc.name,
            message: fmt"{desc.name} ({value}) must be one of: {desc.constraint.allowedValues}"
          )

    of cfkBool:
      discard  # Booleans don't have constraints

# =============================================================================
# JSON Serialization (deterministic ordering for reproducibility)
# =============================================================================

proc toJson*(cfg: Config): JsonNode =
  ## Serialize configuration to JSON with deterministic key ordering.
  ## Keys are sorted alphabetically for reproducible output.
  result = newJObject()

  # Build sorted list of key-value pairs
  var pairs: seq[(string, JsonNode)] = @[
    ("actionAuditInterval", %cfg.actionAuditInterval),
    ("actionFreqInterval", %cfg.actionFreqInterval),
    ("combatReportInterval", %cfg.combatReportInterval),
    ("combatVerbose", %cfg.combatVerbose),
    ("consoleVizEnabled", %cfg.consoleVizEnabled),
    ("consoleVizInterval", %cfg.consoleVizInterval),
    ("debugAI", %cfg.debugAI),
    ("debugCombat", %cfg.debugCombat),
    ("debugEconomy", %cfg.debugEconomy),
    ("debugPathfinding", %cfg.debugPathfinding),
    ("econReportInterval", %cfg.econReportInterval),
    ("eventLogEnabled", %cfg.eventLogEnabled),
    ("eventLogInterval", %cfg.eventLogInterval),
    ("flameInterval", %cfg.flameInterval),
    ("flameSample", %cfg.flameSample),
    ("heatmapInterval", %cfg.heatmapInterval),
    ("logRenderEnabled", %cfg.logRenderEnabled),
    ("logRenderEvery", %cfg.logRenderEvery),
    ("logRenderWindow", %cfg.logRenderWindow),
    ("perfFailOnRegression", %cfg.perfFailOnRegression),
    ("perfInterval", %cfg.perfInterval),
    ("perfThreshold", %cfg.perfThreshold),
    ("perfWindow", %cfg.perfWindow),
    ("replayEnabled", %cfg.replayEnabled),
    ("replayPath", %cfg.replayPath),
    ("scorecardEnabled", %cfg.scorecardEnabled),
    ("scorecardPath", %cfg.scorecardPath),
    ("settlerReportInterval", %cfg.settlerReportInterval),
    ("stateDumpEnabled", %cfg.stateDumpEnabled),
    ("stateDumpInterval", %cfg.stateDumpInterval),
    ("stepTimingTarget", %cfg.stepTimingTarget),
    ("stepTimingWindow", %cfg.stepTimingWindow),
    ("techReportInterval", %cfg.techReportInterval),
    ("timingInterval", %cfg.timingInterval),
    ("tumorReportInterval", %cfg.tumorReportInterval)
  ]

  for (key, value) in pairs:
    result[key] = value

proc configFromJson*(node: JsonNode): Config =
  ## Deserialize configuration from JSON.
  ## Missing keys use default values.
  result = defaultConfig()

  if node.hasKey("actionAuditInterval"):
    result.actionAuditInterval = node["actionAuditInterval"].getInt()
  if node.hasKey("actionFreqInterval"):
    result.actionFreqInterval = node["actionFreqInterval"].getInt()
  if node.hasKey("combatReportInterval"):
    result.combatReportInterval = node["combatReportInterval"].getInt()
  if node.hasKey("combatVerbose"):
    result.combatVerbose = node["combatVerbose"].getBool()
  if node.hasKey("consoleVizEnabled"):
    result.consoleVizEnabled = node["consoleVizEnabled"].getBool()
  if node.hasKey("consoleVizInterval"):
    result.consoleVizInterval = node["consoleVizInterval"].getInt()
  if node.hasKey("debugAI"):
    result.debugAI = node["debugAI"].getBool()
  if node.hasKey("debugCombat"):
    result.debugCombat = node["debugCombat"].getBool()
  if node.hasKey("debugEconomy"):
    result.debugEconomy = node["debugEconomy"].getBool()
  if node.hasKey("debugPathfinding"):
    result.debugPathfinding = node["debugPathfinding"].getBool()
  if node.hasKey("econReportInterval"):
    result.econReportInterval = node["econReportInterval"].getInt()
  if node.hasKey("eventLogEnabled"):
    result.eventLogEnabled = node["eventLogEnabled"].getBool()
  if node.hasKey("eventLogInterval"):
    result.eventLogInterval = node["eventLogInterval"].getInt()
  if node.hasKey("flameInterval"):
    result.flameInterval = node["flameInterval"].getInt()
  if node.hasKey("flameSample"):
    result.flameSample = node["flameSample"].getInt()
  if node.hasKey("heatmapInterval"):
    result.heatmapInterval = node["heatmapInterval"].getInt()
  if node.hasKey("logRenderEnabled"):
    result.logRenderEnabled = node["logRenderEnabled"].getBool()
  if node.hasKey("logRenderEvery"):
    result.logRenderEvery = node["logRenderEvery"].getInt()
  if node.hasKey("logRenderWindow"):
    result.logRenderWindow = node["logRenderWindow"].getInt()
  if node.hasKey("perfFailOnRegression"):
    result.perfFailOnRegression = node["perfFailOnRegression"].getBool()
  if node.hasKey("perfInterval"):
    result.perfInterval = node["perfInterval"].getInt()
  if node.hasKey("perfThreshold"):
    result.perfThreshold = node["perfThreshold"].getFloat()
  if node.hasKey("perfWindow"):
    result.perfWindow = node["perfWindow"].getInt()
  if node.hasKey("replayEnabled"):
    result.replayEnabled = node["replayEnabled"].getBool()
  if node.hasKey("replayPath"):
    result.replayPath = node["replayPath"].getStr()
  if node.hasKey("scorecardEnabled"):
    result.scorecardEnabled = node["scorecardEnabled"].getBool()
  if node.hasKey("scorecardPath"):
    result.scorecardPath = node["scorecardPath"].getStr()
  if node.hasKey("settlerReportInterval"):
    result.settlerReportInterval = node["settlerReportInterval"].getInt()
  if node.hasKey("stateDumpEnabled"):
    result.stateDumpEnabled = node["stateDumpEnabled"].getBool()
  if node.hasKey("stateDumpInterval"):
    result.stateDumpInterval = node["stateDumpInterval"].getInt()
  if node.hasKey("stepTimingTarget"):
    result.stepTimingTarget = node["stepTimingTarget"].getInt()
  if node.hasKey("stepTimingWindow"):
    result.stepTimingWindow = node["stepTimingWindow"].getInt()
  if node.hasKey("techReportInterval"):
    result.techReportInterval = node["techReportInterval"].getInt()
  if node.hasKey("timingInterval"):
    result.timingInterval = node["timingInterval"].getInt()
  if node.hasKey("tumorReportInterval"):
    result.tumorReportInterval = node["tumorReportInterval"].getInt()

proc toJsonString*(cfg: Config, pretty: bool = true): string =
  ## Serialize configuration to a JSON string.
  let node = cfg.toJson()
  if pretty:
    return node.pretty()
  else:
    return $node

proc configFromJsonString*(s: string): Config =
  ## Deserialize configuration from a JSON string.
  let node = parseJson(s)
  return configFromJson(node)

# =============================================================================
# Help / Documentation Generation
# =============================================================================

proc help*(cfg: Config = defaultConfig()): string =
  ## Generate human-readable documentation for all configuration options.
  ## Groups options by category with descriptions, defaults, and env vars.
  var lines: seq[string] = @[]
  lines.add "Tribal Village Configuration"
  lines.add "============================"
  lines.add ""
  lines.add "All options can be set via environment variables."
  lines.add ""

  # Group by category
  var categories: Table[string, seq[ConfigFieldDesc]]
  for desc in ConfigFieldDescs:
    if not categories.hasKey(desc.category):
      categories[desc.category] = @[]
    categories[desc.category].add desc

  # Sort categories
  var catNames: seq[string] = @[]
  for cat in categories.keys:
    catNames.add cat
  catNames.sort()

  for cat in catNames:
    lines.add fmt"[{cat}]"
    lines.add ""

    for desc in categories[cat]:
      var defaultStr: string
      case desc.kind
      of cfkInt: defaultStr = $desc.defaultInt
      of cfkFloat: defaultStr = $desc.defaultFloat
      of cfkBool: defaultStr = $desc.defaultBool
      of cfkString: defaultStr = "\"" & desc.defaultString & "\""

      var typeStr: string
      case desc.kind
      of cfkInt: typeStr = "int"
      of cfkFloat: typeStr = "float"
      of cfkBool: typeStr = "bool"
      of cfkString: typeStr = "string"

      lines.add fmt"  {desc.envVar}"
      lines.add fmt"    Type: {typeStr}, Default: {defaultStr}"
      lines.add fmt"    {desc.description}"

      if desc.hasConstraint:
        case desc.kind
        of cfkInt:
          lines.add fmt"    Range: [{desc.constraint.minInt}, {desc.constraint.maxInt}]"
        of cfkFloat:
          lines.add fmt"    Range: [{desc.constraint.minFloat}, {desc.constraint.maxFloat}]"
        of cfkString:
          if desc.constraint.allowedValues.len > 0:
            lines.add fmt"    Allowed: {desc.constraint.allowedValues}"
        of cfkBool:
          discard

      lines.add ""

  result = lines.join("\n")

proc helpMarkdown*(cfg: Config = defaultConfig()): string =
  ## Generate Markdown documentation for all configuration options.
  var lines: seq[string] = @[]
  lines.add "# Tribal Village Configuration"
  lines.add ""
  lines.add "All options can be set via environment variables."
  lines.add ""

  # Group by category
  var categories: Table[string, seq[ConfigFieldDesc]]
  for desc in ConfigFieldDescs:
    if not categories.hasKey(desc.category):
      categories[desc.category] = @[]
    categories[desc.category].add desc

  # Sort categories
  var catNames: seq[string] = @[]
  for cat in categories.keys:
    catNames.add cat
  catNames.sort()

  for cat in catNames:
    lines.add fmt"## {cat}"
    lines.add ""
    lines.add "| Environment Variable | Type | Default | Description |"
    lines.add "|---------------------|------|---------|-------------|"

    for desc in categories[cat]:
      var defaultStr: string
      case desc.kind
      of cfkInt: defaultStr = $desc.defaultInt
      of cfkFloat: defaultStr = $desc.defaultFloat
      of cfkBool: defaultStr = $desc.defaultBool
      of cfkString: defaultStr = "`" & desc.defaultString & "`"

      var typeStr: string
      case desc.kind
      of cfkInt: typeStr = "int"
      of cfkFloat: typeStr = "float"
      of cfkBool: typeStr = "bool"
      of cfkString: typeStr = "string"

      var descWithConstraint = desc.description
      if desc.hasConstraint:
        case desc.kind
        of cfkInt:
          descWithConstraint &= fmt" (range: {desc.constraint.minInt}-{desc.constraint.maxInt})"
        of cfkFloat:
          descWithConstraint &= fmt" (range: {desc.constraint.minFloat}-{desc.constraint.maxFloat})"
        else:
          discard

      lines.add fmt"| `{desc.envVar}` | {typeStr} | {defaultStr} | {descWithConstraint} |"

    lines.add ""

  result = lines.join("\n")

proc envVars*(cfg: Config = defaultConfig()): seq[string] =
  ## Return list of all environment variable names.
  result = @[]
  for desc in ConfigFieldDescs:
    result.add desc.envVar

proc getFieldDesc*(name: string): ConfigFieldDesc =
  ## Look up a field descriptor by name.
  for desc in ConfigFieldDescs:
    if desc.name == name:
      return desc
  raise newException(KeyError, fmt"Unknown config field: {name}")

proc getFieldDescByEnvVar*(envVar: string): ConfigFieldDesc =
  ## Look up a field descriptor by environment variable name.
  for desc in ConfigFieldDescs:
    if desc.envVar == envVar:
      return desc
  raise newException(KeyError, fmt"Unknown environment variable: {envVar}")

# =============================================================================
# Override/Update Support (Pydantic-style)
# =============================================================================

proc override*(cfg: var Config, key: string, value: string): bool =
  ## Override a configuration value by field name.
  ## Returns true if the override was successful, false if the key was unknown.
  ## Parses the string value to the appropriate type.
  for desc in ConfigFieldDescs:
    if desc.name == key:
      case desc.kind
      of cfkInt:
        let intVal = try: parseInt(value) except ValueError: return false
        case key
        of "stepTimingTarget": cfg.stepTimingTarget = intVal
        of "stepTimingWindow": cfg.stepTimingWindow = intVal
        of "timingInterval": cfg.timingInterval = intVal
        of "logRenderWindow": cfg.logRenderWindow = intVal
        of "logRenderEvery": cfg.logRenderEvery = intVal
        of "consoleVizInterval": cfg.consoleVizInterval = intVal
        of "actionAuditInterval": cfg.actionAuditInterval = intVal
        of "actionFreqInterval": cfg.actionFreqInterval = intVal
        of "combatReportInterval": cfg.combatReportInterval = intVal
        of "tumorReportInterval": cfg.tumorReportInterval = intVal
        of "econReportInterval": cfg.econReportInterval = intVal
        of "techReportInterval": cfg.techReportInterval = intVal
        of "settlerReportInterval": cfg.settlerReportInterval = intVal
        of "flameInterval": cfg.flameInterval = intVal
        of "flameSample": cfg.flameSample = intVal
        of "perfWindow": cfg.perfWindow = intVal
        of "perfInterval": cfg.perfInterval = intVal
        of "heatmapInterval": cfg.heatmapInterval = intVal
        of "stateDumpInterval": cfg.stateDumpInterval = intVal
        of "eventLogInterval": cfg.eventLogInterval = intVal
        else: return false
      of cfkFloat:
        let floatVal = try: parseFloat(value) except ValueError: return false
        case key
        of "perfThreshold": cfg.perfThreshold = floatVal
        else: return false
      of cfkBool:
        let boolVal = value.toLowerAscii in ["1", "true", "yes", "on"]
        case key
        of "logRenderEnabled": cfg.logRenderEnabled = boolVal
        of "consoleVizEnabled": cfg.consoleVizEnabled = boolVal
        of "combatVerbose": cfg.combatVerbose = boolVal
        of "perfFailOnRegression": cfg.perfFailOnRegression = boolVal
        of "stateDumpEnabled": cfg.stateDumpEnabled = boolVal
        of "replayEnabled": cfg.replayEnabled = boolVal
        of "scorecardEnabled": cfg.scorecardEnabled = boolVal
        of "eventLogEnabled": cfg.eventLogEnabled = boolVal
        of "debugPathfinding": cfg.debugPathfinding = boolVal
        of "debugCombat": cfg.debugCombat = boolVal
        of "debugEconomy": cfg.debugEconomy = boolVal
        of "debugAI": cfg.debugAI = boolVal
        else: return false
      of cfkString:
        case key
        of "replayPath": cfg.replayPath = value
        of "scorecardPath": cfg.scorecardPath = value
        else: return false
      return true
  return false

proc update*(cfg: var Config, overrides: openArray[(string, string)]): seq[string] =
  ## Apply multiple overrides to the configuration.
  ## Returns a list of keys that failed to update.
  result = @[]
  for (key, value) in overrides:
    if not cfg.override(key, value):
      result.add key

# =============================================================================
# Diff Support
# =============================================================================

proc diff*(a, b: Config): seq[(string, string, string)] =
  ## Compare two configurations and return differences.
  ## Each tuple is (fieldName, valueInA, valueInB).
  result = @[]

  if a.stepTimingTarget != b.stepTimingTarget:
    result.add ("stepTimingTarget", $a.stepTimingTarget, $b.stepTimingTarget)
  if a.stepTimingWindow != b.stepTimingWindow:
    result.add ("stepTimingWindow", $a.stepTimingWindow, $b.stepTimingWindow)
  if a.timingInterval != b.timingInterval:
    result.add ("timingInterval", $a.timingInterval, $b.timingInterval)
  if a.logRenderEnabled != b.logRenderEnabled:
    result.add ("logRenderEnabled", $a.logRenderEnabled, $b.logRenderEnabled)
  if a.logRenderWindow != b.logRenderWindow:
    result.add ("logRenderWindow", $a.logRenderWindow, $b.logRenderWindow)
  if a.logRenderEvery != b.logRenderEvery:
    result.add ("logRenderEvery", $a.logRenderEvery, $b.logRenderEvery)
  if a.consoleVizEnabled != b.consoleVizEnabled:
    result.add ("consoleVizEnabled", $a.consoleVizEnabled, $b.consoleVizEnabled)
  if a.consoleVizInterval != b.consoleVizInterval:
    result.add ("consoleVizInterval", $a.consoleVizInterval, $b.consoleVizInterval)
  if a.actionAuditInterval != b.actionAuditInterval:
    result.add ("actionAuditInterval", $a.actionAuditInterval, $b.actionAuditInterval)
  if a.actionFreqInterval != b.actionFreqInterval:
    result.add ("actionFreqInterval", $a.actionFreqInterval, $b.actionFreqInterval)
  if a.combatReportInterval != b.combatReportInterval:
    result.add ("combatReportInterval", $a.combatReportInterval, $b.combatReportInterval)
  if a.combatVerbose != b.combatVerbose:
    result.add ("combatVerbose", $a.combatVerbose, $b.combatVerbose)
  if a.tumorReportInterval != b.tumorReportInterval:
    result.add ("tumorReportInterval", $a.tumorReportInterval, $b.tumorReportInterval)
  if a.econReportInterval != b.econReportInterval:
    result.add ("econReportInterval", $a.econReportInterval, $b.econReportInterval)
  if a.techReportInterval != b.techReportInterval:
    result.add ("techReportInterval", $a.techReportInterval, $b.techReportInterval)
  if a.settlerReportInterval != b.settlerReportInterval:
    result.add ("settlerReportInterval", $a.settlerReportInterval, $b.settlerReportInterval)
  if a.flameInterval != b.flameInterval:
    result.add ("flameInterval", $a.flameInterval, $b.flameInterval)
  if a.flameSample != b.flameSample:
    result.add ("flameSample", $a.flameSample, $b.flameSample)
  if a.perfWindow != b.perfWindow:
    result.add ("perfWindow", $a.perfWindow, $b.perfWindow)
  if a.perfInterval != b.perfInterval:
    result.add ("perfInterval", $a.perfInterval, $b.perfInterval)
  if a.perfThreshold != b.perfThreshold:
    result.add ("perfThreshold", $a.perfThreshold, $b.perfThreshold)
  if a.perfFailOnRegression != b.perfFailOnRegression:
    result.add ("perfFailOnRegression", $a.perfFailOnRegression, $b.perfFailOnRegression)
  if a.heatmapInterval != b.heatmapInterval:
    result.add ("heatmapInterval", $a.heatmapInterval, $b.heatmapInterval)
  if a.stateDumpEnabled != b.stateDumpEnabled:
    result.add ("stateDumpEnabled", $a.stateDumpEnabled, $b.stateDumpEnabled)
  if a.stateDumpInterval != b.stateDumpInterval:
    result.add ("stateDumpInterval", $a.stateDumpInterval, $b.stateDumpInterval)
  if a.replayEnabled != b.replayEnabled:
    result.add ("replayEnabled", $a.replayEnabled, $b.replayEnabled)
  if a.replayPath != b.replayPath:
    result.add ("replayPath", a.replayPath, b.replayPath)
  if a.scorecardEnabled != b.scorecardEnabled:
    result.add ("scorecardEnabled", $a.scorecardEnabled, $b.scorecardEnabled)
  if a.scorecardPath != b.scorecardPath:
    result.add ("scorecardPath", a.scorecardPath, b.scorecardPath)
  if a.eventLogEnabled != b.eventLogEnabled:
    result.add ("eventLogEnabled", $a.eventLogEnabled, $b.eventLogEnabled)
  if a.eventLogInterval != b.eventLogInterval:
    result.add ("eventLogInterval", $a.eventLogInterval, $b.eventLogInterval)
  if a.debugPathfinding != b.debugPathfinding:
    result.add ("debugPathfinding", $a.debugPathfinding, $b.debugPathfinding)
  if a.debugCombat != b.debugCombat:
    result.add ("debugCombat", $a.debugCombat, $b.debugCombat)
  if a.debugEconomy != b.debugEconomy:
    result.add ("debugEconomy", $a.debugEconomy, $b.debugEconomy)
  if a.debugAI != b.debugAI:
    result.add ("debugAI", $a.debugAI, $b.debugAI)
