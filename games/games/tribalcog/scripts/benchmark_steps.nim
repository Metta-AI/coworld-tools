## benchmark_steps.nim - Measure steps/second over 1000 steps
## with perf regression instrumentation
##
## Usage:
##   make benchmark
##
## Or manually:
##   TV_PERF_SAVE_BASELINE=baselines/benchmark.json \
##     nim c -r -d:perfRegression -d:release --path:src scripts/benchmark_steps.nim
##
## Environment variables:
##   TV_PERF_STEPS     - Steps to run (default: 1000)
##   TV_PERF_SEED      - Random seed (default: 42)
##   TV_PERF_WARMUP    - Warmup steps before measuring (default: 100)
##   TV_PERF_WINDOW    - Sliding window size (default: TV_PERF_STEPS)
##   TV_PERF_INTERVAL  - Report interval (default: TV_PERF_STEPS + TV_PERF_WARMUP)
##   TV_PERF_SAVE_BASELINE - Path to save baseline JSON
##   TV_PERF_BASELINE  - Path to load baseline for comparison
##   TV_PERF_THRESHOLD - Regression threshold % (default: 10)
##   TV_PERF_FAIL_ON_REGRESSION - "1" to exit non-zero on regression

import std/[os, strutils, strformat, monotimes, algorithm]
import envconfig
import environment
import agent_control

proc percentile(sorted: seq[float64], pct: float64): float64 =
  if sorted.len == 0: return 0.0
  let idx = int(float64(sorted.len - 1) * pct / 100.0)
  sorted[min(idx, sorted.len - 1)]

proc main() =
  let steps = parseEnvInt("TV_PERF_STEPS", 1000)
  let seed = parseEnvInt("TV_PERF_SEED", 42)
  let warmup = parseEnvInt("TV_PERF_WARMUP", 100)

  # Configure perf regression: window = measured steps, interval = total steps
  # so the subsystem report prints once at the very end of the run.
  # The circular window drops warmup samples, leaving exactly measured steps.
  if getEnv("TV_PERF_WINDOW") == "":
    putEnv("TV_PERF_WINDOW", $steps)
  if getEnv("TV_PERF_INTERVAL") == "":
    putEnv("TV_PERF_INTERVAL", $(steps + warmup))

  echo "=== Benchmark: tribal_village steps/second ==="
  echo &"  Steps:   {steps} (warmup: {warmup})"
  echo &"  Seed:    {seed}"
  echo &"  Compile: -d:release",
    (when defined(perfRegression): " -d:perfRegression" else: "")
  echo &"  Save:    {getEnv(\"TV_PERF_SAVE_BASELINE\", \"(none)\")}"
  echo &"  Compare: {getEnv(\"TV_PERF_BASELINE\", \"(none)\")}"
  echo ""

  initGlobalController(BuiltinAI, seed = seed)
  var env = newEnvironment()

  # Warmup phase - lets JIT, caches, and game state stabilize
  echo &"Warming up ({warmup} steps)..."
  for i in 0 ..< warmup:
    var actions = getActions(env)
    env.step(addr actions)

  # Measured run - time each step individually
  echo &"Running {steps} measured steps..."
  var stepTimes = newSeq[float64](steps)
  let wallStart = getMonoTime()

  for i in 0 ..< steps:
    let t0 = getMonoTime()
    var actions = getActions(env)
    env.step(addr actions)
    let t1 = getMonoTime()
    stepTimes[i] = (t1.ticks - t0.ticks).float64 / 1_000_000.0

    if i > 0 and i mod 200 == 0:
      echo &"  Step {i}/{steps}..."

  let wallEnd = getMonoTime()
  let wallMs = (wallEnd.ticks - wallStart.ticks).float64 / 1_000_000.0
  let wallSec = wallMs / 1000.0
  let stepsPerSec = float64(steps) / wallSec

  # Compute per-step statistics
  var sorted = stepTimes
  sort(sorted)
  let meanMs = wallMs / float64(steps)
  let p50Ms = percentile(sorted, 50.0)
  let p95Ms = percentile(sorted, 95.0)
  let p99Ms = percentile(sorted, 99.0)
  let minMs = sorted[0]
  let maxMs = sorted[^1]

  # Print wall-clock summary
  echo ""
  echo "=== Benchmark Results ==="
  echo ""
  echo "Wall Clock:"
  echo &"  Total time:    {wallSec:.3f}s"
  echo &"  Steps/second:  {stepsPerSec:.1f}"
  echo ""
  echo "Per-Step Timing (ms):"
  echo "  ", align("Mean", 6), ": ", formatFloat(meanMs, ffDecimal, 4)
  echo "  ", align("P50", 6), ": ", formatFloat(p50Ms, ffDecimal, 4)
  echo "  ", align("P95", 6), ": ", formatFloat(p95Ms, ffDecimal, 4)
  echo "  ", align("P99", 6), ": ", formatFloat(p99Ms, ffDecimal, 4)
  echo "  ", align("Min", 6), ": ", formatFloat(minMs, ffDecimal, 4)
  echo "  ", align("Max", 6), ": ", formatFloat(maxMs, ffDecimal, 4)

  # Per-subsystem breakdown was printed by perf_regression at TV_PERF_INTERVAL
  when defined(perfRegression):
    echo ""
    if perfRegressionDetected():
      echo "RESULT: REGRESSION DETECTED"
      if parseEnvBool("TV_PERF_FAIL_ON_REGRESSION", false):
        quit(1)
    else:
      echo "RESULT: No regressions detected"

  echo ""
  echo "=== Benchmark Complete ==="

main()
