## Structured trace writer — phase 4.
##
## Emits structured JSONL trace output per DESIGN.md section 11, enabling
## post-match replay and offline analysis. Trace output is a session
## directory containing JSONL streams plus a manifest:
##
##   - manifest.json    (round metadata, tuning snapshot, schema version)
##   - events.jsonl     (body_seen, chat_observed, meeting_started, ...)
##   - decisions.jsonl   (per-frame mode / branch / intent)
##   - modes.jsonl      (mode_entered / mode_exited)
##   - guidance.jsonl   (snapshot_sent / llm_response / directive_published)
##   - reflexes.jsonl   (reflex_fired / reflex_suppressed)
##   - snapshots.jsonl  (periodic full-belief snapshots)
##   - frames.bin       (optional, gated by TraceFull)
##
## Tracing is opt-in via GUIDED_BOT_TRACE_DIR / GUIDED_BOT_TRACE_LEVEL
## env vars. When off, every log* call is near-zero-cost (check
## trace == nil early return).
##
## GC-safety: the guidance worker thread cannot access ref/seq/string
## objects on the main thread. Worker-thread trace events are pushed
## onto a Channel[string] and drained by the main thread in
## decideNextMask. See guidance.nim for the channel setup.
##
## See DESIGN.md section 11 for the full schema.

import std/[json, os, streams, times]
import types
import snapshot as snapshotMod

const
  TraceSchemaVersion* = 1
  ## Periodic snapshot interval (in ticks). Snapshots are also
  ## emitted on major events via wake reasons.
  SnapshotIntervalTicks = 240  ## ~10s at 24Hz.

type
  TraceLevel* = enum
    TraceOff
    TraceEvents       ## events.jsonl only
    TraceDecisions    ## events + decisions + modes + reflexes + guidance
    TraceFull         ## all of the above + snapshots + frames.bin

  TraceWriter* = ref object
    level*: TraceLevel
    rootDir*: string
    ## File streams for each JSONL output.
    eventsFile: FileStream
    decisionsFile: FileStream
    modesFile: FileStream
    guidanceFile: FileStream
    reflexesFile: FileStream
    snapshotsFile: FileStream
    framesFile: FileStream      ## Binary append; nil unless TraceFull.
    ## Manifest state — written on open, updated on close.
    startTick: int
    endTick: int
    outcome: string             ## "crew_wins" / "imps_win" / "" (unknown).
    role: string
    ## Mode entry tracking for duration calculation.
    modeEntryTick*: int
    ## Snapshot cadence tracking.
    lastSnapshotTick: int

# ---------------------------------------------------------------------------
# Helpers — JSON serialization for trace payloads
# ---------------------------------------------------------------------------

proc modeStr(mode: ModeName): string =
  case mode
  of ModeIdle:             "idle"
  of ModeTaskCompleting:   "task_completing"
  of ModeFear:             "fear"
  of ModeInvestigating:    "investigating"
  of ModeReporting:        "reporting"
  of ModePretending:       "pretending"
  of ModeHunting:          "hunting"
  of ModeFleeing:          "fleeing"
  of ModeAlibiBuilding:    "alibi_building"
  of ModeSabotageWatching: "sabotage_watching"
  of ModeMeeting:          "meeting"

proc sourceStr(source: DirectiveSource): string =
  case source
  of SourceDefault: "default"
  of SourceLlm:     "llm"
  of SourceReflex:  "reflex"

proc paramsToJson(params: ModeParams): JsonNode =
  ## Serialize mode params to a JSON object. Only includes non-default
  ## fields relevant to the active mode.
  result = newJObject()
  case params.mode
  of ModeIdle:
    if params.idleLingerValid:
      result["linger_at"] = %*[params.idleLingerAt.x, params.idleLingerAt.y]
    result["near_group"] = newJBool(params.idleNearGroup)
  of ModeTaskCompleting:
    var tgt = newJObject()
    case params.tcTarget.kind
    of TgtIndex:
      tgt["kind"] = newJString("index")
      tgt["task_index"] = newJInt(params.tcTarget.taskIndex)
    of TgtNearestMandatory:
      tgt["kind"] = newJString("nearest_mandatory")
    of TgtNearestAny:
      tgt["kind"] = newJString("nearest_any")
    of TgtSpecificRoom:
      tgt["kind"] = newJString("specific_room")
      tgt["room_id"] = newJInt(params.tcTarget.roomId)
    result["target"] = tgt
    result["abandon_on_nearby_body"] = newJBool(params.tcAbandonOnNearbyBody)
  of ModeFear:
    result["min_visible_others"] = newJInt(params.fearMinVisibleOthers)
    result["prefer_room_id"] = newJInt(params.fearPreferRoomId)
    result["max_distance"] = newJInt(params.fearMaxDistance)
  of ModeInvestigating:
    var tgt = newJObject()
    case params.invTarget.kind
    of InvestColor:
      tgt["kind"] = newJString("color")
      tgt["color_index"] = newJInt(params.invTarget.colorIndex)
    of InvestLocation:
      tgt["kind"] = newJString("location")
      tgt["x"] = newJInt(params.invTarget.location.x)
      tgt["y"] = newJInt(params.invTarget.location.y)
    of InvestRoom:
      tgt["kind"] = newJString("room")
      tgt["room_id"] = newJInt(params.invTarget.roomId)
    result["target"] = tgt
    result["timeout_ticks"] = newJInt(params.invTimeoutTicks)
  of ModeReporting:
    result["body_location"] = %*[params.repBodyLocation.x,
                                  params.repBodyLocation.y]
  of ModePretending:
    var tgt = newJObject()
    case params.preTarget.kind
    of TgtIndex:
      tgt["kind"] = newJString("index")
      tgt["task_index"] = newJInt(params.preTarget.taskIndex)
    of TgtNearestMandatory:
      tgt["kind"] = newJString("nearest_mandatory")
    of TgtNearestAny:
      tgt["kind"] = newJString("nearest_any")
    of TgtSpecificRoom:
      tgt["kind"] = newJString("specific_room")
      tgt["room_id"] = newJInt(params.preTarget.roomId)
    result["target"] = tgt
    result["loiter_ticks"] = newJInt(params.preLoiterTicks)
    result["may_swap_on_witness"] = newJBool(params.preMaySwapOnWitness)
  of ModeHunting:
    result["preferred_target"] = newJInt(params.huntPreferredTarget)
    result["max_witnesses"] = newJInt(params.huntMaxWitnesses)
    result["opportunistic"] = newJBool(params.huntOpportunistic)
    result["cover_mode"] = newJString(modeStr(params.huntCoverMode))
  of ModeFleeing:
    result["away_from"] = %*[params.fleeAwayFrom.x, params.fleeAwayFrom.y]
    result["min_distance"] = newJInt(params.fleeMinDistance)
    result["duration_ticks"] = newJInt(params.fleeDurationTicks)
  of ModeAlibiBuilding:
    result["companion_color"] = newJInt(params.aliCompanionColor)
    result["room_id"] = newJInt(params.aliRoomId)
    result["min_duration_ticks"] = newJInt(params.aliMinDurationTicks)
  of ModeSabotageWatching:
    result["station_id"] = newJInt(params.sabStationId)
  of ModeMeeting:
    result["want_to_speak_first"] = newJBool(params.meetWantToSpeakFirst)

proc intentToJson(intent: ActionIntent): JsonNode =
  result = newJObject()
  if intent.steerValid:
    result["steer_to"] = %*[intent.steerTo.x, intent.steerTo.y]
  else:
    result["steer_to"] = newJNull()
  result["press_a"] = newJBool(intent.pressA)
  result["press_b"] = newJBool(intent.pressB)
  case intent.cursor
  of CursorNone:  result["cursor"] = newJString("none")
  of CursorLeft:  result["cursor"] = newJString("left")
  of CursorRight: result["cursor"] = newJString("right")
  if intent.chat.len > 0:
    result["chat"] = newJString(intent.chat)
  result["discipline"] = newJString($intent.discipline)

proc writeLine(fs: FileStream, line: string) =
  ## Write a line + newline to a file stream. No-op if stream is nil.
  if fs != nil:
    fs.write(line)
    fs.write("\n")

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

proc writeManifest(trace: TraceWriter, final: bool = false) =
  ## Write (or overwrite) the manifest.json file.
  var m = newJObject()
  m["trace_schema_version"] = newJInt(TraceSchemaVersion)
  m["bot"] = newJString("guided_bot")
  m["level"] = newJString($trace.level)
  m["start_tick"] = newJInt(trace.startTick)
  m["created_at"] = newJString(now().format("yyyy-MM-dd'T'HH:mm:sszzz"))
  if trace.role.len > 0:
    m["role"] = newJString(trace.role)
  if final:
    m["end_tick"] = newJInt(trace.endTick)
    if trace.outcome.len > 0:
      m["outcome"] = newJString(trace.outcome)
    m["closed"] = newJBool(true)
  else:
    m["closed"] = newJBool(false)
  let path = trace.rootDir / "manifest.json"
  writeFile(path, m.pretty())

# ---------------------------------------------------------------------------
# Public API — lifecycle
# ---------------------------------------------------------------------------

proc openTrace*(rootDir: string, level: TraceLevel): TraceWriter =
  ## Create the trace directory and open file handles for each JSONL
  ## stream. Returns nil if tracing is off or rootDir is empty.
  if level == TraceOff or rootDir.len == 0:
    return nil

  createDir(rootDir)

  result = TraceWriter(
    level: level,
    rootDir: rootDir,
    startTick: 0,
    endTick: 0,
    outcome: "",
    role: "",
    modeEntryTick: 0,
    lastSnapshotTick: -1000
  )

  # Open JSONL streams based on trace level.
  # TraceEvents: events only.
  result.eventsFile = newFileStream(rootDir / "events.jsonl", fmWrite)

  if level >= TraceDecisions:
    result.decisionsFile = newFileStream(rootDir / "decisions.jsonl", fmWrite)
    result.modesFile = newFileStream(rootDir / "modes.jsonl", fmWrite)
    result.reflexesFile = newFileStream(rootDir / "reflexes.jsonl", fmWrite)
    result.guidanceFile = newFileStream(rootDir / "guidance.jsonl", fmWrite)

  if level >= TraceFull:
    result.snapshotsFile = newFileStream(rootDir / "snapshots.jsonl", fmWrite)
    result.framesFile = newFileStream(rootDir / "frames.bin", fmWrite)

  # Write the initial manifest.
  writeManifest(result, final = false)

proc closeTrace*(trace: TraceWriter) =
  ## Flush and close all trace file handles. Update the manifest with
  ## end-tick and outcome.
  if trace == nil:
    return

  # Update manifest with final state.
  writeManifest(trace, final = true)

  # Close all streams.
  if trace.eventsFile != nil:
    trace.eventsFile.close()
    trace.eventsFile = nil
  if trace.decisionsFile != nil:
    trace.decisionsFile.close()
    trace.decisionsFile = nil
  if trace.modesFile != nil:
    trace.modesFile.close()
    trace.modesFile = nil
  if trace.guidanceFile != nil:
    trace.guidanceFile.close()
    trace.guidanceFile = nil
  if trace.reflexesFile != nil:
    trace.reflexesFile.close()
    trace.reflexesFile = nil
  if trace.snapshotsFile != nil:
    trace.snapshotsFile.close()
    trace.snapshotsFile = nil
  if trace.framesFile != nil:
    trace.framesFile.close()
    trace.framesFile = nil

# ---------------------------------------------------------------------------
# Public API — per-event writers
# ---------------------------------------------------------------------------

proc logDecision*(trace: TraceWriter, belief: Belief,
                  intent: ActionIntent, branchId: string,
                  mask: uint8 = 0) =
  ## Log one decision record to decisions.jsonl (DESIGN.md section 11.3).
  ## Called once per frame from bot.nim:decideNextMask after applyIntent()
  ## so the final button mask is available.
  if trace == nil or trace.level < TraceDecisions:
    return

  # Track end tick for the manifest.
  trace.endTick = belief.tick

  var rec = newJObject()
  rec["t"] = newJInt(belief.tick)
  rec["mode"] = newJString(modeStr(belief.directive.mode))
  rec["directive_source"] = newJString(sourceStr(belief.directive.source))
  rec["directive_issued_at"] = newJInt(belief.directive.issuedAtTick)
  rec["params"] = paramsToJson(belief.directive.params)
  rec["branch_id"] = newJString(branchId)
  rec["intent"] = intentToJson(intent)
  rec["mask"] = newJInt(int(mask))
  # Self position for correlating with camera localization.
  rec["self_x"] = newJInt(belief.percep.selfX)
  rec["self_y"] = newJInt(belief.percep.selfY)
  rec["localized"] = newJBool(belief.percep.localized)
  if belief.directive.reasoning.len > 0:
    rec["reason"] = newJString(belief.directive.reasoning)
  trace.decisionsFile.writeLine($rec)

proc logModeEntered*(trace: TraceWriter, tick: int, fromMode, toMode: ModeName,
                    params: ModeParams, reason: string) =
  ## Log a mode_entered event to modes.jsonl (DESIGN.md section 11.5).
  ## Called from bot.nim:switchMode after onEnter completes.
  if trace == nil or trace.level < TraceDecisions:
    return

  trace.modeEntryTick = tick

  var rec = newJObject()
  rec["t"] = newJInt(tick)
  rec["kind"] = newJString("mode_entered")
  rec["mode"] = newJString(modeStr(toMode))
  rec["params"] = paramsToJson(params)
  rec["from_mode"] = newJString(modeStr(fromMode))
  rec["reason"] = newJString(reason)
  trace.modesFile.writeLine($rec)

proc logModeExited*(trace: TraceWriter, tick: int, mode: ModeName,
                   durationTicks: int) =
  ## Log a mode_exited event to modes.jsonl (DESIGN.md section 11.5).
  ## Called from bot.nim:switchMode before onExit runs.
  if trace == nil or trace.level < TraceDecisions:
    return

  var rec = newJObject()
  rec["t"] = newJInt(tick)
  rec["kind"] = newJString("mode_exited")
  rec["mode"] = newJString(modeStr(mode))
  rec["duration_ticks"] = newJInt(durationTicks)
  trace.modesFile.writeLine($rec)

proc logReflexFired*(trace: TraceWriter, tick: int, name: string,
                    fromMode, toMode: ModeName, toParams: ModeParams) =
  ## Log a reflex_fired event to reflexes.jsonl (DESIGN.md section 11.6).
  ## Called from bot.nim:reconcileDirective when a reflex fires.
  if trace == nil or trace.level < TraceDecisions:
    return

  var rec = newJObject()
  rec["t"] = newJInt(tick)
  rec["kind"] = newJString("reflex_fired")
  rec["name"] = newJString(name)
  rec["from_mode"] = newJString(modeStr(fromMode))
  rec["to_mode"] = newJString(modeStr(toMode))
  rec["to_params"] = paramsToJson(toParams)
  trace.reflexesFile.writeLine($rec)

proc logGuidanceEvent*(trace: TraceWriter, payload: string) =
  ## Log a guidance event to guidance.jsonl (DESIGN.md section 11.4).
  ## The payload is a pre-serialized JSON string pushed from the
  ## guidance worker thread via a channel, then drained on the main
  ## thread and forwarded here.
  if trace == nil or trace.level < TraceDecisions:
    return
  # The payload is already a complete JSON line.
  trace.guidanceFile.writeLine(payload)

proc logGameEvent*(trace: TraceWriter, kind: string, tick: int,
                  payload: string) =
  ## Log a game event to events.jsonl (DESIGN.md section 11.2).
  ## Called from bot.nim after belief merge procs detect game events.
  if trace == nil:
    return

  # Update end tick and role if we learn it.
  trace.endTick = tick

  var rec = newJObject()
  rec["t"] = newJInt(tick)
  rec["kind"] = newJString(kind)
  # Merge any additional payload fields.
  if payload.len > 0:
    try:
      let extra = parseJson(payload)
      if extra.kind == JObject:
        for key, val in extra:
          rec[key] = val
    except CatchableError:
      rec["detail"] = newJString(payload)
  trace.eventsFile.writeLine($rec)

proc logSnapshot*(trace: TraceWriter, tick: int, belief: Belief) =
  ## Log a periodic full-belief snapshot to snapshots.jsonl.
  ## Called from bot.nim:decideNextMask at SnapshotIntervalTicks cadence.
  if trace == nil or trace.level < TraceFull:
    return
  if tick - trace.lastSnapshotTick < SnapshotIntervalTicks:
    return
  trace.lastSnapshotTick = tick

  let snapJson = snapshotMod.renderSnapshot(belief)
  var rec = newJObject()
  rec["t"] = newJInt(tick)
  try:
    rec["snapshot"] = parseJson(snapJson)
  except CatchableError:
    rec["snapshot_raw"] = newJString(snapJson)
  trace.snapshotsFile.writeLine($rec)

proc logFrame*(trace: TraceWriter, frame: openArray[uint8]) =
  ## Append a raw frame to frames.bin. Only active at TraceFull.
  if trace == nil or trace.level < TraceFull:
    return
  if trace.framesFile == nil:
    return
  # Write raw bytes — each frame is FrameLen bytes.
  for b in frame:
    trace.framesFile.write(b)

proc setRole*(trace: TraceWriter, role: string) =
  ## Update the role in the trace manifest. Called when the bot
  ## discovers its role.
  if trace == nil:
    return
  trace.role = role

proc setOutcome*(trace: TraceWriter, outcome: string) =
  ## Update the outcome in the trace manifest. Called on game_over.
  if trace == nil:
    return
  trace.outcome = outcome
