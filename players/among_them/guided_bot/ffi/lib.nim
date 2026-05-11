## FFI exports for the cogames training / tournament harness.
##
## Mirrors `modulabot/ffi/lib.nim` with a renamed symbol prefix
## (`guidedbot_*`). The Python wrapper in `cogames/amongthem_policy.py`
## loads this shared library via ctypes.
##
## `actionIndexForMask` maps a button mask to the index in
## `TrainableMasks`. That index is the action index the Python side
## looks up in `mettagrid.bitworld.BITWORLD_ACTION_MASKS` to recover
## the mask to send to the server. **The two tables must be in the
## same order.** A compile-time assertion enforces this; see the
## `CanonicalMasks` block below.
##
## Bump `GuidedBotAbiVersion` below (and
## `build_guided_bot.py:GUIDED_BOT_ABI_VERSION`) whenever the FFI
## surface changes.

when defined(guidedBotLibrary):
  import ../constants
  import ../types
  import ../bot
  import ../trace
  import std/strutils

  const GuidedBotAbiVersion* = 3

  ## Action-index table. Ordering must match
  ## `mettagrid.bitworld.BITWORLD_ACTION_MASKS` exactly. Pattern:
  ## for each direction group {none, up, down, left, right, up+left,
  ## up+right, down+left, down+right}, emit {bare, +A, +B}.
  const TrainableMasks = [
    0'u8,                                        #  0: noop
    ButtonA,                                     #  1: a
    ButtonB,                                     #  2: b
    ButtonUp,                                    #  3: up
    ButtonUp or ButtonA,                         #  4: up+a
    ButtonUp or ButtonB,                         #  5: up+b
    ButtonDown,                                  #  6: down
    ButtonDown or ButtonA,                       #  7: down+a
    ButtonDown or ButtonB,                       #  8: down+b
    ButtonLeft,                                  #  9: left
    ButtonLeft or ButtonA,                       # 10: left+a
    ButtonLeft or ButtonB,                       # 11: left+b
    ButtonRight,                                 # 12: right
    ButtonRight or ButtonA,                      # 13: right+a
    ButtonRight or ButtonB,                      # 14: right+b
    ButtonUp or ButtonLeft,                      # 15: up+left
    ButtonUp or ButtonLeft or ButtonA,           # 16: up+left+a
    ButtonUp or ButtonLeft or ButtonB,           # 17: up+left+b
    ButtonUp or ButtonRight,                     # 18: up+right
    ButtonUp or ButtonRight or ButtonA,          # 19: up+right+a
    ButtonUp or ButtonRight or ButtonB,          # 20: up+right+b
    ButtonDown or ButtonLeft,                    # 21: down+left
    ButtonDown or ButtonLeft or ButtonA,         # 22: down+left+a
    ButtonDown or ButtonLeft or ButtonB,         # 23: down+left+b
    ButtonDown or ButtonRight,                   # 24: down+right
    ButtonDown or ButtonRight or ButtonA,        # 25: down+right+a
    ButtonDown or ButtonRight or ButtonB,        # 26: down+right+b
  ]

  # Compile-time assertion: derive the canonical table from the
  # direction × modifier pattern and verify element-wise equality.
  # This catches ordering drift the moment anyone edits TrainableMasks
  # or the button constants.
  const CanonicalMasks = block:
    var res: array[27, uint8]
    let dirs: array[9, uint8] = [
      0'u8, ButtonUp, ButtonDown, ButtonLeft, ButtonRight,
      ButtonUp or ButtonLeft, ButtonUp or ButtonRight,
      ButtonDown or ButtonLeft, ButtonDown or ButtonRight]
    let mods: array[3, uint8] = [0'u8, ButtonA, ButtonB]
    for i in 0 ..< 9:
      for j in 0 ..< 3:
        res[i * 3 + j] = dirs[i] or mods[j]
    res

  static:
    doAssert TrainableMasks.len == CanonicalMasks.len,
      "TrainableMasks length mismatch vs canonical BITWORLD table"
    for i in 0 ..< TrainableMasks.len:
      doAssert TrainableMasks[i] == CanonicalMasks[i],
        "TrainableMasks[" & $i & "] mismatch"

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
      policy.bots[i] = initBot(botIndex = i)
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
        policy.bots[i] = initBot(botIndex = i)

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

  proc copyToBuffer(text: string, buffer: pointer, bufferLen: cint): cint =
    ## Copies up to ``bufferLen - 1`` bytes and NUL-terminates.
    if buffer.isNil or bufferLen <= 0 or text.len == 0:
      return cint(0)
    let dst = cast[ptr UncheckedArray[byte]](buffer)
    let maxLen = min(text.len, int(bufferLen) - 1)
    for i in 0 ..< maxLen:
      dst[i] = byte(text[i])
    dst[maxLen] = 0
    cint(maxLen)

  proc guidedbot_take_chat*(
      handle: cint,
      agentId: cint,
      buffer: pointer,
      bufferLen: cint): cint {.exportc, dynlib.} =
    ## Drains one queued meeting chat line for the Python/WebSocket bridge.
    if handle < 0 or int(handle) >= GuidedBotPolicies.len:
      return cint(0)
    let policy = GuidedBotPolicies[int(handle)]
    if policy.isNil or int(agentId) < 0 or int(agentId) >= policy.bots.len:
      return cint(0)
    let text = policy.bots[int(agentId)].actionState.pendingChat
    if text.len == 0:
      return cint(0)
    let written = copyToBuffer(text, buffer, bufferLen)
    policy.bots[int(agentId)].actionState.pendingChat = ""
    written

  proc guidedbot_destroy_policy*(handle: cint) {.exportc, dynlib.} =
    ## Tear down a policy: call destroyBot on each bot (stops guidance
    ## worker, flushes and closes trace writer), then release the slot.
    ## Safe to call multiple times — subsequent calls on the same handle
    ## are no-ops.
    if handle < 0 or int(handle) >= GuidedBotPolicies.len:
      return
    let policy = GuidedBotPolicies[int(handle)]
    if policy.isNil:
      return
    for i in 0 ..< policy.bots.len:
      destroyBot(policy.bots[i])
    GuidedBotPolicies[int(handle)] = nil

  proc guidedbot_set_trace_dir*(handle: cint, traceDir: cstring,
                                 traceLevel: cstring) {.exportc, dynlib.} =
    ## Override trace configuration for all bots in a policy.
    ## Must be called BEFORE the first step_batch for correct results.
    ## Closes any existing trace writers and reopens with the new
    ## directory. Each bot gets a unique session subdirectory via the
    ## instance counter in openTrace.
    ##
    ## Pass an empty traceDir to disable tracing.
    ## This is an additive FFI export — old callers that don't know about
    ## it simply never call it and the env-var path still works.
    if handle < 0 or int(handle) >= GuidedBotPolicies.len:
      return
    let policy = GuidedBotPolicies[int(handle)]
    if policy.isNil:
      return
    let dir = $traceDir
    let levelStr = ($traceLevel).toLowerAscii()
    let level = case levelStr
      of "events":    TraceEvents
      of "decisions": TraceDecisions
      of "full":      TraceFull
      else:           TraceOff
    for i in 0 ..< policy.bots.len:
      if policy.bots[i].trace != nil:
        closeTrace(policy.bots[i].trace)
        policy.bots[i].trace = nil
      if dir.len > 0 and level != TraceOff:
        policy.bots[i].trace = openTrace(dir, level, botIndex = i)
