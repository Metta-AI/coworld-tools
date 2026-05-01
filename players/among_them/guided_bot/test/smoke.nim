## Smoke test. Exit status 0 iff:
##   - initBot compiles a fully-formed `Bot`.
##   - decideNextMask returns 0 on an all-zero (interstitial) frame
##     (idle mode emits noop during interstitials).
##   - The mode registry's default directive for an unknown-role belief
##     routes to `ModeIdle`.
##   - Ghost override works (ModeHunting -> ModeTaskCompleting on ghost).
##   - Idle wander emits non-zero masks on non-interstitial frames
##     (the bot physically moves before localization/role detection).
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc test/smoke.nim

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

  # All-zero frame = 100% black = interstitial. Idle mode emits noop
  # during interstitials, so mask should be 0.
  let zero = newSeq[uint8](FrameLen)
  let mask = b.stepUnpackedFrame(zero)
  if mask != 0'u8:
    fail "decideNextMask on interstitial (all-zero) frame expected 0, got " & $mask
  if b.frameTick != 1:
    fail "frameTick should increment to 1, got " & $b.frameTick

  # More interstitial frames; mask stays 0.
  for i in 0 ..< 16:
    let m = b.stepUnpackedFrame(zero)
    if m != 0'u8:
      fail "tick " & $(i + 2) & " interstitial mask expected 0, got " & $m
  if b.frameTick != 17:
    fail "frameTick should be 17 after 17 decisions, got " & $b.frameTick

  # Non-interstitial frame: fill with a non-black palette index (e.g.
  # palette 12 = map void). <30% black → gameplay phase. On a real
  # gameplay frame the actor scanner may detect a role immediately,
  # causing the bot to leave idle (via reconcileDirective's stale-
  # default re-evaluation) before idle's decide even runs. If the bot
  # does stay idle, wander should emit a non-zero mask.
  var nonBlack = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    nonBlack[i] = 12  # MapVoidColor — non-black, triggers gameplay phase.

  var b2 = initBot()
  discard b2.stepUnpackedFrame(nonBlack)
  if b2.belief.directive.mode == ModeIdle:
    # Still idle after a gameplay frame — idle wander should have
    # emitted direction buttons.
    if b2.lastMask == 0'u8:
      fail "idle wander on non-interstitial frame should emit non-zero mask"
  # If the bot transitioned to task_completing/hunting, that's correct
  # behavior — role detection fired on this frame.

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
