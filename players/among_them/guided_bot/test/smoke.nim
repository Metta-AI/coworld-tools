## Phase 0 smoke test. Exit status 0 iff:
##   - initBot compiles a fully-formed `Bot`.
##   - decideNextMask returns 0 on an all-zero frame.
##   - The mode registry's default directive for an unknown-role belief
##     routes to `ModeIdle`.
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc test/smoke.nim
##
## Phase 1+ replaces this with a proper test harness (unittest module
## or an opt-in `tools/smoke.sh` wrapper).

import std/strutils
import ../constants
import ../types
import ../bot
import ../mode_registry

proc fail(msg: string) =
  stderr.writeLine "FAIL: ", msg
  quit(1)

proc main() =
  var b = initBot()

  if b.frameTick != 0:
    fail "initBot: frameTick should start at 0"
  if b.belief.tick != 0:
    fail "initBot: belief.tick should start at 0"
  if b.unpacked.len != FrameLen:
    fail "initBot: unpacked buffer should be FrameLen"
  if b.belief.directive.mode != ModeIdle:
    fail "initBot: initial directive should be ModeIdle"

  # Default directive for a blank belief with unknown role: ModeIdle.
  let def = defaultDirectiveFor(b.belief)
  if def.mode != ModeIdle:
    fail "defaultDirectiveFor(unknown role): expected ModeIdle, got " &
      $def.mode

  # One decide on an all-zero frame.
  let zero = newSeq[uint8](FrameLen)
  let mask = b.stepUnpackedFrame(zero)
  if mask != 0'u8:
    fail "phase-0 decideNextMask expected 0, got " & $mask
  if b.frameTick != 1:
    fail "frameTick should increment to 1, got " & $b.frameTick

  # Run a few more ticks; mask stays 0.
  for i in 0 ..< 16:
    let m = b.stepUnpackedFrame(zero)
    if m != 0'u8:
      fail "tick " & $(i + 2) & " mask expected 0, got " & $m
  if b.frameTick != 17:
    fail "frameTick should be 17 after 17 decisions, got " & $b.frameTick

  # Ghost override: flipping isGhost routes ModeHunting -> ModeTaskCompleting.
  b.belief.self.role = RoleImposter
  b.belief.self.isGhost = false
  b.belief.directive = defaultDirectiveFor(b.belief)
  if b.belief.directive.mode != ModeHunting:
    fail "alive imposter default should be ModeHunting, got " &
      $b.belief.directive.mode
  b.belief.self.isGhost = true
  discard b.stepUnpackedFrame(zero)
  if b.belief.directive.mode != ModeTaskCompleting:
    fail "ghost override should force ModeTaskCompleting, got " &
      $b.belief.directive.mode

  echo "OK"

when isMainModule:
  main()
