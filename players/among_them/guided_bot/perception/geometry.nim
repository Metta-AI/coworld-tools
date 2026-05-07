## Coordinate / camera math. Phase 1.2.
##
## Pure functions. Port of ``modulabot/geometry.py``. Two coordinate
## systems are in play:
##
## - **World** coordinates: pixel positions inside the 952×534 map.
##   Tasks, rooms, vents, the emergency button, and the home point all
##   live in world coordinates.
## - **Screen** coordinates: 128×128 with the player sprite's visual
##   centre at :data:`PlayerScreenX` / :data:`PlayerScreenY`. The
##   camera ``(x, y)`` is the world offset of the screen's top-left
##   pixel.
##
## The player's collision box is drawn at a small offset from the
## screen centre, so inferring world position from a locked camera is
## ``camera + PlayerWorldOff``.
##
## All procs here are pure: no module state, no allocation. They're
## hot in the localizer's local-refit and in every consumer that
## wants to convert between camera and world coords.

import ../constants
import data

const
  ## Screen-space anchor of the player sprite. The renderer centres
  ## the player and scrolls the map under them.
  PlayerScreenX* = ScreenWidth div 2
  PlayerScreenY* = ScreenHeight div 2

  ## World-space offset from the camera origin to the player's
  ## inferred collision-box centre. ``PlayerWorldOffX = SpriteDrawOffX
  ## + PlayerScreenX - SpriteSize div 2`` (and similarly for Y),
  ## verbatim from ``modulabot/geometry.py``.
  PlayerWorldOffX* =
    SpriteDrawOffX + PlayerScreenX - (SpriteSize div 2)
  PlayerWorldOffY* =
    SpriteDrawOffY + PlayerScreenY - (SpriteSize div 2)

# ---------------------------------------------------------------------------
# Camera bounds
# ---------------------------------------------------------------------------

proc minCameraX*(): int {.inline.} =
  -ScreenWidth div 2 - SpriteSize

proc maxCameraX*(): int {.inline.} =
  MapWidth - ScreenWidth div 2 + SpriteSize

proc minCameraY*(): int {.inline.} =
  -ScreenHeight div 2 - SpriteSize

proc maxCameraY*(): int {.inline.} =
  MapHeight - ScreenHeight div 2 + SpriteSize

proc cameraIndex*(x, y: int): int {.inline.} =
  ## Linear index into a (cameraH, cameraW) grid keyed on (cy, cx).
  ## Used by the localizer's vote accumulator.
  (y - minCameraY()) * (maxCameraX() - minCameraX() + 1) +
    (x - minCameraX())

proc cameraIndexX*(idx: int): int {.inline.} =
  minCameraX() + idx mod (maxCameraX() - minCameraX() + 1)

proc cameraIndexY*(idx: int): int {.inline.} =
  minCameraY() + idx div (maxCameraX() - minCameraX() + 1)

proc cameraWidth*(): int {.inline.} =
  maxCameraX() - minCameraX() + 1

proc cameraHeight*(): int {.inline.} =
  maxCameraY() - minCameraY() + 1

# ---------------------------------------------------------------------------
# Button / world helpers
# ---------------------------------------------------------------------------

proc clamp(v, lo, hi: int): int {.inline.} =
  if v < lo: lo elif v > hi: hi else: v

proc clamp(v, lo, hi: float): float {.inline.} =
  if v < lo: lo elif v > hi: hi else: v

proc buttonCameraX*(map: GameMap): int =
  ## Initial camera X guess centred on the emergency button. Clamped
  ## to the camera-range so off-edge buttons don't push the seed past
  ## the bounds.
  let target = map.button.x + map.button.w div 2 - PlayerWorldOffX
  clamp(target, minCameraX(), maxCameraX())

proc buttonCameraY*(map: GameMap): int =
  let target = map.button.y + map.button.h div 2 - PlayerWorldOffY
  clamp(target, minCameraY(), maxCameraY())

proc cameraXForWorld*(x: int): int =
  ## Camera X that puts world ``x`` on the player.
  clamp(x - PlayerWorldOffX, minCameraX(), maxCameraX())

proc cameraYForWorld*(y: int): int =
  clamp(y - PlayerWorldOffY, minCameraY(), maxCameraY())

proc inMap*(x, y: int): bool {.inline.} =
  x >= 0 and x < MapWidth and y >= 0 and y < MapHeight

proc cameraCanHoldPlayer*(cx, cy: int): bool {.inline.} =
  ## True when the camera puts the player's inferred world position
  ## inside the map rectangle. Filters out impossible candidates the
  ## patch-vote step would otherwise score.
  inMap(cx + PlayerWorldOffX, cy + PlayerWorldOffY)

# ---------------------------------------------------------------------------
# Player-from-camera helpers
# ---------------------------------------------------------------------------

proc playerWorldX*(cameraX: int): int {.inline.} =
  cameraX + PlayerWorldOffX

proc playerWorldY*(cameraY: int): int {.inline.} =
  cameraY + PlayerWorldOffY

# ---------------------------------------------------------------------------
# Room lookups
# ---------------------------------------------------------------------------

proc roomNameAt*(map: GameMap, x, y: int): string =
  ## Linear scan over the rooms list — there are ~30 rooms; not worth
  ## a spatial index. Returns ``"unknown"`` for points outside every
  ## room.
  for room in map.rooms:
    if x >= room.x and x < room.x + room.w and
       y >= room.y and y < room.y + room.h:
      return room.name
  "unknown"

proc visibleCrewmateWorldX*(cameraX, screenX: int): int {.inline.} =
  cameraX + screenX + SpriteDrawOffX

proc visibleCrewmateWorldY*(cameraY, screenY: int): int {.inline.} =
  cameraY + screenY + SpriteDrawOffY

proc heuristic*(ax, ay, bx, by: int): int {.inline.} =
  ## Manhattan distance — same name as in modulabot/geometry.py to
  ## keep consumers (A\*, sortBy distance) symmetrical.
  abs(ax - bx) + abs(ay - by)

# ---------------------------------------------------------------------------
# Task-station helpers (phase 6.1)
# ---------------------------------------------------------------------------

proc taskIconExpectedScreenPos*(station: TaskStation,
                                camX, camY: int): (int, int) =
  ## Expected screen position of the task icon for a station, given
  ## the current camera. The icon renders above the station rect
  ## centre. Mirrors ``modulabot/perception/pixel_pipeline.py``'s
  ## ``_task_icon_expected_pos``.
  let wx = station.x + station.w div 2
  let wy = station.y + station.h div 2
  let sx = wx - camX - SpriteDrawOffX
  let sy = wy - camY - SpriteDrawOffY
  (sx, sy)

proc taskIconOnScreen*(station: TaskStation,
                       camX, camY: int,
                       margin: int): bool =
  ## True when the task icon's expected position is fully inside the
  ## screen bounds with ``margin`` pixels of clearance on each edge.
  ## Used to gate icon-miss counting: we only count a miss when we're
  ## confident the icon *would* be visible if it existed.
  let (sx, sy) = taskIconExpectedScreenPos(station, camX, camY)
  # The icon sprite is SpriteSize x SpriteSize. Check that the full
  # sprite rect (anchored at sx, sy) is within the margin-inset screen.
  sx >= margin and
  sy >= margin and
  sx + SpriteSize <= ScreenWidth - margin and
  sy + SpriteSize <= ScreenHeight - margin

proc projectedRadarDot*(station: TaskStation,
                        camX, camY: int,
                        playerWx, playerWy: int): (int, int) =
  ## Where the server would draw a radar dot for this off-screen station.
  ## Uses ray-clip from player screen position to icon screen position,
  ## matching the server's projection algorithm faithfully.
  ## See pixel_pipeline.py:258-320 for the Python reference port.
  let iconSx = station.x + station.w div 2 - SpriteSize div 2 - camX
  let iconSy = station.y - SpriteSize - 2 - camY
  let iconX = iconSx + SpriteSize div 2
  let iconY = iconSy + SpriteSize div 2

  # If icon is on-screen, the server draws the icon, not a dot.
  # Caller should check taskIconOnScreen() first; this returns the
  # icon centre for convenience but it's not a dot position.
  if iconSx + SpriteSize > 0 and iconSy + SpriteSize > 0 and
     iconSx < ScreenWidth and iconSy < ScreenHeight:
    return (iconX, iconY)

  let px = float(playerWx - camX)
  let py = float(playerWy - camY)
  let dx = float(iconX) - px
  let dy = float(iconY) - py

  if abs(dx) < 0.5 and abs(dy) < 0.5:
    return (0, 0)

  var ex, ey: float
  if abs(dx) > abs(dy):
    ex = if dx > 0.0: float(ScreenWidth - 1) else: 0.0
    ey = py + dy * (ex - px) / dx
    ey = clamp(ey, 0.0, float(ScreenHeight - 1))
  else:
    ey = if dy > 0.0: float(ScreenHeight - 1) else: 0.0
    ex = px + dx * (ey - py) / dy
    ex = clamp(ex, 0.0, float(ScreenWidth - 1))
  (int(ex), int(ey))

proc projectedRadarDot*(station: TaskStation,
                        camX, camY: int): (int, int) {.deprecated.} =
  ## Backward-compatible wrapper for older callers that infer player
  ## position from the camera lock.
  projectedRadarDot(station, camX, camY,
                    playerWorldX(camX), playerWorldY(camY))
