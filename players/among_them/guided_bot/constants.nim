## Local game constants for guided_bot.
##
## Phase 0: self-contained. Values are copies of the BitWorld Among Them
## constants we'd otherwise import from `bitworld/common/protocol.nim` and
## `among_them/sim.nim`. Keeping them local lets the phase-0 skeleton
## compile without a configured bitworld checkout.
##
## Phase 1 (perception) will replace this file with proper bitworld imports
## and delete the duplicates. Anything added here now must also exist in
## the upstream headers; do not invent new constants.

const
  ## Screen dimensions (128 × 128 palette-indexed frame).
  ScreenWidth* = 128
  ScreenHeight* = 128
  FrameLen* = ScreenWidth * ScreenHeight

  ## Button-mask bits. Must match `common/protocol.nim` in bitworld.
  ButtonUp*     = 0b0000_0001'u8
  ButtonDown*   = 0b0000_0010'u8
  ButtonLeft*   = 0b0000_0100'u8
  ButtonRight*  = 0b0000_1000'u8
  ButtonSelect* = 0b0001_0000'u8
  ButtonA*      = 0b0010_0000'u8
  ButtonB*      = 0b0100_0000'u8

  ## Default WebSocket endpoint for the Among Them server (for the CLI
  ## entry point). Irrelevant in library builds.
  DefaultHost* = "localhost"
  DefaultPort* = 8080

  ## Palette size (4-bit indexed).
  PaletteSize* = 16

  ## Number of player colour slots. Shadows the BitWorld `PlayerColors.len`.
  PlayerColorCount* = 8
