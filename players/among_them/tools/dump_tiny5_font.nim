## One-off helper to render tiny5.aseprite to a PNG for the Python port.
##
## Build & run:
##   cd ~/coding/bitworld
##   nim c -r --path:. --path:src \
##     /Users/jamesboggs/coding/personal_cogs/among_them/tools/dump_tiny5_font.nim \
##     <output_png>

import std/os
import pixie
import bitworld/aseprite

proc main() =
  if paramCount() < 1:
    echo "usage: dump_tiny5_font <output_png>"
    quit(1)
  let outPath = paramStr(1)
  let src = getHomeDir() / "coding" / "bitworld" / "among_them" / "tiny5.aseprite"
  if not fileExists(src):
    echo "tiny5.aseprite not found at ", src
    quit(1)
  let image = readAsepriteImage(src)
  writeFile(outPath, image.encodeImage(PngFormat))
  echo "wrote ", outPath, " (", image.width, "x", image.height, ")"

when isMainModule:
  main()
