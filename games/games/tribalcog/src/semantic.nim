## Semantic capture helpers for UI debugging.
## When enabled, these helpers emit a text tree of captured widgets.

import
  std/[strformat],
  vmath

const
  RootSemanticContext = ""

type
  SemanticWidgetKind* = enum
    WidgetButton
    WidgetLabel
    WidgetIcon
    WidgetPanel
    WidgetRect
    WidgetImage

  SemanticWidget* = object
    kind*: SemanticWidgetKind
    name*: string
    pos*: Vec2
    size*: Vec2
    parent*: string
      ## Parent context name for hierarchy grouping.

  SemanticContext* = object
    name*: string
    depth*: int

var
  semanticEnabled* = false
  capturedWidgets: seq[SemanticWidget]
  contextStack: seq[SemanticContext]
  currentContext = RootSemanticContext
  currentDepth = 0

proc resetSemanticState() =
  ## Resets all captured semantic state for a new capture session.
  capturedWidgets = @[]
  contextStack = @[]
  currentContext = RootSemanticContext
  currentDepth = 0

proc captureWidget(
  kind: SemanticWidgetKind,
  name: string,
  pos: Vec2,
  size: Vec2
) =
  ## Captures one widget when semantic capture is enabled.
  if not semanticEnabled:
    return
  capturedWidgets.add(SemanticWidget(
    kind: kind,
    name: name,
    pos: pos,
    size: size,
    parent: currentContext,
  ))

proc kindToString(kind: SemanticWidgetKind): string =
  ## Returns a stable display name for one widget kind.
  case kind
  of WidgetButton:
    "Button"
  of WidgetLabel:
    "Label"
  of WidgetIcon:
    "Icon"
  of WidgetPanel:
    "Panel"
  of WidgetRect:
    "Rect"
  of WidgetImage:
    "Image"

proc enableSemanticCapture*() =
  ## Enables semantic capture mode.
  semanticEnabled = true
  resetSemanticState()

proc beginSemanticFrame*() =
  ## Starts a new semantic frame and clears previous frame state.
  if not semanticEnabled:
    return
  resetSemanticState()

proc pushSemanticContext*(name: string) =
  ## Pushes one named context onto the semantic stack.
  if not semanticEnabled:
    return
  contextStack.add(SemanticContext(
    name: currentContext,
    depth: currentDepth,
  ))
  currentContext = name
  inc currentDepth

proc popSemanticContext*() =
  ## Pops the current semantic context from the stack.
  if not semanticEnabled or contextStack.len == 0:
    return
  let previous = contextStack.pop()
  currentContext = previous.name
  currentDepth = previous.depth

proc captureButton*(name: string, pos: Vec2, size: Vec2) =
  ## Captures one button widget.
  captureWidget(WidgetButton, name, pos, size)

proc captureLabel*(text: string, pos: Vec2, size: Vec2 = vec2(0, 0)) =
  ## Captures one label widget.
  captureWidget(WidgetLabel, text, pos, size)

proc capturePanel*(name: string, pos: Vec2, size: Vec2) =
  ## Captures one panel widget.
  captureWidget(WidgetPanel, name, pos, size)

proc endSemanticFrame*(frameNumber: int): string =
  ## Ends the frame and returns YAML-like output of captured widgets.
  if not semanticEnabled:
    return ""

  var output = &"Frame {frameNumber}:\n"
  var contexts: seq[string] = @[]

  for widget in capturedWidgets:
    if widget.parent notin contexts:
      contexts.add(widget.parent)

  for ctx in contexts:
    let contextName =
      if ctx.len == 0:
        "Root"
      else:
        ctx
    output.add(&"  {contextName}:\n")
    for widget in capturedWidgets:
      if widget.parent != ctx:
        continue
      let
        kindStr = kindToString(widget.kind)
        posX = widget.pos.x.int
        posY = widget.pos.y.int
        sizeW = widget.size.x.int
        sizeH = widget.size.y.int
      if widget.size.x > 0 and widget.size.y > 0:
        output.add(
          &"    - {kindStr} \"{widget.name}\" @ ({posX}, {posY}) " &
          &"{sizeW}x{sizeH}\n"
        )
      else:
        output.add(
          &"    - {kindStr} \"{widget.name}\" @ ({posX}, {posY})\n"
        )

  output
