import
  std/os,
  gui_assets

const
  PngHeaderSize = 24
  PngSignature = [
    char(0x89), 'P', 'N', 'G', '\r', '\n', char(0x1a), '\n'
  ]

proc readPngSize(path: string): tuple[width, height: int] =
  ## Read the PNG IHDR width and height from disk.
  var file: File
  if not open(file, path, fmRead):
    raise newException(IOError, "Could not open PNG: " & path)
  defer:
    file.close()
  var header: array[PngHeaderSize, char]
  let bytesRead = file.readChars(header.toOpenArray(0, header.high))
  if bytesRead != header.len:
    raise newException(IOError, "Incomplete PNG header: " & path)
  for i in 0 ..< PngSignature.len:
    if header[i] != PngSignature[i]:
      raise newException(ValueError, "Invalid PNG signature: " & path)
  if header[12] != 'I' or
     header[13] != 'H' or
     header[14] != 'D' or
     header[15] != 'R':
    raise newException(ValueError, "Missing IHDR chunk: " & path)
  result.width =
    (ord(header[16]) shl 24) or
    (ord(header[17]) shl 16) or
    (ord(header[18]) shl 8) or
    ord(header[19])
  result.height =
    (ord(header[20]) shl 24) or
    (ord(header[21]) shl 16) or
    (ord(header[22]) shl 8) or
    ord(header[23])

echo "Testing gameplay sprite GUI preloads"
doAssert shouldPreloadGuiAsset("data/house.png")
doAssert guiAssetKey("data/house.png") == "house"
doAssert guiAssetKey("data/oriented/monk.s.png") == "oriented/monk.s"

echo "Testing skipped df_view GUI exports"
doAssert not shouldPreloadGuiAsset("data/df_view/data/art/foo.png")
doAssert not shouldPreloadGuiAsset("df_view/data/art/foo.png")

echo "Testing skipped raw preview GUI assets"
doAssert not shouldPreloadGuiAsset("data/tmp/oriented/monk.e.png")
doAssert not shouldPreloadGuiAsset("tmp/oriented/monk.e.png")

echo "Testing skipped silky atlas preload"
doAssert not shouldPreloadGuiAsset("data/silky.atlas.png")
doAssert not shouldPreloadGuiAsset("silky.atlas.png")

echo "Testing GUI preload asset dimensions"
var checkedAssets = 0
for path in walkDirRec("data"):
  if not shouldPreloadGuiAsset(path):
    continue
  inc checkedAssets
  let
    (width, height) = readPngSize(path)
    sizeText = path & " is " & $width & "x" & $height
  doAssert width <= GuiAssetMaxEdge, sizeText
  doAssert height <= GuiAssetMaxEdge, sizeText
echo "Checked ", checkedAssets, " GUI preload assets"
