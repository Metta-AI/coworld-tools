## Unified text label rendering and caching.
##
## Provides one API for rendering text to images and caching them in the
## boxy atlas.

import
  std/tables,
  boxy, pixie, vmath,
  common, environment

const
  MeasureContextSize = 1
  ColorCacheScale = 255.0'f
  NoBackgroundAlpha = 0.0'f

type
  LabelStyle* = object
    fontPath*: string
    fontSize*: float32
    padding*: float32
    bgAlpha*: float32
    textColor*: Color
    outline*: bool
    outlineColor*: Color

  CachedLabel* = object
    imageKey*: string
    size*: IVec2

var
  labelCache: Table[string, CachedLabel] = initTable[string, CachedLabel]()

proc colorCacheSuffix(textColor: Color): string =
  ## Return the cache-key suffix for a non-default label color.
  let
    red = int(textColor.r * ColorCacheScale)
    green = int(textColor.g * ColorCacheScale)
    blue = int(textColor.b * ColorCacheScale)
  "_c" & $red & "_" & $green & "_" & $blue

proc labelStyle*(
  fontPath: string,
  fontSize: float32,
  padding: float32,
  bgAlpha: float32,
  textColor: Color = TintWhite,
  outline: bool = false
): LabelStyle =
  ## Return a label style with explicit text rendering settings.
  result = LabelStyle(
    fontPath: fontPath,
    fontSize: fontSize,
    padding: padding,
    bgAlpha: bgAlpha,
    textColor: textColor,
    outline: outline,
    outlineColor: TextOutlineColor,
  )

proc makeCacheKey*(prefix: string, text: string, style: LabelStyle): string =
  ## Build a cache key from the prefix, text, and style.
  result = prefix & "/" & text
  if style.textColor != TintWhite:
    result &= colorCacheSuffix(style.textColor)
  if style.fontSize != 0.0'f:
    result &= "_s" & $int(style.fontSize)

proc renderLabel(text: string, style: LabelStyle): (Image, IVec2) =
  ## Render text using the supplied style.
  var measureCtx = newContext(MeasureContextSize, MeasureContextSize)
  measureCtx.font = style.fontPath
  measureCtx.fontSize = style.fontSize
  measureCtx.textBaseline = TopBaseline
  let
    width = max(1, (measureCtx.measureText(text).width + style.padding * 2).int)
    height = max(1, (style.fontSize + style.padding * 2).int)
  var ctx = newContext(width, height)
  ctx.font = style.fontPath
  ctx.fontSize = style.fontSize
  ctx.textBaseline = TopBaseline

  # Fill the background when requested.
  if style.bgAlpha > NoBackgroundAlpha:
    ctx.fillStyle.color = withAlpha(LabelBgBlack, style.bgAlpha)
    ctx.fillRect(0, 0, width.float32, height.float32)

  # Draw the outline at eight offset positions.
  if style.outline:
    ctx.fillStyle.color = style.outlineColor
    for dx in -1 .. 1:
      for dy in -1 .. 1:
        if dx != 0 or dy != 0:
          ctx.fillText(
            text,
            vec2(
              style.padding + dx.float32,
              style.padding + dy.float32
            )
          )

  # Draw the main text.
  ctx.fillStyle.color = style.textColor
  ctx.fillText(text, vec2(style.padding, style.padding))
  result = (ctx.image, ivec2(width.int32, height.int32))

proc ensureLabel*(
  prefix: string,
  text: string,
  style: LabelStyle
): CachedLabel =
  ## Get or create a cached label and return its image key and size.
  let cacheKey = makeCacheKey(prefix, text, style)
  if cacheKey in labelCache:
    return labelCache[cacheKey]
  let
    (image, size) = renderLabel(text, style)
    cached = CachedLabel(imageKey: cacheKey, size: size)
  bxy.addImage(cacheKey, image)
  labelCache[cacheKey] = cached
  result = cached

proc ensureLabelKeyed*(
  cacheKey: string,
  imageKey: string,
  text: string,
  style: LabelStyle
): CachedLabel =
  ## Get or create a cached label with explicit cache and image keys.
  if cacheKey in labelCache:
    return labelCache[cacheKey]
  let
    (image, size) = renderLabel(text, style)
    cached = CachedLabel(imageKey: imageKey, size: size)
  bxy.addImage(imageKey, image)
  labelCache[cacheKey] = cached
  result = cached

proc invalidateLabel*(cacheKey: string) =
  ## Remove one cached label entry.
  labelCache.del(cacheKey)
