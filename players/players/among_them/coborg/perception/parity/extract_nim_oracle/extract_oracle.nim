## Nim oracle dumper for the among-them-coborg perception parity rig.
##
## Walks every `.bin` fixture in `../fixtures/`, runs the upstream
## sprite-matching kernels against it, and writes a JSON sidecar next
## to each fixture (`gameplay_131.bin` -> `gameplay_131.json`). The
## Python parity harness in `perception/parity/run_parity.py` consumes
## those sidecars as the ground-truth oracle for the perception port.
##
## Scope (S2 first pass): sprite atlas index 0 (the player/crewmate
## sprite) only, both horizontal flips, crewmate scan budgets. S3
## widens to body and ghost sprites at their own budgets; S4 adds
## the HUD icons. Schema is versioned (`schema_version`) so widening
## is a non-breaking change.
##
## Self-contained: imports the upstream
## `users/james/personal_cogs/among_them/common/perception_kernels/`
## modules via the `--path` directive in `nim.cfg`, and embeds the
## upstream sprite atlas via `staticRead`. No `nimble`, no FFI, no
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
import common/perception_kernels/sprite_match as ksm

const
  ScreenWidth = 128
  ScreenHeight = 128
  FrameLen = ScreenWidth * ScreenHeight
  SpriteSize = 12
  SpriteCount = 6
  SchemaVersion = 1

  # Crewmate scan budgets, mirroring
  # users/james/personal_cogs/among_them/guided_bot/perception/actors.nim.
  CrewmateMaxMisses = 8
  CrewmateMinStable = 8
  CrewmateMinTint = 8

  # Sprite atlas order, parallel to indices 0..5. Pinned to
  # guided_bot/perception/data.nim's `loadSprites()` slot assignment.
  # snake_case names match coborg/perception/data/sprite_index.json.
  SpriteNames: array[SpriteCount, string] = [
    "player", "body", "ghost", "task", "kill_button", "ghost_icon"
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

proc loadFixture(path: string): seq[uint8] =
  let raw = readFile(path)
  doAssert raw.len == FrameLen, &"fixture wrong length: {path} ({raw.len} bytes)"
  result = newSeq[uint8](FrameLen)
  for i in 0 ..< FrameLen:
    result[i] = uint8(raw[i])

proc runOneFlip(
    frame: var seq[uint8],
    sprite: var array[SpriteSize * SpriteSize, uint8],
    flipH: cint,
): tuple[anchors, colorIndices: JsonNode] =
  ## Call both upstream kernels once for the given (sprite, flip) pair
  ## and build their JSON-serialisable outputs. Sharing the match mask
  ## between the two avoids a redundant second sweep and lets us trim
  ## the color-index output to only the meaningful anchor set.
  const maxY = ScreenHeight - SpriteSize + 1
  const maxX = ScreenWidth - SpriteSize + 1
  var matchMask = newSeq[uint8](maxY * maxX)
  ksm.mb_match_actor_sprite_all(
    cast[ptr UncheckedArray[uint8]](addr frame[0]),
    cast[ptr UncheckedArray[uint8]](addr sprite[0]),
    SpriteSize.cint, SpriteSize.cint, flipH,
    CrewmateMaxMisses.cint, CrewmateMinStable.cint, CrewmateMinTint.cint,
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

proc processFixture(path: string): JsonNode =
  var frame = loadFixture(path)
  var spriteMatches = newJArray()
  var actorColorIndex = newJArray()
  # S2 first pass: atlas index 0 (player) only, both flips, crewmate budgets.
  const spriteIdx = 0
  var sprite = spriteAt(spriteIdx)
  for flipH in [0.cint, 1.cint]:
    let (anchors, colors) = runOneFlip(frame, sprite, flipH)
    spriteMatches.add(%* {
      "sprite": SpriteNames[spriteIdx],
      "atlas_index": spriteIdx,
      "sh": SpriteSize,
      "sw": SpriteSize,
      "flip_h": flipH.int != 0,
      "max_misses": CrewmateMaxMisses,
      "min_stable": CrewmateMinStable,
      "min_tint": CrewmateMinTint,
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
  result = %* {
    "fixture": extractFilename(path),
    "schema_version": SchemaVersion,
    "frame_length": FrameLen,
    "screen_width": ScreenWidth,
    "screen_height": ScreenHeight,
    "sprite_matches": spriteMatches,
    "actor_color_index": actorColorIndex,
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
