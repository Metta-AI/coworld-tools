## LLM client — phase 3.
##
## Adapted from `~/coding/bitworld/src/bitworld/ais/claude.nim` (curly +
## jsony HTTP client). Calls the Anthropic Messages API synchronously
## (intended to run on the guidance worker thread, never on the main
## thread).
##
## The API key is read from env var `ANTHROPIC_API_KEY`, injected by
## cogames via `--secret-env` in the tournament runner.

import std/[os, json, strutils, times]
import curly, jsony
import types
import perception/data
import prompts

const
  AnthropicKeyEnv* = "ANTHROPIC_API_KEY"
  AnthropicUrl = "https://api.anthropic.com/v1/messages"
  AnthropicModel = "claude-sonnet-4-20250514"
  AnthropicVersion = "2023-06-01"
  MaxTokens = 1024
  TimeoutMs = 15_000   ## HTTP timeout in milliseconds.

type
  LlmRequestKind* = enum
    LlmReqGameplay
    LlmReqMeeting

  LlmRequest* = object
    kind*: LlmRequestKind
    snapshotJson*: string     ## Curated belief snapshot (DESIGN.md §8.3).
    conversationJson*: string ## Meeting mode only; empty otherwise.

  LlmResultKind* = enum
    LlmOk
    LlmSchemaError
    LlmHttpError
    LlmTimeout
    LlmRateLimit
    LlmNoKey

  LlmResult* = object
    kind*: LlmResultKind
    directive*: Directive      ## Valid iff `kind == LlmOk` and request was gameplay.
    meetingAction*: MeetingAction ## Valid iff `kind == LlmOk` and request was meeting.
    rawResponse*: string
    latencyMs*: int
    promptTokens*: int
    responseTokens*: int
    detail*: string

# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

proc haveApiKey*(): bool =
  getEnv(AnthropicKeyEnv, "").len > 0

# ---------------------------------------------------------------------------
# Anthropic wire types (for jsony serialization)
# ---------------------------------------------------------------------------

type
  AnthropicMessage = object
    role: string
    content: string

  AnthropicRequest = object
    model: string
    max_tokens: int
    system: string
    messages: seq[AnthropicMessage]

# ---------------------------------------------------------------------------
# HTTP call via curly
# ---------------------------------------------------------------------------

proc httpPost(systemPrompt, userContent: string,
              conversationHistory: seq[AnthropicMessage] = @[]): LlmResult =
  ## Send a request to the Anthropic Messages API. Returns the
  ## assistant's text reply or an error result.
  ##
  ## Creates a fresh CurlPool per call. This is slightly wasteful but
  ## avoids GC-safety issues with global state accessed from the worker
  ## thread. The worker calls this infrequently (fractions of Hz), so
  ## the overhead is negligible.
  let apiKey = getEnv(AnthropicKeyEnv, "")
  if apiKey.len == 0:
    return LlmResult(kind: LlmNoKey, detail: "ANTHROPIC_API_KEY not set")

  var messages: seq[AnthropicMessage]
  # Append conversation history (meeting mode).
  for msg in conversationHistory:
    messages.add msg
  # Append the current user message.
  messages.add AnthropicMessage(role: "user", content: userContent)

  let reqBody = AnthropicRequest(
    model: AnthropicModel,
    max_tokens: MaxTokens,
    system: systemPrompt,
    messages: messages
  )

  let startTime = cpuTime()
  var response: Response
  let pool = newCurlPool(1)
  try:
    response = pool.post(
      AnthropicUrl,
      @[
        ("x-api-key", apiKey),
        ("anthropic-version", AnthropicVersion),
        ("Content-Type", "application/json")
      ],
      reqBody.toJson()
    )
  except CatchableError as e:
    let elapsed = int((cpuTime() - startTime) * 1000)
    return LlmResult(kind: LlmHttpError, latencyMs: elapsed,
                     detail: "HTTP error: " & e.msg)

  let elapsed = int((cpuTime() - startTime) * 1000)

  if response.code == 429:
    return LlmResult(kind: LlmRateLimit, latencyMs: elapsed,
                     detail: "Rate limited (429)")
  if response.code != 200:
    return LlmResult(kind: LlmHttpError, latencyMs: elapsed,
                     rawResponse: response.body,
                     detail: "HTTP " & $response.code)

  # Parse the response body to extract the text content.
  var data: JsonNode
  try:
    data = parseJson(response.body)
  except CatchableError:
    return LlmResult(kind: LlmSchemaError, latencyMs: elapsed,
                     rawResponse: response.body,
                     detail: "Failed to parse response JSON")

  var reply = ""
  if data.hasKey("content"):
    for part in data["content"]:
      if part.hasKey("type") and part["type"].getStr() == "text":
        reply.add part["text"].getStr()

  # Extract token usage if available.
  var promptTok, responseTok: int
  if data.hasKey("usage"):
    let usage = data["usage"]
    if usage.hasKey("input_tokens"):
      promptTok = usage["input_tokens"].getInt()
    if usage.hasKey("output_tokens"):
      responseTok = usage["output_tokens"].getInt()

  LlmResult(kind: LlmOk, rawResponse: reply, latencyMs: elapsed,
            promptTokens: promptTok, responseTokens: responseTok)

# ---------------------------------------------------------------------------
# JSON response parsing → Directive / MeetingAction
# ---------------------------------------------------------------------------

proc parseColorNameToIndex(name: string): int =
  ## Map a colour name back to a colour index. Returns -1 on no match.
  let lower = name.toLowerAscii()
  if lower == "skip": return -1
  for i in 0 ..< PaletteColorTableSize:
    if PlayerColorNames[i].toLowerAscii() == lower:
      return i
  -1

proc parseModeNameStr(name: string): (bool, ModeName) =
  ## Map a mode name string to the enum. Returns (false, _) on no match.
  case name.toLowerAscii()
  of "idle":              (true, ModeIdle)
  of "task_completing":   (true, ModeTaskCompleting)
  of "fear":              (true, ModeFear)
  of "investigating":     (true, ModeInvestigating)
  of "reporting":         (true, ModeReporting)
  of "pretending":        (true, ModePretending)
  of "hunting":           (true, ModeHunting)
  of "fleeing":           (true, ModeFleeing)
  of "alibi_building":    (true, ModeAlibiBuilding)
  of "sabotage_watching": (true, ModeSabotageWatching)
  of "meeting":           (true, ModeMeeting)
  else:                   (false, ModeIdle)

proc parseDirectiveFromJson(raw: string): (bool, Directive) =
  ## Parse an LLM gameplay response into a Directive. Returns
  ## (false, _) if the JSON is malformed or the mode is unrecognised.
  var data: JsonNode
  try:
    data = parseJson(raw)
  except CatchableError:
    return (false, Directive())

  if not data.hasKey("mode"):
    return (false, Directive())

  let modeStr = data["mode"].getStr("")
  let (modeOk, modeName) = parseModeNameStr(modeStr)
  if not modeOk:
    return (false, Directive())

  let ttl = if data.hasKey("ttl_ticks"): data["ttl_ticks"].getInt(360) else: 360
  let reasoning = if data.hasKey("reasoning"): data["reasoning"].getStr("") else: ""

  # Build ModeParams based on mode. Use defaults for missing fields.
  var params: ModeParams
  let pNode = if data.hasKey("params"): data["params"] else: newJObject()

  case modeName
  of ModeTaskCompleting:
    var target = TaskTarget(kind: TgtNearestMandatory)
    if pNode.hasKey("target"):
      let tNode = pNode["target"]
      let tKind = tNode.getOrDefault("kind").getStr("nearest_mandatory")
      case tKind
      of "index":
        target = TaskTarget(kind: TgtIndex,
                           taskIndex: tNode.getOrDefault("task_index").getInt(0))
      of "nearest_any":
        target = TaskTarget(kind: TgtNearestAny)
      of "specific_room":
        target = TaskTarget(kind: TgtSpecificRoom,
                           roomId: tNode.getOrDefault("room_id").getInt(0))
      else:
        target = TaskTarget(kind: TgtNearestMandatory)
    let abandon = if pNode.hasKey("abandon_on_nearby_body"):
                    pNode["abandon_on_nearby_body"].getBool(true)
                  else: true
    params = ModeParams(mode: ModeTaskCompleting,
                       tcTarget: target, tcAbandonOnNearbyBody: abandon)

  of ModeHunting:
    let pref = if pNode.hasKey("preferred_target"):
                 pNode["preferred_target"].getInt(-1) else: -1
    let maxW = if pNode.hasKey("max_witnesses"):
                 pNode["max_witnesses"].getInt(0) else: 0
    let opp = if pNode.hasKey("opportunistic"):
                pNode["opportunistic"].getBool(true) else: true
    let cover = if pNode.hasKey("cover_mode"):
                  let (ok, m) = parseModeNameStr(pNode["cover_mode"].getStr("pretending"))
                  if ok: m else: ModePretending
                else: ModePretending
    params = ModeParams(mode: ModeHunting,
                       hunPreferredTarget: pref, hunMaxWitnesses: maxW,
                       hunOpportunistic: opp, hunCoverMode: cover)

  of ModePretending:
    var target = TaskTarget(kind: TgtNearestMandatory)
    if pNode.hasKey("target"):
      let tNode = pNode["target"]
      let tKind = tNode.getOrDefault("kind").getStr("nearest_mandatory")
      case tKind
      of "index":
        target = TaskTarget(kind: TgtIndex,
                           taskIndex: tNode.getOrDefault("task_index").getInt(0))
      else:
        target = TaskTarget(kind: TgtNearestMandatory)
    let loiter = if pNode.hasKey("loiter_ticks"):
                   pNode["loiter_ticks"].getInt(60) else: 60
    let swap = if pNode.hasKey("may_swap_on_witness"):
                 pNode["may_swap_on_witness"].getBool(true) else: true
    params = ModeParams(mode: ModePretending,
                       preTarget: target, preLoiterTicks: loiter,
                       preMaySwapOnWitness: swap)

  of ModeFleeing:
    var awayX, awayY: int
    if pNode.hasKey("away_from"):
      let af = pNode["away_from"]
      if af.kind == JArray and af.len >= 2:
        awayX = af[0].getInt(0)
        awayY = af[1].getInt(0)
    let minDist = if pNode.hasKey("min_distance"):
                    pNode["min_distance"].getInt(48) else: 48
    let dur = if pNode.hasKey("duration_ticks"):
                pNode["duration_ticks"].getInt(240) else: 240
    params = ModeParams(mode: ModeFleeing,
                       fleeAwayFrom: Point(x: awayX, y: awayY),
                       fleeMinDistance: minDist, fleeDurationTicks: dur)

  of ModeReporting:
    var bx, by: int
    if pNode.hasKey("body_location"):
      let bl = pNode["body_location"]
      if bl.kind == JArray and bl.len >= 2:
        bx = bl[0].getInt(0)
        by = bl[1].getInt(0)
    params = ModeParams(mode: ModeReporting,
                       repBodyLocation: Point(x: bx, y: by))

  of ModeInvestigating:
    var invTarget = InvestigateTarget(kind: InvestColor, colorIndex: -1)
    if pNode.hasKey("target"):
      let tNode = pNode["target"]
      let tKind = tNode.getOrDefault("kind").getStr("color")
      case tKind
      of "color":
        invTarget = InvestigateTarget(kind: InvestColor,
                                     colorIndex: tNode.getOrDefault("color_index").getInt(-1))
      of "location":
        invTarget = InvestigateTarget(kind: InvestLocation,
                                     location: Point(
                                       x: tNode.getOrDefault("x").getInt(0),
                                       y: tNode.getOrDefault("y").getInt(0)))
      of "room":
        invTarget = InvestigateTarget(kind: InvestRoom,
                                     roomId: tNode.getOrDefault("room_id").getInt(0))
      else: discard
    let timeout = if pNode.hasKey("timeout_ticks"):
                    pNode["timeout_ticks"].getInt(240) else: 240
    params = ModeParams(mode: ModeInvestigating,
                       invTarget: invTarget, invTimeoutTicks: timeout)

  of ModeFear:
    let minVis = if pNode.hasKey("min_visible_others"):
                   pNode["min_visible_others"].getInt(2) else: 2
    let prefRoom = if pNode.hasKey("prefer_room"):
                     pNode["prefer_room"].getInt(-1) else: -1
    let maxDist = if pNode.hasKey("max_distance_from_group"):
                    pNode["max_distance_from_group"].getInt(64) else: 64
    params = ModeParams(mode: ModeFear,
                       fearMinVisibleOthers: minVis,
                       fearPreferRoomId: prefRoom,
                       fearMaxDistance: maxDist)

  of ModeAlibiBuilding:
    let companion = if pNode.hasKey("companion_color"):
                      pNode["companion_color"].getInt(-1) else: -1
    let roomId = if pNode.hasKey("room_id"):
                   pNode["room_id"].getInt(-1) else: -1
    let minDur = if pNode.hasKey("min_duration_ticks"):
                   pNode["min_duration_ticks"].getInt(120) else: 120
    params = ModeParams(mode: ModeAlibiBuilding,
                       aliCompanionColor: companion,
                       aliRoomId: roomId,
                       aliMinDurationTicks: minDur)

  of ModeIdle:
    params = ModeParams(mode: ModeIdle,
                       idleLingerValid: false, idleNearGroup: false)

  of ModeMeeting:
    params = ModeParams(mode: ModeMeeting, meetWantToSpeakFirst: false)

  of ModeSabotageWatching:
    params = ModeParams(mode: ModeSabotageWatching, sabStationId: 0)

  let directive = Directive(
    mode: modeName,
    params: params,
    source: SourceLlm,
    issuedAtTick: 0,  # Caller fills in the tick.
    ttlTicks: ttl,
    reflexName: "",
    reasoning: reasoning
  )
  (true, directive)

proc parseMeetingActionFromJson(raw: string): (bool, MeetingAction) =
  ## Parse an LLM meeting response into a MeetingAction. Returns
  ## (false, _) if the JSON is malformed or the action is unrecognised.
  var data: JsonNode
  try:
    data = parseJson(raw)
  except CatchableError:
    return (false, MeetingAction())

  if not data.hasKey("action"):
    return (false, MeetingAction())

  let actionStr = data["action"].getStr("")
  case actionStr.toLowerAscii()
  of "speak":
    let text = data.getOrDefault("text").getStr("")
    if text.len == 0:
      return (false, MeetingAction())
    # Truncate chat to safe length.
    let truncated = if text.len > 80: text[0 ..< 80] else: text
    (true, MeetingAction(kind: MeetingActSpeak, text: truncated))
  of "vote":
    let targetStr = data.getOrDefault("target").getStr("skip")
    let targetIdx = parseColorNameToIndex(targetStr)
    (true, MeetingAction(kind: MeetingActVote, target: targetIdx))
  of "confirm_vote":
    (true, MeetingAction(kind: MeetingActConfirmVote))
  of "unvote":
    (true, MeetingAction(kind: MeetingActUnvote))
  of "wait":
    (true, MeetingAction(kind: MeetingActWait))
  else:
    (false, MeetingAction())

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

proc callLlm*(req: LlmRequest): LlmResult =
  ## Call the Anthropic Messages API. Synchronous — designed to run on
  ## the guidance worker thread.
  ##
  ## For gameplay requests: sends the snapshot as the user message with
  ## the gameplay system prompt. Parses the response into a Directive.
  ##
  ## For meeting requests: sends the snapshot + conversation history
  ## with the meeting system prompt. Parses into a MeetingAction.
  if not haveApiKey():
    return LlmResult(kind: LlmNoKey,
                     detail: "ANTHROPIC_API_KEY not set")

  let systemPrompt = case req.kind
    of LlmReqGameplay: GameplaySystemPrompt
    of LlmReqMeeting:  MeetingSystemPrompt

  # Build conversation history for meeting mode.
  var history: seq[AnthropicMessage]
  if req.kind == LlmReqMeeting and req.conversationJson.len > 0:
    # The conversation JSON is a JSON array of {role, content} objects.
    try:
      let convArr = parseJson(req.conversationJson)
      if convArr.kind == JArray:
        for item in convArr:
          history.add AnthropicMessage(
            role: item["role"].getStr("user"),
            content: item["content"].getStr("")
          )
    except CatchableError:
      discard  # Proceed without history on parse failure.

  let userContent = case req.kind
    of LlmReqGameplay:
      "Current game state:\n" & req.snapshotJson &
        "\n\nProduce your directive as a JSON object."
    of LlmReqMeeting:
      "Current meeting state:\n" & req.snapshotJson &
        "\n\nProduce your next meeting action as a JSON object."

  var httpResult = httpPost(systemPrompt, userContent, history)

  if httpResult.kind != LlmOk:
    return httpResult

  # Parse the text reply into the appropriate structured output.
  let raw = httpResult.rawResponse

  # Try to extract JSON from the response (the LLM might wrap it in
  # backticks or add preamble). Find the first { and last }.
  var jsonStr = raw
  let firstBrace = raw.find('{')
  let lastBrace = raw.rfind('}')
  if firstBrace >= 0 and lastBrace > firstBrace:
    jsonStr = raw[firstBrace .. lastBrace]

  case req.kind
  of LlmReqGameplay:
    let (ok, directive) = parseDirectiveFromJson(jsonStr)
    if ok:
      result = httpResult
      result.directive = directive
    else:
      result = LlmResult(kind: LlmSchemaError,
                         rawResponse: raw,
                         latencyMs: httpResult.latencyMs,
                         promptTokens: httpResult.promptTokens,
                         responseTokens: httpResult.responseTokens,
                         detail: "Failed to parse directive from LLM response")

  of LlmReqMeeting:
    let (ok, action) = parseMeetingActionFromJson(jsonStr)
    if ok:
      result = httpResult
      result.meetingAction = action
    else:
      result = LlmResult(kind: LlmSchemaError,
                         rawResponse: raw,
                         latencyMs: httpResult.latencyMs,
                         promptTokens: httpResult.promptTokens,
                         responseTokens: httpResult.responseTokens,
                         detail: "Failed to parse meeting action from LLM response")
