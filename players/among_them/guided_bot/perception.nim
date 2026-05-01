## Perception pipeline orchestrator.
##
## One entry point — `perceive(frame) -> Percept` — that runs every
## phase's observations against a single unpacked frame and packages
## the results into a `Percept` value. `belief.updateBelief` merges
## the percept into the long-lived `Belief`.
##
## The pipeline is explicitly additive per phase: each sub-phase
## populates more fields of `Percept` than the previous. See
## DESIGN.md §15 for the full sub-phase plan.
##
## Phase 1.0 populates:
##   - `tick`
##   - `interstitial` (kind + black-pixel count)
##   - `ignoreMask`   (player-centre zone + radar colour; no per-sprite
##                     exclusions yet — those are stamped in the bot
##                     pipeline after the actor scan)
##
## Phase 1.3 adds:
##   - `actors`       (crewmates, bodies, ghosts, role, self-colour)
##                     via `perception/actors.scanAll`. The bot pipeline
##                     runs `scanAll` after localize (needs camera for
##                     future world-coord conversion) and stamps actor
##                     exclusions into the ignore mask.

import types
export types  # re-exported so consumers of `Percept` get the shared enums.

import perception/data
import perception/frame
import perception/interstitial
import perception/ignore
import perception/actors as actorsModule

export data, frame, interstitial, ignore, actorsModule

type
  Percept* = object
    ## Structured output of one perception tick. Fields populated
    ## incrementally per sub-phase; phase 1.0 sets the interstitial
    ## observation and the ignore mask; phase 1.3 adds the actor
    ## percept.
    tick*: int
    interstitial*: InterstitialObservation
    ignoreMask*: IgnoreMask
    actors*: ActorPercept

proc initPercept*(): Percept =
  Percept(
    tick: 0,
    interstitial: InterstitialObservation(
      isInterstitial: false,
      kind: NotInterstitial,
      blackPixelCount: 0
    ),
    ignoreMask: initIgnoreMask(),
    actors: initActorPercept()
  )

proc perceive*(frameBuf: openArray[uint8], tick: int): Percept =
  ## Phase 1.0 perception pipeline (interstitial + ignore mask).
  ##
  ## Actor scanning (phase 1.3) is NOT called here — it's called
  ## from the bot pipeline after localize, because scanning needs
  ## the camera lock to compute world coordinates, and the results
  ## feed back into the ignore mask. See ``bot.decideNextMask``.
  ##
  ## Preconditions: `frameBuf.len == FrameLen`. A wrong length is a
  ## caller bug, not a frame corruption — we assert rather than
  ## silently degrade.
  doAssert frameBuf.len == FrameLen,
    "perceive: frameBuf.len (" & $frameBuf.len &
      ") != FrameLen (" & $FrameLen & ")"

  result = initPercept()
  result.tick = tick

  # Gate 1 — interstitial detection (black-pixel %).
  result.interstitial = detectInterstitial(frameBuf)

  # Gate 2 — ignore-mask scaffolding. Build it even during
  # interstitials so the caller has a consistent output shape; the
  # mask is only consulted by localize, which won't run on
  # interstitials anyway.
  buildPhase10IgnoreMask(result.ignoreMask, frameBuf)
