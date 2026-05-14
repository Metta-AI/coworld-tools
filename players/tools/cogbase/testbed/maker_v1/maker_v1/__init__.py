"""DEPRECATED: ``maker_v1`` is the deprecated first-generation agent-making
toolkit for Cogbase. New work should target ``maker_v2`` under
``testbed/maker_v2/``. See ``docs/designs/maker_v1_deprecation.md`` for the
rationale and ``docs/designs/maker_v2_design.md`` for the replacement
direction.

This package is preserved for short-term continuity. It still runs, but it is
not receiving new features and its entry points emit ``DeprecationWarning``.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "maker_v1 is deprecated; new work should go into maker_v2 "
    "(testbed/maker_v2/). See docs/designs/maker_v1_deprecation.md.",
    DeprecationWarning,
    stacklevel=2,
)

from .bootstrap import BootstrapResult, run_visual_bootstrap
from .build_plan import MakerResult, generate_plan
from .guide_index import ObservationSurface, classify_observation_surface, load_guide_bundle
from .policy_builder import PolicyBuildResult, build_policy_from_labels
from .smoke import SmokeResult, run_smoke_test

__all__ = [
    "MakerResult",
    "ObservationSurface",
    "BootstrapResult",
    "PolicyBuildResult",
    "SmokeResult",
    "classify_observation_surface",
    "generate_plan",
    "build_policy_from_labels",
    "load_guide_bundle",
    "run_visual_bootstrap",
    "run_smoke_test",
]
