## Focused lifecycle regression test for guided_bot guidance workers.
##
## Run:
##   nim c -r --nimcache:among_them/guided_bot/.nimcache \
##       -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/guidance_lifecycle_test.nim

import std/[json, os, strformat, strutils]
import ../guidance
import ../trace

const BotCount = 8

var failures = 0

proc expect(cond: bool, label: string) =
  if not cond:
    stderr.writeLine "FAIL: ", label
    inc failures

proc expectEq[T](got, want: T, label: string) =
  if got != want:
    stderr.writeLine &"FAIL: {label}: got {got}, want {want}"
    inc failures

proc readGuidanceEvents(rootDir: string): seq[JsonNode] =
  let path = rootDir / "guidance.jsonl"
  if not fileExists(path):
    return
  for line in readFile(path).splitLines():
    let clean = line.strip()
    if clean.len > 0:
      result.add parseJson(clean)

proc main() =
  # Force no-key behavior so the worker returns immediately without
  # touching the network. startGuidance is intentionally tested directly.
  delEnv("ANTHROPIC_API_KEY")

  let traceRoot = getTempDir() / "guided_bot_guidance_lifecycle_" &
    $getCurrentProcessId()
  createDir(traceRoot)

  var states: array[BotCount, GuidanceState]
  var writers: array[BotCount, TraceWriter]
  var roots: array[BotCount, string]

  for i in 0 ..< BotCount:
    states[i] = initGuidanceState()
    writers[i] = openTrace(traceRoot / &"bot_{i}", TraceDecisions, i)
    roots[i] = writers[i].rootDir
    startGuidance(states[i])
    expect(states[i].running, &"bot {i}: guidance started")

  for i in 0 ..< BotCount:
    submitSnapshot(states[i], Snapshot(
      tick: 1000 + i,
      payloadJson: &"""{{"bot_index": {i}}}""",
      isMeeting: false
    ))

  # Give the no-key workers time to emit their trace event, then drain
  # repeatedly to catch scheduling variation without blocking the test.
  for _ in 0 ..< 100:
    for i in 0 ..< BotCount:
      drainGuidanceTraceEvents(states[i], writers[i])
    sleep(10)

  for i in countdown(BotCount - 1, 0):
    stopGuidance(states[i])
    expect(not states[i].running, &"bot {i}: guidance stopped")
    stopGuidance(states[i])
    expect(not states[i].running, &"bot {i}: second stop is idempotent")

  for i in 0 ..< BotCount:
    closeTrace(writers[i])

  for i in 0 ..< BotCount:
    let events = readGuidanceEvents(roots[i])
    expectEq(events.len, 1, &"bot {i}: exactly one guidance event")
    if events.len == 1:
      expectEq(events[0]["t"].getInt(), 1000 + i,
               &"bot {i}: guidance event tick isolated")
      expectEq(events[0]["kind"].getStr(), "llm_call_failed",
               &"bot {i}: no-key event kind")
      expectEq(events[0]["reason"].getStr(), "no_key",
               &"bot {i}: no-key reason")

  if failures == 0:
    echo "guidance_lifecycle_test: PASS"
  else:
    quit(failures)

main()
