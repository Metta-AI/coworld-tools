"""Perception layer: observation → :class:`~modulabot.state.Perception`.

Two paths depending on what the cogames BitWorld shim feeds us:

- :mod:`modulabot.perception.state_obs` parses *structured* state
  observations (phase / header / grid / players / bodies / tasks).
  Preferred when available: we get high-signal features for free.
- :mod:`modulabot.perception.pixel_obs` falls back to pixel heuristics
  on the 128x128 4-bit indexed frame. Fewer signals, but still enough to
  move toward radar targets and detect interstitials.

The public entrypoint is :func:`update_perception`, which dispatches on the
observation shape and calls the appropriate backend. Everything else in this
package is internal.
"""

from .common import update_perception

__all__ = ["update_perception"]
