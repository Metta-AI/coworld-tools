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
##   stamps) extends v3 with `ignore_phase_1_0`.
## - v4 (S4.3): adds upstream localize kernel + orchestrator outputs:
##   `score_camera_probes` (per-fixture at canonical seeds),
##   `frame_patch_hashes` (16x16 grid of FNV hashes), `patch_vote_top_candidates`
##   (top-16 from the vote kernel), `localize_first_frame` (result of
##   `updateLocation` starting from a fresh state).
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

# Upstream ignore-mask builder — used for v3 outputs (additive within v3).
import guided_bot/perception/ignore as gbIgnore
import guided_bot/perception/frame as gbFrame

# Upstream localize + geometry — used for v4 outputs.
import guided_bot/perception/localize as gbLocalize
import guided_bot/perception/geometry as gbGeometry

import std/sha1
import std/strutils

const
  ScreenWidth = 128
  ScreenHeight = 128
  FrameLen = ScreenWidth * ScreenHeight
  SpriteSize = 12
  SpriteCount = 6
  SchemaVersion = 4

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


proc maskSha1Hex(data: seq[uint8]): string =
  ## SHA-1 over the raw 16384 bytes of an IgnoreMask. Encodes the
  ## full mask as a 40-char hex string so the Python parity rig can
  ## assert byte-exact equality without round-tripping ~16 KB of
  ## boolean data through JSON.
  var s = newString(data.len)
  if data.len > 0:
    copyMem(addr s[0], unsafeAddr data[0], data.len)
  $secureHash(s)


proc ignorePhase10Json(frame: var seq[uint8]): JsonNode =
  ## Result of upstream `ignore.buildPhase10IgnoreMask`. The Python
  ## sidecar consumer compares both fields: `stamped_pixel_count`
  ## is the human-readable summary; `sha1` is the exact-equality
  ## fingerprint over all 16384 mask bytes (0/1 per pixel,
  ## row-major).
  var mask = gbFrame.initIgnoreMask()
  gbIgnore.buildPhase10IgnoreMask(mask, frame)
  %* {
    "stamped_pixel_count": gbFrame.countSet(mask),
    "sha1": maskSha1Hex(mask.data),
  }


# ---------------------------------------------------------------------------
# Orchestrated outputs (v4) — localize
# ---------------------------------------------------------------------------

proc lockToString(lock: gbTypes.CameraLock): string =
  case lock
  of gbTypes.NoLock: "no_lock"
  of gbTypes.LocalFrameMapLock: "local_frame_map_lock"
  of gbTypes.FrameMapLock: "frame_map_lock"
  else: "no_lock"

proc scoreCameraProbesJson(frame: var seq[uint8], ignoreMaskData: seq[uint8]): JsonNode =
  ## Score the upstream `scoreCamera` kernel at a deterministic set of
  ## probe positions per fixture. Probes are chosen for coverage:
  ## (0, 0) at the map origin, the button-camera seed, a negative
  ## offset, and a deep-positive offset. Each emits
  ## ``{cam_x, cam_y, score, errors, compared}``.
  result = newJArray()
  let mapPixels = gbData.referenceData.map.mapPixels
  let probes: seq[(int, int)] = @[
    (0, 0),
    (gbGeometry.buttonCameraX(gbData.referenceData.map),
     gbGeometry.buttonCameraY(gbData.referenceData.map)),
    (-50, -50),
    (400, 250),
  ]
  for (cx, cy) in probes:
    let sc = gbLocalize.scoreCamera(
      frame, mapPixels, ignoreMaskData, cx, cy,
      gbLocalize.FullFrameFitMaxErrors)
    result.add(%* {
      "cam_x": cx,
      "cam_y": cy,
      "score": sc.score,
      "errors": sc.errors,
      "compared": sc.compared,
    })

proc framePatchHashesJson(frame: var seq[uint8], ignoreMaskData: seq[uint8]): JsonNode =
  ## Full 256-entry grid from upstream `hashFramePatches`. Hashes are
  ## emitted as 16-char hex strings (uppercase, no `0x`) so JSON-side
  ## uint64 round-tripping is unambiguous; validity is a parallel bool
  ## array.
  let (hashes, valid) = gbLocalize.hashFramePatches(frame, ignoreMaskData)
  var hashJson = newJArray()
  var validJson = newJArray()
  for i in 0 ..< gbLocalize.PatchTotalCount:
    hashJson.add(%* toHex(hashes[i].uint64, 16))
    validJson.add(%* (valid[i] != 0'u8))
  %* {"hashes": hashJson, "valid": validJson}

proc patchVoteTopCandidatesJson(
    frame: var seq[uint8], ignoreMaskData: seq[uint8]): JsonNode =
  ## Top-K output of upstream `voteCameraCandidates`. Each entry is
  ## ``{cam_x, cam_y, votes}`` in descending vote order with ties
  ## broken by ascending ``(cy, cx)``.
  let (hashes, valid) = gbLocalize.hashFramePatches(frame, ignoreMaskData)
  var votesScratch: seq[uint16] = @[]
  let cands = gbLocalize.voteCameraCandidates(
    hashes, valid, gbLocalize.getPatchIndex(), votesScratch)
  result = newJArray()
  for c in cands:
    result.add(%* {"cam_x": c.cx, "cam_y": c.cy, "votes": c.votes})

proc localizeFirstFrameJson(
    frame: var seq[uint8], ignoreMaskData: seq[uint8],
    outState: var gbTypes.PerceptionState): JsonNode =
  ## Result of one `updateLocation` call starting from a fresh
  ## PerceptionState (no prior lock). Tick is fixed at 0. The seven
  ## fields emitted are the camera-related subset the Python state
  ## also tracks. ``outState`` is populated as a side effect so the
  ## task-icon scan can reuse the same camera offset without
  ## re-running localize.
  var loc = gbLocalize.initLocalizer()
  gbLocalize.updateLocation(loc, outState, frame, ignoreMaskData, 0)
  %* {
    "camera_x": outState.cameraX,
    "camera_y": outState.cameraY,
    "camera_score": outState.cameraScore,
    "camera_lock": lockToString(outState.cameraLock),
    "localized": outState.localized,
    "self_x": outState.selfX,
    "self_y": outState.selfY,
  }


proc taskIconsJson(
    frame: var seq[uint8],
    locState: gbTypes.PerceptionState): JsonNode =
  ## Result of upstream `tasks.scanTaskIcons` at the camera offset
  ## found by `updateLocation`. Returns an empty list when localization
  ## failed (the production code path does the same gating).
  result = newJArray()
  if not locState.localized:
    return
  let sprite = gbData.referenceData.sprites.task
  for m in gbTasks.scanTaskIcons(
      frame, sprite, locState.cameraX, locState.cameraY):
    result.add(%* {"x": m.x, "y": m.y})

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
    "ignore_phase_1_0": ignorePhase10Json(frame),
  }

  # v4 (S4.3) localize fields. The localize kernels need the phase-1.0
  # ignore mask, so we build it once here and feed the raw data buffer
  # to the v4 emitters (they all consume `openArray[uint8]`).
  var ignoreMask = gbFrame.initIgnoreMask()
  gbIgnore.buildPhase10IgnoreMask(ignoreMask, frame)
  result["score_camera_probes"] = scoreCameraProbesJson(frame, ignoreMask.data)
  result["frame_patch_hashes"] = framePatchHashesJson(frame, ignoreMask.data)
  result["patch_vote_top_candidates"] = patchVoteTopCandidatesJson(frame, ignoreMask.data)

  # localize_first_frame populates `locState` as a side effect; the
  # subsequent task-icon scan reads the camera offset from it.
  var locState: gbTypes.PerceptionState
  result["localize_first_frame"] = localizeFirstFrameJson(
    frame, ignoreMask.data, locState)
  # v4 (S4.4) task-icon field — additive within v4 (no schema bump).
  result["task_icons"] = taskIconsJson(frame, locState)

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
