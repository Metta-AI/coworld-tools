## LLM client (phase 0 stub).
##
## Phase 2 adapts `~/coding/bitworld/src/bitworld/ais/claude.nim` (curly +
## jsony HTTP client, ~60 LOC). Phase 0 defines the types and a stub
## `callLlm` that returns a benign "no change" response so the
## guidance loop can run end-to-end without network access.
##
## The actual API key is read from an env var by the worker thread at
## startup. cogames injects it via `--secret-env ANTHROPIC_API_KEY=...`
## (see `metta/packages/cogames/POLICY_SECRETS.md`).

import std/os
import types

const AnthropicKeyEnv* = "ANTHROPIC_API_KEY"

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

proc haveApiKey*(): bool =
  getEnv(AnthropicKeyEnv, "").len > 0

proc callLlm*(req: LlmRequest): LlmResult =
  ## Phase 0: stub. Returns `LlmNoKey` if no key is configured so callers
  ## can exercise the "no LLM" fallback path. Returns a benign
  ## `LlmSchemaError` otherwise — this is intentional; phase 2 replaces
  ## this proc with a real HTTP call.
  if not haveApiKey():
    return LlmResult(kind: LlmNoKey,
                     detail: "ANTHROPIC_API_KEY not set; phase-0 stub")
  discard req
  LlmResult(kind: LlmSchemaError,
            detail: "phase-0 stub; no HTTP client wired yet")
