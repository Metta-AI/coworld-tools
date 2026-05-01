## Guidance-loop worker thread shell (phase 0 stub).
##
## Phase 2 spawns an OS thread here that:
##   - blocks on `snapshotChan` (newest-snapshot-wins),
##   - renders a prompt, calls `llm.callLlm`, parses and validates the
##     response,
##   - pushes the validated `Directive` onto `directiveChan`, and during
##     meetings pushes `MeetingAction` values onto `meetingActionChan`.
##
## The inner loop never blocks on this. See DESIGN.md §10.
##
## Phase 0: the module compiles and declares the channel types but does
## not spawn a thread. Gated by `-d:guidedBotGuidance` for phase 2.

import types

type
  Snapshot* = object
    ## Phase 0: placeholder. Phase 2: the curated JSON snapshot the LLM
    ## sees (DESIGN.md §8.3) plus a request kind and conversation handle.
    tick*: int
    payloadJson*: string
    isMeeting*: bool

  GuidanceState* = object
    ## Phase 0: empty shell. Phase 2 holds the channel handles, the
    ## thread ref, the per-meeting conversation history, and call-rate
    ## accounting.
    running*: bool
    callsThisMatch*: int
    lastCallTick*: int
    meetingConversationJson*: string

proc initGuidanceState*(): GuidanceState =
  GuidanceState(
    running: false,
    callsThisMatch: 0,
    lastCallTick: -1,
    meetingConversationJson: ""
  )

proc startGuidance*(state: var GuidanceState) =
  ## Phase 0: no-op. Phase 2: spawn the worker thread.
  state.running = false

proc stopGuidance*(state: var GuidanceState) =
  ## Phase 0: no-op. Phase 2: signal worker, join the thread.
  state.running = false

proc submitSnapshot*(state: var GuidanceState, snap: Snapshot) =
  ## Phase 0: no-op. Phase 2: push onto `snapshotChan`, drop the current
  ## pending snapshot (newest wins).
  discard state
  discard snap

proc tryReceiveDirective*(state: var GuidanceState,
                          directive: var Directive): bool =
  ## Phase 0: no-op. Phase 2: non-blocking drain of `directiveChan`,
  ## keep the newest, return true iff a fresh directive landed.
  discard state
  discard directive
  false

proc tryReceiveMeetingAction*(state: var GuidanceState,
                              act: var MeetingAction): bool =
  ## Phase 0: no-op. Phase 2: pop the next `MeetingAction` from
  ## `meetingActionChan` (FIFO, one per call).
  discard state
  discard act
  false
