## Perception layer (phase 0 stub).
##
## Phase 0: the inner loop hands perceived frames to `perceive`, which
## currently does nothing. Phase 1 wires in modulabot's perception
## modules (localize, sprite_match, actors, tasks, voting parse, ascii
## OCR) and produces a percept that `belief.updateBelief` merges.
##
## Keeping this as its own module (rather than inlining into bot.nim)
## makes the phase-1 port mechanical: drop the existing bitworld imports
## in here and expose a single `perceive(frame) -> Percept` proc.

import types
# types is re-exported for phase-1 callers that consume Percept alongside
# the full Belief; phase 0 doesn't need it internally but we keep the
# import so removing it isn't a breaking change downstream.
export types

type
  Percept* = object
    ## Phase 0 placeholder. Phase 1: this is the output of one frame of
    ## perception work — visible actors, camera lock, task icons, radar
    ## dots, interstitial state, voting parse, new chat lines, role
    ## reveal, etc. See DESIGN.md §4.1.
    tick*: int

proc initPercept*(): Percept = Percept(tick: 0)

proc perceive*(frame: openArray[uint8]): Percept =
  ## Phase 0: empty percept.
  discard frame
  initPercept()
