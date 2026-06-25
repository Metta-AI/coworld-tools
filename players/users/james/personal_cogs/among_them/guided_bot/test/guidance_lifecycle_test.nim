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
  # Force no-provider behavior so the worker returns immediately
  # without touching the network. startGuidance is intentionally tested
  # directly. This matters on machines with Bedrock credentials.
  putEnv("GUIDED_BOT_LLM_DISABLE", "1")
  putEnv("GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES", "1")
  delEnv("ANTHROPIC_API_KEY")
  delEnv("COGAMES_LLM_PROVIDER")
  delEnv("COGAMES_LLM_MODEL")
  delEnv("CLAUDE_CODE_USE_BEDROCK")
  delEnv("USE_BEDROCK")

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
    let submitted = submitSnapshot(states[i], Snapshot(
      id: &"test-{i}",
      tick: 1000 + i,
      payloadJson: &"""{{"bot_index": {i}}}""",
      isMeeting: false,
      trigger: "test"
    ))
    expect(submitted, &"bot {i}: snapshot submitted")

  # Give the no-provider workers time to emit their trace event, then
  # drain repeatedly to catch scheduling variation without blocking the
  # test.
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
    expectEq(events.len, 3, &"bot {i}: exactly three guidance events")
    if events.len == 3:
      # Event 0: llm_init (emitted once at worker startup)
      expectEq(events[0]["kind"].getStr(), "llm_init",
               &"bot {i}: init event kind")
      expectEq(events[0]["init"]["provider_selected"].getStr(), "none",
               &"bot {i}: init provider")
      expect(events[0]["init"].hasKey("env_presence"),
             &"bot {i}: init env_presence present")
      # Event 1: snapshot_sent for the submitted snapshot
      expectEq(events[1]["t"].getInt(), 1000 + i,
               &"bot {i}: snapshot event tick isolated")
      expectEq(events[1]["kind"].getStr(), "snapshot_sent",
               &"bot {i}: snapshot event kind")
      expectEq(events[1]["snapshot_id"].getStr(), &"test-{i}",
               &"bot {i}: snapshot id")
      expectEq(events[1]["trigger"].getStr(), "test",
               &"bot {i}: snapshot trigger")
      expectEq(events[1]["snapshot"]["bot_index"].getInt(), i,
               &"bot {i}: snapshot payload")
      # Event 2: llm_call_failed for the no-provider case
      expectEq(events[2]["t"].getInt(), 1000 + i,
               &"bot {i}: failure event tick isolated")
      expectEq(events[2]["kind"].getStr(), "llm_call_failed",
               &"bot {i}: no-provider event kind")
      expectEq(events[2]["snapshot_id"].getStr(), &"test-{i}",
               &"bot {i}: failure snapshot id")
      expectEq(events[2]["reason"].getStr(), "no_key",
               &"bot {i}: no-provider reason")

  # When gameplay directives are disabled, a non-meeting snapshot should
  # never become an LLM call or directive. This is a worker-side guard for
  # the bot-level snapshot gate.
  putEnv("GUIDED_BOT_LLM_DISABLE", "0")
  putEnv("GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES", "0")

  var suppressedState = initGuidanceState()
  let suppressedWriter = openTrace(traceRoot / "suppressed_gameplay",
                                  TraceDecisions, 99)
  startGuidance(suppressedState)
  expect(suppressedState.running, "suppressed gameplay: guidance started")

  let submitted = submitSnapshot(suppressedState, Snapshot(
    id: "suppressed-gameplay",
    tick: 3000,
    payloadJson: """{"kind":"gameplay"}""",
    isMeeting: false,
    trigger: "periodic"
  ))
  expect(submitted, "suppressed gameplay: snapshot submitted")

  for _ in 0 ..< 100:
    drainGuidanceTraceEvents(suppressedState, suppressedWriter)
    sleep(10)

  stopGuidance(suppressedState)
  closeTrace(suppressedWriter)

  let suppressedEvents = readGuidanceEvents(suppressedWriter.rootDir)
  expectEq(suppressedEvents.len, 2,
           "suppressed gameplay: exactly two guidance events")
  if suppressedEvents.len == 2:
    # Event 0: llm_init at worker startup
    expectEq(suppressedEvents[0]["kind"].getStr(), "llm_init",
             "suppressed gameplay: init event kind")
    # Event 1: guidance_suppressed for the gameplay snapshot
    expectEq(suppressedEvents[1]["t"].getInt(), 3000,
             "suppressed gameplay: event tick")
    expectEq(suppressedEvents[1]["kind"].getStr(), "guidance_suppressed",
             "suppressed gameplay: event kind")
    expectEq(suppressedEvents[1]["reason"].getStr(),
             "gameplay_directives_disabled",
             "suppressed gameplay: reason")
    expectEq(suppressedEvents[1]["suppressed_request_kind"].getStr(),
             "gameplay",
             "suppressed gameplay: request kind")

  if failures == 0:
    echo "guidance_lifecycle_test: PASS"
  else:
    quit(failures)

main()
