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
##                     exclusions yet — those arrive in phase 1.3/1.4)
##
## Phase 1.1 will add the static reference data (map, sprites, font)
## to a sibling `perception/data.nim` module. Phase 1.2 will add
## camera localization that consumes `ignoreMask`. Phase 1.3+ add
## actor / task / voting scanning.

import types
export types  # re-exported so consumers of `Percept` get the shared enums.

import perception/data
import perception/frame
import perception/interstitial
import perception/ignore

export data, frame, interstitial, ignore

type
  Percept* = object
    ## Structured output of one perception tick. Fields populated
    ## incrementally per sub-phase; phase 1.0 sets the interstitial
    ## observation and the ignore mask, leaves the rest at their
    ## default-zero values.
    tick*: int
    interstitial*: InterstitialObservation
    ignoreMask*: IgnoreMask

proc initPercept*(): Percept =
  Percept(
    tick: 0,
    interstitial: InterstitialObservation(
      isInterstitial: false,
      kind: NotInterstitial,
      blackPixelCount: 0
    ),
    ignoreMask: initIgnoreMask()
  )

proc perceive*(frameBuf: openArray[uint8], tick: int): Percept =
  ## Phase 1.0 perception pipeline.
  ##
  ## Ordering: interstitial detection first (cheapest; gates anything
  ## map-dependent), ignore-mask construction second (will be consumed
  ## by phase 1.2 localize). No sprite scans yet — those require map
  ## and sprite data that arrives in phase 1.1.
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
