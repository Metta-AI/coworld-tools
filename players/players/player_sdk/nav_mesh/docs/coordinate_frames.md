# Coordinate frames: measure in the engine's collision frame

**Read this before writing world-model positions or any range/proximity check
for a continuous/pixel world.**

The general lesson: engines measure gameplay ranges (attack range, report
range, "who is near me") at each agent's **collision point** — but the
observation stream usually gives you sprite *draw* positions, which are offset
from it. If a policy measures distances in the draw frame, **every**
me↔other distance is shifted by a constant vector. A shift of even a few
pixels is enough to make an in-range action read as out-of-range (and
vice-versa), and to make your own avatar appear as a phantom "other" standing
a few pixels away instead of at 0.

## The worked case: crewrift's (7,7) gotcha

In the game this library was extracted from (crewrift, on the bitworld
engine), the constant error was **(7, 7) px ≈ 9.9 px** — half of the 20 px
kill range:

- **Others (and bodies).** The engine drew another player's sprite at
  `other.x - SpriteDrawOffX - 1`, `other.y - SpriteDrawOffY - 1`
  (`SpriteDrawOffX = 2`, `SpriteDrawOffY = 8`), so the streamed position sat
  **(3, 9) px** away from the true collision point.
- **Self (the focal player).** The self position derived from the camera was
  the sprite **centre**, sitting `(-4, 2)` from the collision point.

The fix was to normalize *everything* into the collision frame at the
world-model boundary (the reader added the offsets back as it parsed), so
policy code could compare coordinates directly:

```python
me = world.me_collision                     # NOT the draw/camera position
for actor in world.others:                  # already collision-frame
    dx = actor.x - me[0]
    dy = actor.y - me[1]
    if dx * dx + dy * dy <= KILL_RANGE_PX ** 2:
        ...                                 # exact against the engine
```

With everything in one frame, your own avatar resolves to ~0 px (so it is
reliably dropped as "me"), and range checks line up with what the engine sees.

## How to apply it to a new game

1. Find the engine's authoritative collision/interaction point (source, docs,
   or empirically: walk into a wall and compare the streamed position against
   where the engine stops you — `nav_mesh.NavGrid` + the `simulation`
   physics oracle make that experiment cheap).
2. Measure the constant offsets between each streamed position kind (self,
   others, static objects) and that point.
3. Normalize at the observation boundary — the code that builds your world
   snapshot adds the offsets — so nothing downstream ever mixes frames.
4. Feed `NavState.heading(..., collision=...)` the collision point too: the
   wall-probe dodge samples the walkability grid from there.

## Why this class of bug hides

An "I chose to act" trace measures *intent*, not the engine's outcome — a
constant frame error produces perfectly reasonable-looking intent traces
while the engine silently refuses every action. If actions never land despite
point-blank readings, suspect the frame first: check that the self resolves
to ~0 px and that distances use the collision point.

---

Origin: generalized from swgy-crewrift's `docs/COORDINATE_FRAMES.md`
(Ron Dahlgren / swgy), where the (7,7) incident was diagnosed.
