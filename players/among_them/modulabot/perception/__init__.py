"""Perception layer: observation → :class:`~modulabot.state.Perception`.

Three paths depending on what the cogames BitWorld shim feeds us:

- :mod:`modulabot.perception.pixel_pipeline` is the **production
  path**: full pixel perception (sprite matching, camera localization,
  voting parser, task-icon scanning, radar projection, icon-miss
  negative-evidence pruning). Runs whenever ``reference_data`` is
  available — i.e. always in tournament play where observations are
  ``(4, 128, 128) uint8 kind=pixels``.
- :mod:`modulabot.perception.state_obs` parses *structured* state
  observations (phase / header / grid / players / bodies / tasks).
  Used by the training-harness `BitWorldVecEnv` path; not exercised
  in tournament play. Kept for offline evaluation + tests.
- :mod:`modulabot.perception.pixel_obs` is a minimal pixel fallback
  for tests / sessions without ``reference_data`` (no sprite
  matching, no localization, just interstitial + radar centroid).

The public entrypoint is :func:`update_perception`
(:mod:`modulabot.perception.common`), which dispatches on observation
shape + the presence of ``reference_data``. Everything else in this
package is internal.
"""

from .common import update_perception

__all__ = ["update_perception"]
