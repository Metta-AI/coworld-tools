## Per-step flame graph sampling helpers for optional profiling output.

when defined(flameGraph):
  import
    std/[monotimes, os, strutils]

  const
    FlameSubsystemCount* = 11
    FlameSubsystemNames*: array[FlameSubsystemCount, string] = [
      "actionTint", "shields", "preDeaths", "actions", "things",
      "tumors", "tumorDamage", "auras", "popRespawn", "survival",
      "tintObs"
    ]
    DefaultFlameOutput = "flame_graph.folded"
    DefaultFlameInterval = 100
    DefaultFlameSample = 1

  type
    FlameGraphState* = object
      outputPath*: string
      flushInterval*: int
      sampleInterval*: int
      stepsSinceFlush*: int
      buffer*: seq[string]
      fileHandle*: File
      isOpen*: bool
      totalSamples*: int

  var
    flameState*: FlameGraphState
    flameInitialized = false

  proc usBetween(a, b: MonoTime): int64 =
    ## Return the microseconds between two monotonic times.
    (b.ticks - a.ticks) div 1000

  proc initFlameGraph*() =
    ## Initialize flame graph output state from environment settings.
    let
      outputPath = getEnv("TV_FLAME_OUTPUT", DefaultFlameOutput)
      flushInterval = parseEnvInt("TV_FLAME_INTERVAL", DefaultFlameInterval)
      sampleInterval = parseEnvInt("TV_FLAME_SAMPLE", DefaultFlameSample)

    flameState.outputPath = outputPath
    flameState.flushInterval = max(1, flushInterval)
    flameState.sampleInterval = max(1, sampleInterval)
    flameState.stepsSinceFlush = 0
    flameState.buffer = @[]
    flameState.totalSamples = 0

    try:
      flameState.fileHandle = open(outputPath, fmWrite)
      flameState.isOpen = true
      echo(
        "[flameGraph] Output file: ",
        outputPath,
        " (flush every ",
        flushInterval,
        " steps, sample every ",
        sampleInterval,
        " steps)"
      )
    except IOError as err:
      echo(
        "[flameGraph] WARNING: Could not open output file ",
        outputPath,
        ": ",
        err.msg
      )
      flameState.isOpen = false

    flameInitialized = true

  proc ensureFlameInit*() =
    ## Initialize flame graph state on first use.
    if not flameInitialized:
      initFlameGraph()

  proc flushFlameBuffer*() =
    ## Write buffered flame graph samples to disk.
    if not flameState.isOpen or flameState.buffer.len == 0:
      return

    try:
      for line in flameState.buffer:
        flameState.fileHandle.writeLine(line)
      flameState.fileHandle.flushFile()
      flameState.buffer.setLen(0)
    except IOError:
      discard

  proc recordFlameStep*(
    currentStep: int,
    subsystems: array[FlameSubsystemCount, int64],
    totalUs: int64
  ) =
    ## Record one step of subsystem timings in collapsed stack format.
    discard totalUs
    ensureFlameInit()
    if currentStep mod flameState.sampleInterval != 0:
      return

    for subsystemIdx in 0 ..< FlameSubsystemCount:
      if subsystems[subsystemIdx] > 0:
        let line =
          "step;" & FlameSubsystemNames[subsystemIdx] &
          " " & $subsystems[subsystemIdx]
        flameState.buffer.add(line)

    inc flameState.totalSamples
    inc flameState.stepsSinceFlush
    if flameState.stepsSinceFlush >= flameState.flushInterval:
      flushFlameBuffer()
      flameState.stepsSinceFlush = 0

  proc closeFlameGraph*() =
    ## Flush any buffered samples and close the output file.
    if not flameInitialized:
      return

    flushFlameBuffer()
    if flameState.isOpen:
      try:
        flameState.fileHandle.close()
        echo(
          "[flameGraph] Closed output file: ",
          flameState.outputPath,
          " (",
          flameState.totalSamples,
          " samples)"
        )
      except IOError:
        discard
      flameState.isOpen = false
