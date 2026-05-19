## Fuzz seed testing: run 100 games with random seeds for 200 steps each.
## Verify no crashes, no assertion failures, no infinite loops.
## Report any failing seeds for reproduction.
## Run with: nim r --path:src tests/fuzz_seeds.nim

import std/[strformat, times]
import environment
import agent_control
import types

const
  NumSeeds = 100
  StepsPerGame = 200
  ## Timeout per game in seconds — detect infinite loops
  GameTimeoutSecs = 60.0

type
  FuzzResult = object
    seed: int
    stepsCompleted: int
    crashed: bool
    errorMsg: string
    elapsedSecs: float

proc runGameWithSeed(seed: int): FuzzResult =
  result.seed = seed
  let startTime = cpuTime()
  try:
    initGlobalController(BuiltinAI, seed = seed)
    var env = newEnvironment()

    for step in 0 ..< StepsPerGame:
      var actions = getActions(env)
      env.step(addr actions)

      # Check for timeout (infinite loop detection)
      let elapsed = cpuTime() - startTime
      if elapsed > GameTimeoutSecs:
        result.crashed = true
        result.errorMsg = &"Timeout after {elapsed:.1f}s at step {step}"
        result.stepsCompleted = step
        result.elapsedSecs = elapsed
        return

      if env.shouldReset:
        result.stepsCompleted = step + 1
        result.elapsedSecs = cpuTime() - startTime
        return

    result.stepsCompleted = StepsPerGame
    result.elapsedSecs = cpuTime() - startTime
  except CatchableError as e:
    result.crashed = true
    result.errorMsg = &"{e.name}: {e.msg}"
    result.elapsedSecs = cpuTime() - startTime
  except Defect as e:
    result.crashed = true
    result.errorMsg = &"DEFECT {e.name}: {e.msg}"
    result.elapsedSecs = cpuTime() - startTime

proc main() =
  echo &"=== Fuzz Seed Testing: {NumSeeds} games x {StepsPerGame} steps ==="
  echo ""

  var failedSeeds: seq[FuzzResult]
  var totalElapsed = 0.0

  for i in 0 ..< NumSeeds:
    let seed = i + 1  # Seeds 1..100
    let r = runGameWithSeed(seed)
    totalElapsed += r.elapsedSecs

    if r.crashed:
      echo &"  CRASH seed={seed}: {r.errorMsg} (step {r.stepsCompleted})"
      failedSeeds.add(r)
    else:
      # Progress indicator every 10 games
      if (i + 1) mod 10 == 0:
        echo &"  ... {i + 1}/{NumSeeds} seeds OK ({totalElapsed:.1f}s elapsed)"

  echo ""
  echo &"=== Results ==="
  echo &"  Total seeds tested: {NumSeeds}"
  echo &"  Passed: {NumSeeds - failedSeeds.len}"
  echo &"  Failed: {failedSeeds.len}"
  echo &"  Total time: {totalElapsed:.1f}s"

  if failedSeeds.len > 0:
    echo ""
    echo "=== Failing Seeds (for reproduction) ==="
    for r in failedSeeds:
      echo &"  Seed {r.seed}: {r.errorMsg} (completed {r.stepsCompleted}/{StepsPerGame} steps)"
    echo ""
    echo "To reproduce a failure:"
    echo "  nim r --path:src tests/fuzz_seeds.nim  # or isolate with specific seed"
    quit(1)
  else:
    echo ""
    echo "All seeds passed. No crashes, assertion failures, or infinite loops detected."

main()
