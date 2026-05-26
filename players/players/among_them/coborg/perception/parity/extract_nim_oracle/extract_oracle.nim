## Nim oracle dumper for the among-them-coborg perception parity rig.
##
## Walks every `.bin` fixture in `../fixtures/`, runs the upstream
## perception modules against it, and writes a JSON sidecar next to
## each fixture (`gameplay_131.bin` -> `gameplay_131.json`). The
## Python parity harness in `perception/parity/run_parity.py` consumes
## those sidecars as the ground-truth oracle for the perception port.
##
## Schema versions:
##
## - v1 (S2 first pass): kernel-level outputs for the player sprite
##   only, at crewmate budgets, both horizontal flips. Covered
##   `frame.py` + `sprite_match.py`.
## - v2 (S3 kickoff): widens kernel coverage to body + ghost sprites
##   at their own budgets, and adds **orchestrated** outputs from the
##   upstream `guided_bot/perception/actors.nim` and
##   `guided_bot/perception/tasks.nim` — role detection, self colour,
##   crewmate / body / ghost match lists, and radar-dot positions.
##   The task-icon half of `tasks.nim` is deferred to S4 alongside
##   localize (see `PLAN.md` §12 item 5).
## - v3 (S4.1): adds the upstream `interstitial.detectInterstitial`
##   output (black-pixel count + boolean + kind). S4.2 (ignore-mask
##   stamps) and S4.3 (localize) extend v3 with additional keys.
##
## Each sidecar's `schema_version` field declares the version the
## sidecar conforms to. The Python harness fails closed on unknown
## versions; the v1 keys are still emitted at v2 for backward
## compatibility with kernel-level checks.
##
## Self-contained: imports the upstream
## `users/james/personal_cogs/among_them/common/perception_kernels/`
## and `guided_bot/perception/` modules via the `--path` directive in
## `nim.cfg`. The upstream `data.nim` embeds the baked sprite atlas
## via compile-time `staticRead`. No `nimble`, no FFI, no
## `libguidedbot.dylib`. Fits the AGENTS.md offline-tools exemption:
## reads checked-in fixtures, produces checked-in sidecars, never
## talks to a live game.
##
## Regenerate with::
##
##     nim c -r players/among_them/coborg/perception/parity/extract_nim_oracle/extract_oracle.nim
##
## or from inside the dumper directory::
##
##     nim c -r extract_oracle.nim

import std/[json, os, strformat]

# Low-level kernel — used for v1-shape kernel outputs.
import common/perception_kernels/sprite_match as ksm

# Upstream orchestrated procs — used for v2 outputs.
import guided_bot/perception/actors as gbActors
import guided_bot/perception/tasks as gbTasks
import guided_bot/perception/data as gbData
import guided_bot/types as gbTypes

# Upstream interstitial detector — used for v3 outputs.
import guided_bot/perception/interstitial as gbInterstitial

const
  ScreenWidth = 128
  ScreenHeight = 128
  FrameLen = ScreenWidth * ScreenHeight
  SpriteSize = 12
  SpriteCount = 6
  SchemaVersion = 3

  # Crewmate (= player sprite) scan budgets.
  CrewmateMaxMisses = 8
  CrewmateMinStable = 8
  CrewmateMinTint = 8

  # Body sprite scan budgets.
  BodyMaxMisses = 9
  BodyMinStable = 6
  BodyMinTint = 6

  # Ghost sprite scan budgets.
  GhostMaxMisses = 9
  GhostMinStable = 6
  GhostMinTint = 6

  # Sprite atlas order, parallel to indices 0..5. Pinned to
  # guided_bot/perception/data.nim's `loadSprites()` slot assignment.
  # snake_case names match coborg/perception/data/sprite_index.json.
  SpriteNames: array[SpriteCount, string] = [
    "player", "body", "ghost", "task", "kill_button", "ghost_icon"
  ]

type
  KernelBudget = tuple[maxMisses, minStable, minTint: int]

const
  # Kernel-level oracle entries are emitted for the actor sprites
  # (player, body, ghost). Task-icon (atlas 3) and the HUD icons
  # (kill_button atlas 4, ghost_icon atlas 5) are not whole-frame
  # scan targets — task icons wait for S4 (need localize); HUD
  # icons are scalar probes recorded under the `role` field.
  KernelSpriteIndices: array[3, int] = [0, 1, 2]
  KernelBudgets: array[3, KernelBudget] = [
    (CrewmateMaxMisses, CrewmateMinStable, CrewmateMinTint),
    (BodyMaxMisses,     BodyMinStable,     BodyMinTint),
    (GhostMaxMisses,    GhostMinStable,    GhostMinTint),
  ]
  # Bodies don't flip in-game; player and ghost sprites do. Match the
  # upstream `scanBodies` / `scanGhosts` / `scanCrewmates` flip lists.
  KernelFlips: array[3, seq[cint]] = [
    @[0.cint, 1.cint],  # player
    @[0.cint],          # body
    @[0.cint, 1.cint],  # ghost
  ]

# Compile-time-embedded sprite atlas; same bytes as the upstream
# `sprites.bin` consumed by `data.nim`. Path is relative to *this*
# source file (`extract_oracle.nim`).
const AtlasBlob = staticRead(
  "../../../../../../users/james/personal_cogs/among_them/" &
  "guided_bot/perception/baked/sprites.bin"
)

static:
  doAssert AtlasBlob.len == SpriteCount * SpriteSize * SpriteSize,
    "extract_oracle: sprites.bin wrong size; regenerate baked assets"
  doAssert ksm.ScreenWidth == ScreenWidth
  doAssert ksm.ScreenHeight == ScreenHeight

# ---------------------------------------------------------------------------
# Kernel-level outputs (v1-compatible, widened to body + ghost in v2)
# ---------------------------------------------------------------------------

proc spriteAt(idx: int): array[SpriteSize * SpriteSize, uint8] =
  ## Copy sprite `idx` out of the embedded atlas into a fresh array.
  let base = idx * SpriteSize * SpriteSize
  for i in 0 ..< SpriteSize * SpriteSize:
    result[i] = uint8(AtlasBlob[base + i])

proc anchorsJson(mask: openArray[uint8]): JsonNode =
  ## Serialise the `mb_match_actor_sprite_all` mask as `[ay, ax]` pairs
  ## in raster order. Sparse representation: only positive anchors are
  ## recorded.
  result = newJArray()
  const maxY = ScreenHeight - SpriteSize + 1
  const maxX = ScreenWidth - SpriteSize + 1
  for ay in 0 ..< maxY:
    for ax in 0 ..< maxX:
      if mask[ay * maxX + ax] != 0:
        result.add(%*[ay, ax])

proc colorIndicesAtAnchorsJson(
    indices: openArray[int8], matchMask: openArray[uint8]
): JsonNode =
  ## Serialise `mb_actor_color_index_all` output as `[ay, ax, color_idx]`
  ## triples, **only at anchors where `mb_match_actor_sprite_all` also
  ## reported a match**. A bare dump of the full per-anchor color array
  ## would be hugely redundant (the proc returns a non-(-1) value at
  ## essentially every anchor on a typical frame because every PICO-8
  ## palette index is in `PlayerColors[]`); the downstream consumer in
  ## upstream `actors.nim` only ever reads it at match-mask anchors.
  result = newJArray()
  const maxY = ScreenHeight - SpriteSize + 1
  const maxX = ScreenWidth - SpriteSize + 1
  for ay in 0 ..< maxY:
    for ax in 0 ..< maxX:
      if matchMask[ay * maxX + ax] != 0:
        let v = indices[ay * maxX + ax]
        result.add(%*[ay, ax, int(v)])

proc runKernelOneFlip(
    frame: var seq[uint8],
    sprite: var array[SpriteSize * SpriteSize, uint8],
    budget: KernelBudget,
    flipH: cint,
): tuple[anchors, colorIndices: JsonNode] =
  ## Call both upstream kernels once for the given (sprite, budget, flip)
  ## triple and build their JSON-serialisable outputs. Sharing the match
  ## mask between the two avoids a redundant second sweep and lets us
  ## trim the color-index output to only the meaningful anchor set.
  const maxY = ScreenHeight - SpriteSize + 1
  const maxX = ScreenWidth - SpriteSize + 1
  var matchMask = newSeq[uint8](maxY * maxX)
  ksm.mb_match_actor_sprite_all(
    cast[ptr UncheckedArray[uint8]](addr frame[0]),
    cast[ptr UncheckedArray[uint8]](addr sprite[0]),
    SpriteSize.cint, SpriteSize.cint, flipH,
    budget.maxMisses.cint, budget.minStable.cint, budget.minTint.cint,
    cast[ptr UncheckedArray[uint8]](addr matchMask[0]),
  )
  var colorIdx = newSeq[int8](maxY * maxX)
  ksm.mb_actor_color_index_all(
    cast[ptr UncheckedArray[uint8]](addr frame[0]),
    cast[ptr UncheckedArray[uint8]](addr sprite[0]),
    SpriteSize.cint, SpriteSize.cint, flipH,
    cast[ptr UncheckedArray[int8]](addr colorIdx[0]),
  )
  result = (anchorsJson(matchMask), colorIndicesAtAnchorsJson(colorIdx, matchMask))

proc kernelEntries(
    frame: var seq[uint8]
): tuple[spriteMatches, actorColorIndex: JsonNode] =
  ## Iterate the (atlas slot, budget, flip) combinations that get
  ## kernel-level oracle entries and build the two top-level arrays.
  var spriteMatches = newJArray()
  var actorColorIndex = newJArray()
  for i, spriteIdx in KernelSpriteIndices:
    let budget = KernelBudgets[i]
    var sprite = spriteAt(spriteIdx)
    for flipH in KernelFlips[i]:
      let (anchors, colors) = runKernelOneFlip(frame, sprite, budget, flipH)
      spriteMatches.add(%* {
        "sprite": SpriteNames[spriteIdx],
        "atlas_index": spriteIdx,
        "sh": SpriteSize,
        "sw": SpriteSize,
        "flip_h": flipH.int != 0,
        "max_misses": budget.maxMisses,
        "min_stable": budget.minStable,
        "min_tint": budget.minTint,
        "anchors": anchors,
      })
      actorColorIndex.add(%* {
        "sprite": SpriteNames[spriteIdx],
        "atlas_index": spriteIdx,
        "sh": SpriteSize,
        "sw": SpriteSize,
        "flip_h": flipH.int != 0,
        "indices": colors,
      })
  (spriteMatches, actorColorIndex)

# ---------------------------------------------------------------------------
# Orchestrated outputs (v2)
# ---------------------------------------------------------------------------

proc roleToString(role: gbTypes.BotRole): string =
  ## Serialise the upstream `BotRole` enum as a stable lowercase string.
  case role
  of gbTypes.RoleUnknown: "unknown"
  of gbTypes.RoleCrewmate: "crewmate"
  of gbTypes.RoleImposter: "imposter"

proc roleJson(p: gbActors.ActorPercept): JsonNode =
  ## Result of `updateRole`. Captured with no prior frame history
  ## (`prevGhostIconFrames=0, prevKillIconFrames=0, prevRole=Unknown`)
  ## so the oracle treats each fixture as a fresh first-frame check.
  %* {
    "ghost_icon_frames": p.ghostIconFrames,
    "kill_icon_frames": p.killIconFrames,
    "is_ghost": p.isGhost,
    "kill_ready": p.killReady,
    "role_updated": p.roleUpdated,
    "new_role": roleToString(p.newRole),
  }

proc selfColorJson(p: gbActors.ActorPercept): JsonNode =
  ## Result of `updateSelfColor`. `color_index` is -1 when no anchor
  ## in the search window matched.
  %* {
    "updated": p.selfColorUpdated,
    "color_index": p.newSelfColor,
  }

proc crewmatesJson(p: gbActors.ActorPercept): JsonNode =
  ## List of crewmate match records emitted by `scanCrewmates`. Anchor
  ## `(x, y)` is the sprite's top-left corner; `color_index` is the
  ## dominant-tint slot in `PlayerColors[]` (`-1` if no tint pixels
  ## voted). Sorted in the order the upstream proc emits.
  result = newJArray()
  for m in p.crewmates:
    result.add(%* {
      "x": m.x, "y": m.y,
      "color_index": m.colorIndex,
      "flip_h": m.flipH,
    })

proc bodiesJson(p: gbActors.ActorPercept): JsonNode =
  ## List of body (dead crewmate) match records emitted by `scanBodies`.
  ## Bodies don't flip in-game, so no `flip_h` field.
  result = newJArray()
  for m in p.bodies:
    result.add(%* {
      "x": m.x, "y": m.y,
      "color_index": m.colorIndex,
    })

proc ghostsJson(p: gbActors.ActorPercept): JsonNode =
  ## List of ghost match records emitted by `scanGhosts`. Ghosts are
  ## translucent — no reliable colour extraction, only anchor + flip.
  result = newJArray()
  for m in p.ghosts:
    result.add(%* {
      "x": m.x, "y": m.y,
      "flip_h": m.flipH,
    })

proc radarDotsJson(frame: var seq[uint8]): JsonNode =
  ## List of deduped yellow radar dots in the screen-edge periphery
  ## ring, from upstream `tasks.scanRadarDots`. Independent of camera
  ## state — runs on every gameplay frame.
  result = newJArray()
  for d in gbTasks.scanRadarDots(frame):
    result.add(%* {"x": d.x, "y": d.y})

# ---------------------------------------------------------------------------
# Orchestrated outputs (v3)
# ---------------------------------------------------------------------------

proc interstitialKindToString(k: gbTypes.InterstitialKind): string =
  case k
  of gbTypes.NotInterstitial: "not_interstitial"
  of gbTypes.InterstitialUnknown: "unknown"
  of gbTypes.InterstitialRoleReveal: "role_reveal"
  of gbTypes.InterstitialRoleRevealCrewmate: "role_reveal_crewmate"
  of gbTypes.InterstitialRoleRevealImposter: "role_reveal_imposter"
  of gbTypes.InterstitialVoting: "voting"
  of gbTypes.InterstitialVoteResult: "vote_result"
  of gbTypes.InterstitialGameOver: "game_over"

proc interstitialJson(frame: var seq[uint8]): JsonNode =
  ## Result of upstream `interstitial.detectInterstitial`. Pure
  ## black-pixel count gate; never returns the role-reveal subtype
  ## variants at this layer (those come from OCR, S4.5).
  let obs = gbInterstitial.detectInterstitial(frame)
  %* {
    "is_interstitial": obs.isInterstitial,
    "kind": interstitialKindToString(obs.kind),
    "black_pixel_count": obs.blackPixelCount,
  }

# ---------------------------------------------------------------------------
# Fixture loader + per-fixture orchestrator
# ---------------------------------------------------------------------------

proc loadFixture(path: string): seq[uint8] =
  let raw = readFile(path)
  doAssert raw.len == FrameLen, &"fixture wrong length: {path} ({raw.len} bytes)"
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(raw[i])

proc processFixture(path: string): JsonNode =
  var frame = loadFixture(path)

  # Kernel-level outputs (v1-shape, widened to body + ghost in v2).
  let (spriteMatches, actorColorIndex) = kernelEntries(frame)

  # Orchestrated outputs (v2). Each fixture is treated as a fresh
  # first frame: no prior ghost-icon / kill-icon counters, role
  # starts at Unknown.
  var percept = gbActors.initActorPercept()
  var matchBuf: seq[uint8] = @[]
  var colorBuf: seq[int8] = @[]
  let sprites = gbData.sprites()
  gbActors.updateRole(
    percept,
    prevGhostIconFrames = 0,
    prevKillIconFrames = 0,
    prevRole = gbTypes.RoleUnknown,
    sprites = sprites,
    frame = frame,
  )
  gbActors.updateSelfColor(percept, sprites, frame)
  gbActors.scanBodies(percept, sprites, frame, matchBuf, colorBuf)
  gbActors.scanGhosts(percept, sprites, frame, matchBuf)
  gbActors.scanCrewmates(percept, sprites, frame, matchBuf, colorBuf)

  result = %* {
    "fixture": extractFilename(path),
    "schema_version": SchemaVersion,
    "frame_length": FrameLen,
    "screen_width": ScreenWidth,
    "screen_height": ScreenHeight,
    "sprite_matches": spriteMatches,
    "actor_color_index": actorColorIndex,
    "role": roleJson(percept),
    "self_color": selfColorJson(percept),
    "crewmates": crewmatesJson(percept),
    "bodies": bodiesJson(percept),
    "ghosts": ghostsJson(percept),
    "radar_dots": radarDotsJson(frame),
    "interstitial": interstitialJson(frame),
  }

proc main() =
  let here = currentSourcePath().parentDir()
  let fixturesDir = here.parentDir() / "fixtures"
  doAssert dirExists(fixturesDir), &"fixtures dir not found: {fixturesDir}"
  var count = 0
  for binPath in walkFiles(fixturesDir / "*.bin"):
    let outPath = binPath.changeFileExt("json")
    let payload = processFixture(binPath)
    writeFile(outPath, payload.pretty() & "\n")
    echo "wrote ", extractFilename(outPath)
    inc count
  echo &"oracle dumper finished: {count} sidecar(s)"

when isMainModule:
  main()
