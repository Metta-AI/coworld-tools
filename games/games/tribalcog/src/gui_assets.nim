## GUI asset filtering helpers.
## These helpers keep preload focused on gameplay sprite assets.

import
  std/[strutils]

const
  GuiAssetMaxEdge* = 256
    ## Maximum edge size for GUI preload assets.
  GuiAssetPngExtension = ".png"
  GuiAssetDataPrefix = "data/"
  GuiAssetSkipPrefixes* = [
    "df_view/",
    "tmp/",
  ]
  GuiAssetSkipPaths* = [
    "silky.atlas.png",
  ]

proc normalizeGuiAssetPath(path: string): string =
  ## Normalizes a GUI asset path to a data-relative slash path.
  result = path.replace('\\', '/')
  if result.startsWith("./"):
    result = result[2 .. ^1]
  if result.startsWith(GuiAssetDataPrefix):
    result = result[GuiAssetDataPrefix.len .. ^1]

proc shouldSkipGuiAsset(path: string): bool =
  ## Returns true when a normalized path is outside the preload set.
  for prefix in GuiAssetSkipPrefixes:
    if path.startsWith(prefix):
      return true
  for skippedPath in GuiAssetSkipPaths:
    if path == skippedPath:
      return true
  false

proc shouldPreloadGuiAsset*(path: string): bool =
  ## Returns true when GUI startup should preload the asset.
  let normalizedPath = normalizeGuiAssetPath(path)
  if not normalizedPath.endsWith(GuiAssetPngExtension):
    return false
  not shouldSkipGuiAsset(normalizedPath)

proc guiAssetKey*(path: string): string =
  ## Converts a data PNG path into the renderer image key.
  result = normalizeGuiAssetPath(path)
  if result.endsWith(GuiAssetPngExtension):
    result.setLen(result.len - GuiAssetPngExtension.len)
