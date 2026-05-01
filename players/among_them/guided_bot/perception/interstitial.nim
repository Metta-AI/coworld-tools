## Interstitial detection — the cheap first gate of the per-frame
## pipeline. Phase 1.0.
##
## Among Them's voting screen, role-reveal, vote-result, and game-over
## screens are all rendered with a black background covering most of
## the framebuffer. Gameplay never does; off-map pixels in gameplay
## are filled with `MapVoidColor` (palette index 12), not black (see
## `bitworld/among_them/players/how_to_make_a_bot.md` § "Interstitial
## Detection"). That lets a 30 %-or-more-black-pixels test cleanly
## separate the two without false positives from off-map padding.
##
## Phase 1.0 distinguishes only "black-enough to be an interstitial"
## from "gameplay". Phase 1.5 (OCR) reads the actual interstitial
## text and classifies into role-reveal / voting / vote-result /
## game-over subtypes. Until then all interstitials are reported as
## `InterstitialUnknown`.

import ../constants
import ../types
import frame

const
  ## Minimum fraction of black pixels for a frame to be classified as
  ## an interstitial, expressed as a count threshold over `FrameLen`.
  ## Matches modulabot's `INTERSTITIAL_BLACK_PERCENT = 30` in both the
  ## Python port (`frame.py`) and the original Nim implementation
  ## (`bitworld/among_them/players/modulabot/frame.nim`). Keep this
  ## constant in lockstep.
  InterstitialBlackPercent* = 30
  InterstitialBlackThreshold* = (InterstitialBlackPercent * FrameLen + 99) div 100

type
  InterstitialObservation* = object
    ## What `detectInterstitial` reports. Embedded directly into
    ## `Percept` (see `perception.nim`) so belief update can merge it
    ## without re-running the scan.
    isInterstitial*: bool
    kind*: InterstitialKind
    blackPixelCount*: int

proc detectInterstitial*(frame: openArray[uint8]): InterstitialObservation =
  ## Classify a single unpacked frame as interstitial or gameplay.
  ##
  ## Semantics: pure black-pixel count threshold. We do NOT look at
  ## the four screen corners (that's the pre-2024 modulabot heuristic
  ## that `how_to_make_a_bot.md` documents as having broken when chat
  ## text or UI marks touched corners).
  ##
  ## Phase 1.0 returns `InterstitialUnknown` for any black-enough
  ## frame. Phase 1.5 refines that to the correct `InterstitialKind`
  ## variant via OCR.
  result.blackPixelCount = frame.blackPixelCount()
  if result.blackPixelCount >= InterstitialBlackThreshold:
    result.isInterstitial = true
    result.kind = InterstitialUnknown
  else:
    result.isInterstitial = false
    result.kind = NotInterstitial

proc phaseFromInterstitial*(
    prevPhase: GamePhase,
    obs: InterstitialObservation): GamePhase =
  ## Phase transition rule for phase 1.0. Only two states the
  ## observation can confirm with certainty: "interstitial" (some
  ## kind of gap screen) and "gameplay" (map is visible).
  ##
  ## Phase 1.5's OCR-refined interstitial kind lets us disambiguate
  ## voting vs. role-reveal vs. game-over; until then we keep any
  ## non-Unknown phase the caller had before if the interstitial
  ## observation is consistent with it, to avoid thrash.
  if obs.isInterstitial:
    case prevPhase
    of PhaseVoting, PhaseGameOver:
      prevPhase
    else:
      PhaseInterstitial
  else:
    PhaseGameplay
