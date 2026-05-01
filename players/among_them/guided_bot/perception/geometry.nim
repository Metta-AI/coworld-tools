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
