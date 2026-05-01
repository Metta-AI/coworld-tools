## FFI exports for the cogames training / tournament harness.
##
## Mirrors `modulabot/ffi/lib.nim` with a renamed symbol prefix
## (`guidedbot_*`). The Python wrapper in `cogames/amongthem_policy.py`
## loads this shared library via ctypes.
##
## Phase 0: handles + frame dimensions are validated, but every step
## returns action index 0 (idle) because `decideNextMask` returns 0.
## Phase 1+ doesn't need to change this file — once `decideNextMask`
## returns real masks, the existing `actionIndexForMask` lookup
## translates them into the cogames action table.
##
## Bump `GuidedBotAbiVersion` below (and
## `build_guided_bot.py:GUIDED_BOT_ABI_VERSION`) whenever the FFI
## surface changes.

when defined(guidedBotLibrary):
  import ../constants
  import ../types
  import ../bot

  const GuidedBotAbiVersion* = 1

  const TrainableMasks = [
    0'u8,
    ButtonA,
    ButtonB,
    ButtonUp,
    ButtonDown,
    ButtonLeft,
    ButtonRight,
    ButtonUp or ButtonA,
    ButtonDown or ButtonA,
    ButtonLeft or ButtonA,
    ButtonRight or ButtonA,
    ButtonUp or ButtonB,
    ButtonDown or ButtonB,
    ButtonLeft or ButtonB,
    ButtonRight or ButtonB,
    ButtonUp or ButtonLeft,
    ButtonUp or ButtonRight,
    ButtonDown or ButtonLeft,
    ButtonDown or ButtonRight,
    ButtonUp or ButtonLeft or ButtonA,
    ButtonUp or ButtonRight or ButtonA,
    ButtonDown or ButtonLeft or ButtonA,
    ButtonDown or ButtonRight or ButtonA,
    ButtonUp or ButtonLeft or ButtonB,
    ButtonUp or ButtonRight or ButtonB,
    ButtonDown or ButtonLeft or ButtonB,
    ButtonDown or ButtonRight or ButtonB,
  ]

  type GuidedBotPolicy = ref object
    bots: seq[Bot]

  var GuidedBotPolicies: seq[GuidedBotPolicy]

  proc actionIndexForMask(mask: uint8): int32 =
    for i, m in TrainableMasks:
      if m == mask: return int32(i)
    0

  proc stepUnpackedFramePtr(bot: var Bot,
                            frame: ptr UncheckedArray[uint8],
                            frameLen: int): uint8 =
    if frame.isNil or frameLen != FrameLen:
      return bot.lastMask
    if bot.unpacked.len != frameLen:
      bot.unpacked.setLen(frameLen)
    for i in 0 ..< frameLen:
      bot.unpacked[i] = frame[i] and 0x0f'u8
    decideNextMask(bot)

  proc guidedbot_abi_version*(): cint {.exportc, dynlib.} =
    cint(GuidedBotAbiVersion)

  proc guidedbot_new_policy*(numAgents: cint): cint {.exportc, dynlib.} =
    let count = max(1, int(numAgents))
    var policy = GuidedBotPolicy(bots: newSeq[Bot](count))
    for i in 0 ..< count:
      policy.bots[i] = initBot()
    GuidedBotPolicies.add(policy)
    cint(GuidedBotPolicies.len - 1)

  proc guidedbot_step_batch*(
      handle: cint,
      agentIds: ptr UncheckedArray[int32],
      numAgentIds: cint,
      numAgents: cint,
      frameStack: cint,
      height: cint,
      width: cint,
      observations: pointer,
      actions: pointer) {.exportc, dynlib.} =
    if handle < 0 or int(handle) >= GuidedBotPolicies.len:
      return
    if observations.isNil or actions.isNil or agentIds.isNil:
      return
    if frameStack <= 0 or height != ScreenHeight or width != ScreenWidth:
      return

    let
      policy = GuidedBotPolicies[int(handle)]
      obs = cast[ptr UncheckedArray[uint8]](observations)
      outs = cast[ptr UncheckedArray[int32]](actions)
      rowLen = int(height) * int(width)
      rowStride = int(frameStack) * rowLen
      latestOffset = (int(frameStack) - 1) * rowLen

    if policy.bots.len < int(numAgents):
      let oldLen = policy.bots.len
      policy.bots.setLen(int(numAgents))
      for i in oldLen ..< policy.bots.len:
        policy.bots[i] = initBot()

    for row in 0 ..< int(numAgentIds):
      let agentId = int(agentIds[row])
      if agentId < 0 or agentId >= policy.bots.len:
        outs[row] = 0
        continue
      let frame = cast[ptr UncheckedArray[uint8]](
        cast[uint](obs) + uint(row * rowStride + latestOffset)
      )
      let mask = policy.bots[agentId].stepUnpackedFramePtr(frame, rowLen)
      outs[row] = actionIndexForMask(mask)
