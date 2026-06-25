## Guidance-loop worker thread — phase 3.
##
## Spawns an OS thread that:
##   - blocks on its per-bot `snapshotChan` (newest-snapshot-wins),
##   - renders a prompt, calls `llm.callLlm`, parses and validates the
##     response,
##   - pushes the validated `Directive` onto `directiveChan`, and during
##     meetings pushes `MeetingAction` values onto `meetingActionChan`.
##
## The inner loop never blocks on this. See DESIGN.md §10.
##
## Concurrency model (DESIGN.md §10.2-10.3):
##   - Main thread: inner loop (perceive/update/decide/act). Owns
##     belief, scratch, action state.
##   - Worker thread: blocks on snapshot channel, calls LLM, pushes
##     directive (or meeting action) onto outgoing channel.
##
## Channels (Nim `system.Channel[T]`):
##   - `snapshotChan`: main → worker. Bounded, newest wins.
##   - `directiveChan`: worker → main. Main reads non-blocking.
##   - `meetingActionChan`: worker → main. FIFO, one per tick.

import std/json
import types
import tuning
import llm
import trace

type
  Snapshot* = object
    ## The curated JSON snapshot the LLM sees (DESIGN.md §8.3) plus a
    ## request kind and conversation handle.
    id*: string
    tick*: int
    payloadJson*: string
    isMeeting*: bool
    trigger*: string

  ## Sentinel value sent on snapshotChan to tell the worker to exit.
  ## When tick == -1, the worker breaks out of its loop.

  GuidanceRuntime = object
    ## Heap-stable per-bot guidance runtime. Bots live in resizable seqs,
    ## so the worker receives this pointer instead of a Bot/GuidanceState
    ## address that might move.
    snapshotChan: Channel[Snapshot]
    directiveChan: Channel[Directive]
    meetingActionChan: Channel[MeetingAction]
    traceEventChan: Channel[string]
    workerThread: Thread[ptr GuidanceRuntime]

  GuidanceState* = object
    ## Main-thread handle to the guidance subsystem. Holds channel
    ## references, the worker thread handle, per-meeting conversation
    ## history, and call-rate accounting.
    running*: bool
    callsThisMatch*: int
    lastCallTick*: int
    meetingConversationJson*: string
    ## Whether we're currently in a meeting (for conversation mgmt).
    inMeeting*: bool
    runtime: ptr GuidanceRuntime

proc meetingActionToJson(action: MeetingAction): JsonNode =
  result = newJObject()
  result["action_kind"] = newJString($action.kind)
  if action.text.len > 0:
    result["text"] = newJString(action.text)
  if action.kind == MeetingActVote:
    result["target"] = newJInt(action.target)

# ---------------------------------------------------------------------------
# Worker thread procedure
# ---------------------------------------------------------------------------

proc guidanceWorker(runtime: ptr GuidanceRuntime) {.thread.} =
  ## Worker thread main loop. Blocks on snapshotChan, calls the LLM,
  ## pushes results onto directiveChan / meetingActionChan.
  ##
  ## Meeting conversation history is maintained as thread-local state
  ## within this proc to avoid GC-safety issues with global seqs.
  if runtime.isNil:
    return

  var meetingHistory: seq[tuple[role: string, content: string]]
  var wasInMeeting = false

  # One-shot startup trace: record which LLM provider was selected and
  # what env presence drove that choice. Self-contained per match so a
  # later failure trace doesn't depend on its sibling line being
  # retained in the ring buffer.
  block:
    var ev = newJObject()
    ev["t"] = newJInt(0)
    ev["kind"] = newJString("llm_init")
    ev["init"] = dumpLlmInit()
    runtime[].traceEventChan.send($ev)

  while true:
    # Block until a snapshot arrives.
    let snap = runtime[].snapshotChan.recv()

    # Sentinel: tick == -1 means exit.
    if snap.tick < 0:
      break

    # If transitioning out of a meeting, flush conversation history.
    if wasInMeeting and not snap.isMeeting:
      meetingHistory.setLen(0)
    wasInMeeting = snap.isMeeting

    if not snap.isMeeting and not gameplayLlmDirectivesEnabled():
      var ev = newJObject()
      ev["t"] = newJInt(snap.tick)
      ev["kind"] = newJString("guidance_suppressed")
      ev["reason"] = newJString("gameplay_directives_disabled")
      ev["suppressed_request_kind"] = newJString("gameplay")
      if snap.id.len > 0:
        ev["snapshot_id"] = newJString(snap.id)
      if snap.trigger.len > 0:
        ev["trigger"] = newJString(snap.trigger)
      runtime[].traceEventChan.send($ev)
      continue

    # Build the LLM request.
    var req: LlmRequest
    if snap.isMeeting:
      req = LlmRequest(
        kind: LlmReqMeeting,
        snapshotJson: snap.payloadJson,
        conversationJson: ""
      )
      # Serialize conversation history for the LLM client.
      if meetingHistory.len > 0:
        var convArr = newJArray()
        for msg in meetingHistory:
          convArr.add %*{"role": msg.role, "content": msg.content}
        req.conversationJson = $convArr
    else:
      req = LlmRequest(
        kind: LlmReqGameplay,
        snapshotJson: snap.payloadJson
      )

    # Trace the exact snapshot payload that is about to be sent to the
    # provider. Logging from the worker avoids recording snapshots that
    # were only queued and then replaced by the newest-wins channel.
    block:
      var ev = newJObject()
      ev["t"] = newJInt(snap.tick)
      ev["kind"] = newJString("snapshot_sent")
      if snap.id.len > 0:
        ev["snapshot_id"] = newJString(snap.id)
      if snap.trigger.len > 0:
        ev["trigger"] = newJString(snap.trigger)
      ev["request_kind"] = newJString(if snap.isMeeting: "meeting" else: "gameplay")
      try:
        ev["snapshot"] = parseJson(snap.payloadJson)
      except CatchableError:
        ev["snapshot_raw"] = newJString(snap.payloadJson)
      runtime[].traceEventChan.send($ev)

    # Call the LLM (synchronous, blocks this thread only).
    let result = callLlm(req)

    # Phase 4: push trace events onto the channel for the main thread
    # to drain. We serialize to JSON strings here (thread-local) to
    # avoid GC-safety issues with ref objects.
    block traceEvents:
      var ev = newJObject()
      ev["t"] = newJInt(snap.tick)
      if snap.id.len > 0:
        ev["snapshot_id"] = newJString(snap.id)
      if result.kind == LlmOk:
        ev["kind"] = newJString("llm_response")
        ev["latency_ms"] = newJInt(result.latencyMs)
        ev["prompt_tokens"] = newJInt(result.promptTokens)
        ev["response_tokens"] = newJInt(result.responseTokens)
        if result.rawResponse.len > 0:
          ev["raw_response"] = newJString(result.rawResponse)
        if snap.isMeeting:
          ev["parsed"] = meetingActionToJson(result.meetingAction)
        else:
          var parsed = newJObject()
          parsed["mode"] = newJString($result.directive.mode)
          parsed["params"] = paramsToJson(result.directive.params)
          parsed["ttl_ticks"] = newJInt(result.directive.ttlTicks)
          ev["parsed"] = parsed
        ev["validation"] = newJString("ok")
      else:
        ev["kind"] = newJString("llm_call_failed")
        let reason = case result.kind
          of LlmHttpError:    "http_error"
          of LlmTimeout:      "timeout"
          of LlmRateLimit:    "rate_limit"
          of LlmSchemaError:  "schema_error"
          of LlmNoKey:        "no_key"
          of LlmOk:           "ok"  # unreachable
        ev["reason"] = newJString(reason)
        if result.detail.len > 0:
          ev["detail"] = newJString(result.detail)
      runtime[].traceEventChan.send($ev)

    if result.kind == LlmOk:
      if snap.isMeeting:
        # Append to meeting conversation history.
        meetingHistory.add (
          role: "user",
          content: "Current meeting state:\n" & snap.payloadJson &
                   "\n\nProduce your next meeting action as a JSON object."
        )
        meetingHistory.add (
          role: "assistant",
          content: result.rawResponse
        )
        # Push the meeting action onto the channel.
        runtime[].meetingActionChan.send(result.meetingAction)
        # Phase 4: trace the meeting action received.
        block:
          var ev = newJObject()
          ev["t"] = newJInt(snap.tick)
          ev["kind"] = newJString("meeting_action_received")
          if snap.id.len > 0:
            ev["snapshot_id"] = newJString(snap.id)
          ev["action"] = meetingActionToJson(result.meetingAction)
          runtime[].traceEventChan.send($ev)
      else:
        # Push the directive onto the channel. Fill in the tick.
        var directive = result.directive
        directive.issuedAtTick = snap.tick
        runtime[].directiveChan.send(directive)
        # Phase 4: trace the directive published.
        block:
          var ev = newJObject()
          ev["t"] = newJInt(snap.tick)
          ev["kind"] = newJString("directive_published")
          if snap.id.len > 0:
            ev["snapshot_id"] = newJString(snap.id)
          ev["mode"] = newJString($directive.mode)
          ev["params"] = paramsToJson(directive.params)
          ev["ttl_ticks"] = newJInt(directive.ttlTicks)
          runtime[].traceEventChan.send($ev)

    # On error, do nothing — the inner loop continues on the current
    # directive or the default. Per DESIGN.md §9.

# ---------------------------------------------------------------------------
# Public API (called from the main thread)
# ---------------------------------------------------------------------------

proc initGuidanceState*(): GuidanceState =
  GuidanceState(
    running: false,
    callsThisMatch: 0,
    lastCallTick: -1,
    meetingConversationJson: "",
    inMeeting: false,
    runtime: nil
  )

proc startGuidance*(state: var GuidanceState) =
  ## Open channels and spawn the worker thread.
  if state.running:
    return

  let runtime = cast[ptr GuidanceRuntime](allocShared0(sizeof(GuidanceRuntime)))
  runtime[].snapshotChan.open(1)
  runtime[].directiveChan.open()
  runtime[].meetingActionChan.open()
  runtime[].traceEventChan.open()

  createThread(runtime[].workerThread, guidanceWorker, runtime)
  state.runtime = runtime
  state.running = true

proc stopGuidance*(state: var GuidanceState) =
  ## Signal the worker to exit and join the thread.
  if not state.running or state.runtime.isNil:
    state.running = false
    state.runtime = nil
    return

  let runtime = state.runtime

  # Send sentinel snapshot to unblock the worker.
  runtime[].snapshotChan.send(Snapshot(tick: -1, payloadJson: "", isMeeting: false))
  joinThread(runtime[].workerThread)

  runtime[].snapshotChan.close()
  runtime[].directiveChan.close()
  runtime[].meetingActionChan.close()
  runtime[].traceEventChan.close()
  deallocShared(runtime)
  state.runtime = nil
  state.running = false

proc submitSnapshot*(state: var GuidanceState, snap: Snapshot): bool {.discardable.} =
  ## Push a snapshot onto the channel for the worker. If the worker
  ## hasn't consumed the previous snapshot, the old one is replaced
  ## (newest wins — DESIGN.md §10.3).
  if not state.running or state.runtime.isNil:
    return false
  let runtime = state.runtime

  # Rate limiting: enforce minimum interval and per-match cap.
  if snap.tick - state.lastCallTick < LlmMinIntervalTicks and
     state.lastCallTick >= 0:
    return false
  if state.callsThisMatch >= LlmMaxCallsPerMatch:
    return false

  # Drain any pending old snapshot (newest wins).
  while true:
    let (ok, _) = runtime[].snapshotChan.tryRecv()
    if not ok: break

  runtime[].snapshotChan.send(snap)
  state.lastCallTick = snap.tick
  inc state.callsThisMatch

  # Track meeting state for conversation flush.
  state.inMeeting = snap.isMeeting
  result = true

proc drainGuidanceTraceEvents*(state: GuidanceState,
                                traceWriter: TraceWriter) =
  ## Drain all pending trace events from the worker thread channel and
  ## log them via the TraceWriter. Called from the main thread in
  ## bot.nim:decideNextMask. GC-safe: the channel carries pre-serialized
  ## strings, not ref objects.
  if not state.running or state.runtime.isNil:
    return
  let runtime = state.runtime
  if traceWriter == nil:
    # Still drain the channel to prevent unbounded growth.
    while true:
      let (ok, _) = runtime[].traceEventChan.tryRecv()
      if not ok: break
    return
  while true:
    let (ok, payload) = runtime[].traceEventChan.tryRecv()
    if not ok: break
    logGuidanceEvent(traceWriter, payload)

proc tryReceiveDirective*(state: var GuidanceState,
                          directive: var Directive): bool =
  ## Non-blocking drain of `directiveChan`. Keeps the newest
  ## directive if multiple have arrived. Returns true iff a fresh
  ## directive landed.
  if not state.running or state.runtime.isNil:
    return false
  let runtime = state.runtime

  var found = false
  while true:
    let (ok, d) = runtime[].directiveChan.tryRecv()
    if not ok: break
    directive = d
    found = true
  found

proc tryReceiveMeetingAction*(state: var GuidanceState,
                              act: var MeetingAction): bool =
  ## Pop the next `MeetingAction` from the channel (FIFO, one per
  ## call). Returns true if an action was available.
  if not state.running or state.runtime.isNil:
    return false
  let runtime = state.runtime

  let (ok, a) = runtime[].meetingActionChan.tryRecv()
  if ok:
    act = a
    true
  else:
    false

proc flushMeetingConversation*(state: var GuidanceState) =
  ## Reset the meeting conversation history. Called when the phase
  ## transitions away from voting (DESIGN.md §7.3).
  state.meetingConversationJson = ""
  state.inMeeting = false
