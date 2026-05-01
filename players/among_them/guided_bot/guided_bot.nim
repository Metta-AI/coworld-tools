## guided_bot CLI entry point.
##
## Phase 0: parses a minimal flag set and exits cleanly without
## connecting to any server. Phase 2 fills in a `viewer/runner.nim`-
## style loop that opens a WebSocket to the Among Them server, drains
## frames, calls `bot.stepUnpackedFrame`, and emits masks/chat. The
## entry-point layout mirrors `modulabot/modulabot.nim` so the phase-2
## port is mechanical.
##
## When built as a shared library (`-d:guidedBotLibrary`), this module
## re-exports `ffi/lib`; the `isMainModule` block below doesn't run.

when defined(guidedBotLibrary):
  import ffi/lib
  export lib
else:
  import std/[os, parseopt, strutils]
  import constants
  import bot

  proc runStub(address: string, port: int, name, mapPath, framesPath: string) =
    ## Phase 0: construct a bot, report parsed flags, exit. Phase 2
    ## replaces with a real WebSocket loop.
    var b = initBot()
    echo "guided_bot (phase 0 skeleton)"
    echo "  server     : ", address, ":", port
    echo "  name       : ", name
    echo "  map path   : ", (if mapPath.len == 0: "(default)" else: mapPath)
    echo "  frames path: ", (if framesPath.len == 0: "(off)" else: framesPath)
    # One dry decideNextMask on an all-zero frame to prove wiring.
    let zero = newSeq[uint8](FrameLen)
    let mask = b.stepUnpackedFrame(zero)
    echo "  phase-0 smoke mask (expected 0): ", mask
    echo "  frame tick after smoke          : ", b.frameTick

  when isMainModule and not defined(guidedBotLibrary):
    var
      address = DefaultHost
      port = DefaultPort
      name = ""
      mapPath = ""
      framesPath = ""
    for kind, key, val in getopt():
      case kind
      of cmdLongOption:
        case key
        of "address": address = val
        of "port":    port = parseInt(val)
        of "name":    name = val
        of "map":     mapPath = val
        of "frames":  framesPath = val
        else: discard
      else: discard
    if mapPath.len > 0 and not mapPath.isAbsolute():
      mapPath = absolutePath(mapPath)
    if framesPath.len > 0 and not framesPath.isAbsolute():
      framesPath = absolutePath(framesPath)
    runStub(address, port, name, mapPath, framesPath)
