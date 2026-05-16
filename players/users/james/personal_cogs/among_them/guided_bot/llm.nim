## LLM client — phase 3.
##
## Adapted from `~/coding/bitworld/src/bitworld/ais/claude.nim` (curly +
## jsony HTTP client). Calls Claude synchronously through either AWS
## Bedrock or the direct Anthropic Messages API (intended to run on the
## guidance worker thread, never on the main thread).
##
## Provider selection follows the local Softmax convention:
## `CLAUDE_CODE_USE_BEDROCK=1` / `USE_BEDROCK=true` prefers Bedrock
## credentials; `ANTHROPIC_API_KEY` is only the direct-API fallback.

import std/[os, osproc, json, strutils, times]
import curly, jsony
import crunchy/common
import crunchy/sha256
import types
import perception/data
import prompts
import tuning

const
  AnthropicKeyEnv* = "ANTHROPIC_API_KEY"
  GuidedBotLlmDisableEnv* = "GUIDED_BOT_LLM_DISABLE"
  GuidedBotLlmGameplayDirectivesEnv* = "GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES"
  GuidedBotLlmProviderEnv* = "GUIDED_BOT_LLM_PROVIDER"
  GuidedBotLlmModelEnv* = "GUIDED_BOT_LLM_MODEL"
  GuidedBotBedrockModelEnv* = "GUIDED_BOT_BEDROCK_MODEL"
  GuidedBotAnthropicModelEnv* = "GUIDED_BOT_ANTHROPIC_MODEL"
  CogamesLlmProviderEnv* = "COGAMES_LLM_PROVIDER"
  CogamesLlmModelEnv* = "COGAMES_LLM_MODEL"
  ClaudeCodeBedrockEnv* = "CLAUDE_CODE_USE_BEDROCK"
  CogamesBedrockEnv* = "USE_BEDROCK"
  AnthropicUrl = "https://api.anthropic.com/v1/messages"
  DefaultAnthropicModel = "claude-sonnet-4-20250514"
  DefaultBedrockModel = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
  AnthropicVersion = "2023-06-01"
  BedrockAnthropicVersion = "bedrock-2023-05-31"
  BedrockService = "bedrock"
  AwsCredsEndpoint = "http://169.254.170.2"
  MaxTokens = 1024
  TimeoutMs = 15_000   ## HTTP timeout in milliseconds.

type
  LlmProvider = enum
    ProviderNone
    ProviderAnthropic
    ProviderBedrock

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

  AwsCredentials = object
    accessKeyId: string
    secretAccessKey: string
    sessionToken: string

# ---------------------------------------------------------------------------
# Provider selection / credentials
# ---------------------------------------------------------------------------

proc envFlag(name: string): bool =
  let value = getEnv(name, "").strip().toLowerAscii()
  value in ["1", "true", "yes", "on"]

proc llmDisabled(): bool =
  envFlag(GuidedBotLlmDisableEnv)

proc gameplayLlmDirectivesEnabled*(): bool =
  ## Controls whether non-meeting snapshots may produce LLM gameplay
  ## directives. Defaults to enabled to preserve local full-LLM behavior;
  ## set GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0/false/off to keep gameplay
  ## mode control symbolic while allowing meeting LLM actions.
  let value = getEnv(GuidedBotLlmGameplayDirectivesEnv, "").strip().toLowerAscii()
  if value.len == 0:
    return true
  value notin ["0", "false", "no", "off", "disabled"]

proc configuredProvider(): string =
  result = getEnv(GuidedBotLlmProviderEnv, "").strip().toLowerAscii()
  if result.len == 0:
    result = getEnv(CogamesLlmProviderEnv, "").strip().toLowerAscii()

proc bedrockRequested(): bool =
  let provider = configuredProvider()
  provider == "bedrock" or provider == "bedrock-claude" or
    envFlag(ClaudeCodeBedrockEnv) or
    envFlag(CogamesBedrockEnv)

proc haveStaticAwsEnv(): bool =
  getEnv("AWS_ACCESS_KEY_ID", "").len > 0 and
    getEnv("AWS_SECRET_ACCESS_KEY", "").len > 0

proc haveAwsCredentialHint(): bool =
  haveStaticAwsEnv() or
    getEnv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "").len > 0 or
    getEnv("AWS_CONTAINER_CREDENTIALS_FULL_URI", "").len > 0 or
    getEnv("AWS_PROFILE", "").len > 0 or
    bedrockRequested()

proc selectedProvider(): LlmProvider =
  if llmDisabled():
    return ProviderNone
  let provider = configuredProvider()
  case provider
  of "anthropic", "direct":
    if getEnv(AnthropicKeyEnv, "").len > 0:
      return ProviderAnthropic
    return ProviderNone
  of "bedrock", "bedrock-claude":
    if haveAwsCredentialHint():
      return ProviderBedrock
    return ProviderNone
  of "", "auto":
    if bedrockRequested() or getEnv(AnthropicKeyEnv, "").len == 0:
      if haveAwsCredentialHint():
        return ProviderBedrock
    if getEnv(AnthropicKeyEnv, "").len > 0:
      return ProviderAnthropic
    if haveAwsCredentialHint():
      return ProviderBedrock
    return ProviderNone
  else:
    return ProviderNone

proc haveLlmProvider*(): bool =
  selectedProvider() != ProviderNone

proc haveApiKey*(): bool =
  ## Backwards-compatible name retained for older call sites/tests.
  haveLlmProvider()

proc currentProviderName*(): string =
  case selectedProvider()
  of ProviderAnthropic: "anthropic"
  of ProviderBedrock: "bedrock"
  of ProviderNone: "none"

proc directAnthropicModel(): string =
  let guided = getEnv(GuidedBotLlmModelEnv, "").strip()
  if guided.len > 0:
    return guided
  let direct = getEnv(GuidedBotAnthropicModelEnv, "").strip()
  if direct.len > 0:
    return direct
  let platformModel = getEnv(CogamesLlmModelEnv, "").strip()
  if platformModel.len > 0:
    return platformModel
  DefaultAnthropicModel

proc bedrockModel(): string =
  for name in [GuidedBotLlmModelEnv, GuidedBotBedrockModelEnv,
               CogamesLlmModelEnv,
               "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_MODEL"]:
    let value = getEnv(name, "").strip()
    if value.len > 0:
      return value
  DefaultBedrockModel

proc awsRegion(): string =
  for name in ["AWS_REGION", "AWS_DEFAULT_REGION"]:
    let value = getEnv(name, "").strip()
    if value.len > 0:
      return value
  "us-east-1"

# ---------------------------------------------------------------------------
# Claude / AWS wire types (for jsony serialization)
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

  BedrockRequest = object
    anthropic_version: string
    max_tokens: int
    temperature: float
    system: string
    messages: seq[AnthropicMessage]

proc parseClaudeTextResponse(body: string, latencyMs: int): LlmResult =
  ## Parse the common Claude Messages response shape returned by both
  ## direct Anthropic and Bedrock InvokeModel.
  var data: JsonNode
  try:
    data = parseJson(body)
  except CatchableError:
    return LlmResult(kind: LlmSchemaError, latencyMs: latencyMs,
                     rawResponse: body,
                     detail: "Failed to parse response JSON")

  var reply = ""
  if data.hasKey("content"):
    for part in data["content"]:
      if part.hasKey("type") and part["type"].getStr() == "text":
        reply.add part["text"].getStr()

  var promptTok, responseTok: int
  if data.hasKey("usage"):
    let usage = data["usage"]
    if usage.hasKey("input_tokens"):
      promptTok = usage["input_tokens"].getInt()
    elif usage.hasKey("inputTokens"):
      promptTok = usage["inputTokens"].getInt()
    if usage.hasKey("output_tokens"):
      responseTok = usage["output_tokens"].getInt()
    elif usage.hasKey("outputTokens"):
      responseTok = usage["outputTokens"].getInt()

  LlmResult(kind: LlmOk, rawResponse: reply, latencyMs: latencyMs,
            promptTokens: promptTok, responseTokens: responseTok)

proc stripQuotes(value: string): string =
  result = value.strip()
  if result.len >= 2 and
     ((result[0] == '"' and result[^1] == '"') or
      (result[0] == '\'' and result[^1] == '\'')):
    result = result[1 .. ^2]

proc parseAwsCredentialLines(output: string): AwsCredentials =
  for rawLine in output.splitLines():
    let line = rawLine.strip()
    if line.len == 0 or line.startsWith("#"):
      continue
    let eq = line.find('=')
    if eq <= 0:
      continue
    let key = line[0 ..< eq].strip()
    let value = stripQuotes(line[eq + 1 .. ^1])
    case key
    of "AWS_ACCESS_KEY_ID": result.accessKeyId = value
    of "AWS_SECRET_ACCESS_KEY": result.secretAccessKey = value
    of "AWS_SESSION_TOKEN": result.sessionToken = value
    else: discard

proc fetchContainerCredentials(): (bool, AwsCredentials, string) =
  ## Resolve ECS task-role credentials when Coworld grants Bedrock via
  ## `--use-bedrock`. The endpoint and token are local metadata; no
  ## user secrets are logged.
  let rel = getEnv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "").strip()
  let full = getEnv("AWS_CONTAINER_CREDENTIALS_FULL_URI", "").strip()
  if rel.len == 0 and full.len == 0:
    return (false, AwsCredentials(), "container credentials env not set")

  let url = if full.len > 0: full else: AwsCredsEndpoint & rel
  var headers: seq[(string, string)] = @[]
  let token = getEnv("AWS_CONTAINER_AUTHORIZATION_TOKEN", "")
  let tokenFile = getEnv("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE", "")
  if token.len > 0:
    headers.add ("Authorization", token)
  elif tokenFile.len > 0 and fileExists(tokenFile):
    try:
      headers.add ("Authorization", readFile(tokenFile).strip())
    except CatchableError:
      discard

  let pool = newCurlPool(1)
  defer: pool.close()
  var response: Response
  try:
    response = pool.get(url, headers, 2.0'f32)
  except CatchableError as e:
    return (false, AwsCredentials(), "container credentials fetch failed: " & e.msg)

  if response.code != 200:
    return (false, AwsCredentials(),
            "container credentials HTTP " & $response.code)

  try:
    let data = parseJson(response.body)
    let creds = AwsCredentials(
      accessKeyId: data.getOrDefault("AccessKeyId").getStr(""),
      secretAccessKey: data.getOrDefault("SecretAccessKey").getStr(""),
      sessionToken: data.getOrDefault("Token").getStr("")
    )
    if creds.accessKeyId.len > 0 and creds.secretAccessKey.len > 0:
      return (true, creds, "")
    (false, AwsCredentials(), "container credentials missing access key fields")
  except CatchableError:
    (false, AwsCredentials(), "container credentials JSON parse failed")

proc exportAwsCliCredentials(): (bool, AwsCredentials, string) =
  ## Local development path for AWS SSO profiles. `aws configure
  ## export-credentials` resolves the standard CLI chain without
  ## exposing credential values to logs.
  if findExe("aws").len == 0:
    return (false, AwsCredentials(), "aws CLI not found")
  let (output, exitCode) = execCmdEx(
    "aws configure export-credentials --format env-no-export"
  )
  if exitCode != 0:
    return (false, AwsCredentials(), "aws credential export failed")
  let creds = parseAwsCredentialLines(output)
  if creds.accessKeyId.len > 0 and creds.secretAccessKey.len > 0:
    return (true, creds, "")
  (false, AwsCredentials(), "aws credential export missing access key fields")

proc resolveAwsCredentials(): (bool, AwsCredentials, string) =
  let envCreds = AwsCredentials(
    accessKeyId: getEnv("AWS_ACCESS_KEY_ID", ""),
    secretAccessKey: getEnv("AWS_SECRET_ACCESS_KEY", ""),
    sessionToken: getEnv("AWS_SESSION_TOKEN", "")
  )
  if envCreds.accessKeyId.len > 0 and envCreds.secretAccessKey.len > 0:
    return (true, envCreds, "")

  let (metadataOk, metadataCreds, metadataDetail) = fetchContainerCredentials()
  if metadataOk:
    return (true, metadataCreds, "")

  let (cliOk, cliCreds, cliDetail) = exportAwsCliCredentials()
  if cliOk:
    return (true, cliCreds, "")

  (false, AwsCredentials(),
   metadataDetail & "; " & cliDetail)

# ---------------------------------------------------------------------------
# HTTP calls via curly
# ---------------------------------------------------------------------------

proc awsUriEncode(value: string): string =
  ## AWS SigV4 URI encoding for a single path segment.
  const hex = "0123456789ABCDEF"
  for ch in value:
    if ch in {'A'..'Z'} or ch in {'a'..'z'} or ch in {'0'..'9'} or
       ch in {'-', '_', '.', '~'}:
      result.add ch
    else:
      let b = ord(ch)
      result.add '%'
      result.add hex[(b shr 4) and 0xF]
      result.add hex[b and 0xF]

proc sha256Hex(value: string): string =
  sha256(value).toHex()

proc sigv4SigningKey(secretKey, dateStamp, region, service: string): array[32, uint8] =
  let kDate = hmacSha256("AWS4" & secretKey, dateStamp)
  let kRegion = hmacSha256(kDate, region)
  let kService = hmacSha256(kRegion, service)
  hmacSha256(kService, "aws4_request")

proc awsIsoDate(): (string, string) =
  let ts = now().utc()
  (ts.format("yyyyMMdd'T'HHmmss'Z'"), ts.format("yyyyMMdd"))

proc buildAnthropicMessages(userContent: string,
                            conversationHistory: seq[AnthropicMessage]): seq[AnthropicMessage] =
  for msg in conversationHistory:
    result.add msg
  result.add AnthropicMessage(role: "user", content: userContent)

proc httpPostAnthropic(systemPrompt, userContent: string,
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

  let messages = buildAnthropicMessages(userContent, conversationHistory)

  let reqBody = AnthropicRequest(
    model: directAnthropicModel(),
    max_tokens: MaxTokens,
    system: systemPrompt,
    messages: messages
  )

  let startTime = cpuTime()
  var response: Response
  let pool = newCurlPool(1)
  defer: pool.close()
  try:
    response = pool.post(
      AnthropicUrl,
      @[
        ("x-api-key", apiKey),
        ("anthropic-version", AnthropicVersion),
        ("Content-Type", "application/json")
      ],
      reqBody.toJson(),
      float32(TimeoutMs) / 1000.0'f32
    )
  except CatchableError as e:
    let elapsed = int((cpuTime() - startTime) * 1000)
    let lowerMsg = e.msg.toLowerAscii()
    if lowerMsg.contains("timeout") or lowerMsg.contains("timed out"):
      return LlmResult(kind: LlmTimeout, latencyMs: elapsed,
                       detail: "HTTP timeout: " & e.msg)
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

  parseClaudeTextResponse(response.body, elapsed)

proc httpPostBedrock(systemPrompt, userContent: string,
                     conversationHistory: seq[AnthropicMessage] = @[]): LlmResult =
  ## Send a Claude Messages request through AWS Bedrock InvokeModel.
  let (credsOk, creds, credDetail) = resolveAwsCredentials()
  if not credsOk:
    return LlmResult(kind: LlmNoKey,
                     detail: "AWS Bedrock credentials unavailable: " & credDetail)

  let region = awsRegion()
  let host = "bedrock-runtime." & region & ".amazonaws.com"
  let model = bedrockModel()
  let encodedModel = awsUriEncode(model)
  let canonicalUri = "/model/" & encodedModel & "/invoke"
  # Send the raw model id in the URL. SigV4 signs the single-encoded
  # canonical URI above; passing an already-escaped id to libcurl causes
  # AWS to canonicalize `%` again and reject the signature.
  let url = "https://" & host & "/model/" & model & "/invoke"
  let messages = buildAnthropicMessages(userContent, conversationHistory)
  let reqBody = BedrockRequest(
    anthropic_version: BedrockAnthropicVersion,
    max_tokens: MaxTokens,
    temperature: 0.0,
    system: systemPrompt,
    messages: messages
  )
  let payload = reqBody.toJson()
  let payloadHash = sha256Hex(payload)
  let (amzDate, dateStamp) = awsIsoDate()

  var signedHeaders = "accept;content-type;host;x-amz-content-sha256;x-amz-date"
  var canonicalHeaders =
    "accept:application/json\n" &
    "content-type:application/json\n" &
    "host:" & host & "\n" &
    "x-amz-content-sha256:" & payloadHash & "\n" &
    "x-amz-date:" & amzDate & "\n"
  if creds.sessionToken.len > 0:
    signedHeaders.add ";x-amz-security-token"
    canonicalHeaders.add "x-amz-security-token:" & creds.sessionToken & "\n"

  let canonicalRequest =
    "POST\n" & canonicalUri & "\n\n" & canonicalHeaders & "\n" &
    signedHeaders & "\n" & payloadHash
  let credentialScope =
    dateStamp & "/" & region & "/" & BedrockService & "/aws4_request"
  let stringToSign =
    "AWS4-HMAC-SHA256\n" & amzDate & "\n" & credentialScope & "\n" &
    sha256Hex(canonicalRequest)
  let signingKey = sigv4SigningKey(
    creds.secretAccessKey, dateStamp, region, BedrockService
  )
  let signature = hmacSha256(signingKey, stringToSign).toHex()
  let authorization =
    "AWS4-HMAC-SHA256 Credential=" & creds.accessKeyId & "/" &
    credentialScope & ", SignedHeaders=" & signedHeaders &
    ", Signature=" & signature

  var headers = @[
    ("Accept", "application/json"),
    ("Content-Type", "application/json"),
    ("Host", host),
    ("X-Amz-Content-Sha256", payloadHash),
    ("X-Amz-Date", amzDate),
    ("Authorization", authorization)
  ]
  if creds.sessionToken.len > 0:
    headers.add ("X-Amz-Security-Token", creds.sessionToken)

  let startTime = cpuTime()
  var response: Response
  let pool = newCurlPool(1)
  defer: pool.close()
  try:
    response = pool.post(
      url,
      headers,
      payload,
      float32(TimeoutMs) / 1000.0'f32
    )
  except CatchableError as e:
    let elapsed = int((cpuTime() - startTime) * 1000)
    let lowerMsg = e.msg.toLowerAscii()
    if lowerMsg.contains("timeout") or lowerMsg.contains("timed out"):
      return LlmResult(kind: LlmTimeout, latencyMs: elapsed,
                       detail: "Bedrock HTTP timeout: " & e.msg)
    return LlmResult(kind: LlmHttpError, latencyMs: elapsed,
                     detail: "Bedrock HTTP error: " & e.msg)

  let elapsed = int((cpuTime() - startTime) * 1000)

  proc bedrockErrorDetail(): string =
    result = "Bedrock HTTP " & $response.code
    try:
      let data = parseJson(response.body)
      if data.hasKey("message"):
        var msg = data["message"].getStr("").strip()
        let canonicalAt = msg.find("\n\nThe Canonical String")
        if canonicalAt >= 0:
          msg = msg[0 ..< canonicalAt].strip()
        if msg.len > 240:
          msg = msg[0 ..< 240] & "..."
        if msg.len > 0:
          result.add ": " & msg
    except CatchableError:
      discard

  if response.code == 429:
    return LlmResult(kind: LlmRateLimit, latencyMs: elapsed,
                     detail: "Bedrock rate limited (429)")
  if response.code != 200:
    return LlmResult(kind: LlmHttpError, latencyMs: elapsed,
                     detail: bedrockErrorDetail())

  parseClaudeTextResponse(response.body, elapsed)

proc httpPost(systemPrompt, userContent: string,
              conversationHistory: seq[AnthropicMessage] = @[]): LlmResult =
  case selectedProvider()
  of ProviderAnthropic:
    httpPostAnthropic(systemPrompt, userContent, conversationHistory)
  of ProviderBedrock:
    httpPostBedrock(systemPrompt, userContent, conversationHistory)
  of ProviderNone:
    let detail =
      if llmDisabled():
        "LLM disabled by " & GuidedBotLlmDisableEnv
      else:
        "No Anthropic API key or AWS Bedrock credentials configured"
    LlmResult(kind: LlmNoKey, detail: detail)

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
  of "reporting":         (true, ModeReporting)
  of "pretending":        (true, ModePretending)
  of "hunting":           (true, ModeHunting)
  of "fleeing":           (true, ModeFleeing)
  of "alibi_building":    (true, ModeAlibiBuilding)
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
                  if ok and (m == ModePretending or m == ModeIdle):
                    m
                  else:
                    ModePretending
                else: ModePretending
    params = ModeParams(mode: ModeHunting,
                       huntPreferredTarget: pref, huntMaxWitnesses: maxW,
                       huntOpportunistic: opp, huntCoverMode: cover)

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
    # Truncate chat to the same safe length enforced by the action layer.
    let truncated =
      if text.len > MeetingChatMaxLen: text[0 ..< MeetingChatMaxLen]
      else: text
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
  ## Call Claude through the selected provider. Synchronous — designed
  ## to run on the guidance worker thread.
  ##
  ## For gameplay requests: sends the snapshot as the user message with
  ## the gameplay system prompt. Parses the response into a Directive.
  ##
  ## For meeting requests: sends the snapshot + conversation history
  ## with the meeting system prompt. Parses into a MeetingAction.
  if not haveApiKey():
    return LlmResult(kind: LlmNoKey,
                     detail: "No enabled LLM provider")

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
