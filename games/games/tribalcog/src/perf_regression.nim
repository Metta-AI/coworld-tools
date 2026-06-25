## Performance regression detection with sliding-window timing baselines.

when defined(perfRegression):
  import
    std/[algorithm, json, os, strutils],
    envconfig

  const
    PerfSubsystemCount* = 11
    PerfSubsystemNames*: array[PerfSubsystemCount, string] = [
      "actionTint", "shields", "preDeaths", "actions", "things",
      "tumors", "tumorDamage", "auras", "popRespawn", "survival",
      "tintObs"
    ]
    PerfSubsystemCategory*: array[PerfSubsystemCount, string] = [
      "rendering", "physics", "physics", "AI", "physics", "physics",
      "physics", "physics", "AI", "physics", "rendering"
    ]
    DefaultThresholdPct = 10.0
    DefaultWindowSize = 100
    DefaultReportInterval = 100

  type
    PerfBaseline* = object
      ## Baseline summary statistics for one window of samples.
      mean*: array[PerfSubsystemCount, float64]
      p95*: array[PerfSubsystemCount, float64]
      p99*: array[PerfSubsystemCount, float64]
      totalMean*: float64
      totalP95*: float64
      totalP99*: float64
      stepCount*: int
      windowSize*: int

    PerfSlidingWindow* = object
      ## Circular buffer of recent subsystem timing samples.
      samples: seq[array[PerfSubsystemCount, float64]]
      totalSamples: seq[float64]
      head: int
      count: int
      capacity: int

    PerfRegressionState* = object
      window*: PerfSlidingWindow
      baseline*: PerfBaseline
      hasBaseline*: bool
      thresholdPct*: float64
      reportInterval*: int
      stepsSinceReport*: int
      failOnRegression*: bool
      saveBaselinePath*: string
      regressionDetected*: bool

  var
    perfState*: PerfRegressionState
    perfInitialized = false

  proc initSlidingWindow(capacity: int): PerfSlidingWindow =
    ## Initialize one circular timing-sample window.
    result.capacity = capacity
    result.samples = newSeq[array[PerfSubsystemCount, float64]](capacity)
    result.totalSamples = newSeq[float64](capacity)
    result.head = 0
    result.count = 0

  proc pushSample(
    window: var PerfSlidingWindow,
    subsystems: array[PerfSubsystemCount, float64],
    total: float64
  ) =
    ## Push one timing sample into the sliding window.
    window.samples[window.head] = subsystems
    window.totalSamples[window.head] = total
    window.head = (window.head + 1) mod window.capacity
    if window.count < window.capacity:
      inc window.count

  proc computePercentile(values: var seq[float64], pct: float64): float64 =
    ## Compute one percentile from a sequence in place.
    if values.len == 0:
      return 0.0
    sort(values)
    let idx = int(float64(values.len - 1) * pct / 100.0)
    values[min(idx, values.len - 1)]

  proc computeWindowStats(window: PerfSlidingWindow): PerfBaseline =
    ## Compute summary statistics from the current sliding window.
    if window.count == 0:
      return

    result.stepCount = window.count
    result.windowSize = window.capacity

    var subsystemValues: array[PerfSubsystemCount, seq[float64]]
    var totalValues = newSeq[float64](window.count)

    for subsystemIdx in 0 ..< PerfSubsystemCount:
      subsystemValues[subsystemIdx] = newSeq[float64](window.count)

    for i in 0 ..< window.count:
      let sampleIdx =
        if window.count < window.capacity:
          i
        else:
          (window.head + i) mod window.capacity
      for subsystemIdx in 0 ..< PerfSubsystemCount:
        subsystemValues[subsystemIdx][i] =
          window.samples[sampleIdx][subsystemIdx]
      totalValues[i] = window.totalSamples[sampleIdx]

    for subsystemIdx in 0 ..< PerfSubsystemCount:
      var sum = 0.0
      for value in subsystemValues[subsystemIdx]:
        sum += value
      result.mean[subsystemIdx] = sum / float64(window.count)
      result.p95[subsystemIdx] =
        computePercentile(subsystemValues[subsystemIdx], 95.0)
      result.p99[subsystemIdx] =
        computePercentile(subsystemValues[subsystemIdx], 99.0)

    var totalSum = 0.0
    for value in totalValues:
      totalSum += value
    result.totalMean = totalSum / float64(window.count)
    result.totalP95 = computePercentile(totalValues, 95.0)
    result.totalP99 = computePercentile(totalValues, 99.0)

  proc baselineToJson(baseline: PerfBaseline): JsonNode =
    ## Serialize one performance baseline to JSON.
    result = newJObject()
    result["stepCount"] = %baseline.stepCount
    result["windowSize"] = %baseline.windowSize
    result["totalMean"] = %baseline.totalMean
    result["totalP95"] = %baseline.totalP95
    result["totalP99"] = %baseline.totalP99

    var subsystems = newJObject()
    for subsystemIdx in 0 ..< PerfSubsystemCount:
      var entry = newJObject()
      entry["mean"] = %baseline.mean[subsystemIdx]
      entry["p95"] = %baseline.p95[subsystemIdx]
      entry["p99"] = %baseline.p99[subsystemIdx]
      subsystems[PerfSubsystemNames[subsystemIdx]] = entry
    result["subsystems"] = subsystems

  proc baselineFromJson(node: JsonNode): PerfBaseline =
    ## Deserialize one performance baseline from JSON.
    result.stepCount = node["stepCount"].getInt()
    result.windowSize = node["windowSize"].getInt()
    result.totalMean = node["totalMean"].getFloat()
    result.totalP95 = node["totalP95"].getFloat()
    result.totalP99 = node["totalP99"].getFloat()

    let subsystems = node["subsystems"]
    for subsystemIdx in 0 ..< PerfSubsystemCount:
      let name = PerfSubsystemNames[subsystemIdx]
      if subsystems.hasKey(name):
        let entry = subsystems[name]
        result.mean[subsystemIdx] = entry["mean"].getFloat()
        result.p95[subsystemIdx] = entry["p95"].getFloat()
        result.p99[subsystemIdx] = entry["p99"].getFloat()

  proc saveBaseline*(baseline: PerfBaseline, path: string) =
    ## Save one captured baseline to disk.
    let jsonNode = baselineToJson(baseline)
    writeFile(path, $jsonNode)
    echo "[perf] Baseline saved to ", path

  proc loadBaseline*(path: string): PerfBaseline =
    ## Load one saved baseline from disk.
    let
      content = readFile(path)
      node = parseJson(content)
    result = baselineFromJson(node)
    echo(
      "[perf] Baseline loaded from ",
      path,
      " (",
      result.stepCount,
      " samples, window=",
      result.windowSize,
      ")"
    )

  proc initPerfRegression*() =
    ## Initialize regression detection from environment settings.
    let
      windowSize = parseEnvInt("TV_PERF_WINDOW", DefaultWindowSize)
      interval = parseEnvInt("TV_PERF_INTERVAL", DefaultReportInterval)
      baselinePath = getEnv("TV_PERF_BASELINE", "")
      savePath = getEnv("TV_PERF_SAVE_BASELINE", "")

    perfState.window = initSlidingWindow(windowSize)
    perfState.thresholdPct =
      parseEnvFloat("TV_PERF_THRESHOLD", DefaultThresholdPct)
    perfState.reportInterval = max(1, interval)
    perfState.stepsSinceReport = 0
    perfState.saveBaselinePath = savePath
    perfState.failOnRegression =
      parseEnvBool("TV_PERF_FAIL_ON_REGRESSION", false)
    perfState.regressionDetected = false

    if baselinePath.len > 0 and fileExists(baselinePath):
      perfState.baseline = loadBaseline(baselinePath)
      perfState.hasBaseline = true
    else:
      perfState.hasBaseline = false

    perfInitialized = true

  proc ensurePerfInit*() =
    ## Initialize regression detection on first use.
    if not perfInitialized:
      initPerfRegression()

  proc recordPerfStep*(
    subsystems: array[PerfSubsystemCount, float64],
    totalMs: float64
  ) =
    ## Record one step timing sample.
    ensurePerfInit()
    pushSample(perfState.window, subsystems, totalMs)
    inc perfState.stepsSinceReport

  proc checkPerfRegression*(currentStep: int) =
    ## Print the regression report when the report interval elapses.
    ensurePerfInit()
    if perfState.stepsSinceReport < perfState.reportInterval:
      return

    perfState.stepsSinceReport = 0
    let stats = computeWindowStats(perfState.window)
    if stats.stepCount == 0:
      return

    echo ""
    echo(
      "=== Perf Regression Report (step ",
      currentStep,
      ", window=",
      stats.stepCount,
      ") ==="
    )
    echo(
      alignLeft("Subsystem", 14), " | ",
      align("Mean ms", 10), " | ",
      align("P95 ms", 10), " | ",
      align("P99 ms", 10),
      if perfState.hasBaseline:
        " | " & align("Δ Mean%", 9)
      else:
        ""
    )
    echo(
      repeat("-", 14), "-+-", repeat("-", 10), "-+-", repeat("-", 10),
      "-+-", repeat("-", 10),
      if perfState.hasBaseline:
        "-+-" & repeat("-", 9)
      else:
        ""
    )

    var
      worstSubsystem = -1
      worstDeltaPct = 0.0

    for subsystemIdx in 0 ..< PerfSubsystemCount:
      var deltaPctText = ""
      if perfState.hasBaseline and perfState.baseline.mean[subsystemIdx] > 0.0:
        let deltaPct =
          (stats.mean[subsystemIdx] - perfState.baseline.mean[subsystemIdx]) /
          perfState.baseline.mean[subsystemIdx] * 100.0
        if deltaPct > worstDeltaPct:
          worstDeltaPct = deltaPct
          worstSubsystem = subsystemIdx
        let sign =
          if deltaPct >= 0.0:
            "+"
          else:
            ""
        deltaPctText =
          " | " & align(sign & formatFloat(deltaPct, ffDecimal, 1) & "%", 9)
      elif perfState.hasBaseline:
        deltaPctText = " | " & align("N/A", 9)

      echo(
        alignLeft(PerfSubsystemNames[subsystemIdx], 14), " | ",
        align(formatFloat(stats.mean[subsystemIdx], ffDecimal, 4), 10), " | ",
        align(formatFloat(stats.p95[subsystemIdx], ffDecimal, 4), 10), " | ",
        align(formatFloat(stats.p99[subsystemIdx], ffDecimal, 4), 10),
        deltaPctText
      )

    var totalDeltaText = ""
    if perfState.hasBaseline and perfState.baseline.totalMean > 0.0:
      let totalDelta =
        (stats.totalMean - perfState.baseline.totalMean) /
        perfState.baseline.totalMean * 100.0
      let sign =
        if totalDelta >= 0.0:
          "+"
        else:
          ""
      totalDeltaText =
        " | " & align(sign & formatFloat(totalDelta, ffDecimal, 1) & "%", 9)

    echo(
      repeat("-", 14), "-+-", repeat("-", 10), "-+-", repeat("-", 10),
      "-+-", repeat("-", 10),
      if perfState.hasBaseline:
        "-+-" & repeat("-", 9)
      else:
        ""
    )
    echo(
      alignLeft("TOTAL", 14), " | ",
      align(formatFloat(stats.totalMean, ffDecimal, 4), 10), " | ",
      align(formatFloat(stats.totalP95, ffDecimal, 4), 10), " | ",
      align(formatFloat(stats.totalP99, ffDecimal, 4), 10),
      totalDeltaText
    )

    if perfState.hasBaseline:
      let totalDelta =
        if perfState.baseline.totalMean > 0.0:
          (stats.totalMean - perfState.baseline.totalMean) /
            perfState.baseline.totalMean * 100.0
        else:
          0.0

      if totalDelta > perfState.thresholdPct:
        perfState.regressionDetected = true
        echo ""
        echo(
          "⚠ REGRESSION DETECTED: total step time +",
          formatFloat(totalDelta, ffDecimal, 1),
          "% (threshold: ",
          formatFloat(perfState.thresholdPct, ffDecimal, 1),
          "%)"
        )
        if worstSubsystem >= 0:
          echo(
            "  Worst offender: ",
            PerfSubsystemNames[worstSubsystem],
            " (",
            PerfSubsystemCategory[worstSubsystem],
            ") +",
            formatFloat(worstDeltaPct, ffDecimal, 1),
            "%"
          )
      else:
        echo ""
        echo(
          "✓ No regression (total Δ ",
          if totalDelta >= 0.0:
            "+"
          else:
            "",
          formatFloat(totalDelta, ffDecimal, 1),
          "%, threshold: ",
          formatFloat(perfState.thresholdPct, ffDecimal, 1),
          "%)"
        )

    echo ""
    if perfState.saveBaselinePath.len > 0:
      saveBaseline(stats, perfState.saveBaselinePath)
