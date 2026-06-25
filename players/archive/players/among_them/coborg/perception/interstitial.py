"""Interstitial detection. Port of
``users/james/personal_cogs/among_them/guided_bot/perception/interstitial.nim``.

Among Them's voting / role-reveal / vote-result / game-over screens
all paint a black background over most of the frame. Gameplay never
does — off-map pixels in gameplay are filled with ``MAP_VOID_COLOR``
(palette 12), not palette 0 black. A 30%-or-more-black-pixels test
cleanly separates the two without false positives from off-map
padding.

This module is intentionally a single-shot classifier: it says
"interstitial" or "gameplay" and reports the black-pixel count.
**It does not distinguish among interstitial subtypes** (role
reveal vs voting vs vote result vs game over). That refinement
comes from OCR in S4.5 and gets layered on top of this gate.

The companion ``phase_from_interstitial`` proc in the upstream Nim
lives in the belief layer; it isn't ported here because our belief
layer is P2 work, not perception.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from .frame import FRAME_LEN, black_pixel_count

# Threshold expressed as both a percentage (for documentation) and a
# pre-computed pixel count (for the actual comparison). The Nim source
# uses ceiling division so a fixture exactly at the boundary stays
# within budget; we mirror that.
INTERSTITIAL_BLACK_PERCENT: int = 30
INTERSTITIAL_BLACK_THRESHOLD: int = (INTERSTITIAL_BLACK_PERCENT * FRAME_LEN + 99) // 100


class InterstitialKind(Enum):
    """Mirrors upstream ``InterstitialKind`` in
    ``guided_bot/types.nim``. String values are the lowercase form
    the Nim oracle emits so sidecars are human-readable.

    :data:`NOT_INTERSTITIAL` and :data:`UNKNOWN` are the only two
    values :func:`detect_interstitial` ever returns — the rest are
    subtype refinements that land with OCR in S4.5+ (the belief layer
    upgrades :data:`UNKNOWN` to the right subtype once OCR reads the
    on-screen text)."""

    NOT_INTERSTITIAL = "not_interstitial"
    UNKNOWN = "unknown"
    ROLE_REVEAL = "role_reveal"
    ROLE_REVEAL_CREWMATE = "role_reveal_crewmate"
    ROLE_REVEAL_IMPOSTER = "role_reveal_imposter"
    VOTING = "voting"
    VOTE_RESULT = "vote_result"
    GAME_OVER = "game_over"


@dataclass
class InterstitialObservation:
    """Result of one :func:`detect_interstitial` call. Mirrors
    upstream ``InterstitialObservation``."""

    is_interstitial: bool
    kind: InterstitialKind
    black_pixel_count: int


def detect_interstitial(frame: np.ndarray) -> InterstitialObservation:
    """Classify a single unpacked frame as interstitial or gameplay.

    Pure black-pixel count threshold — no four-corner heuristic, no
    structural pattern matching. The 30% threshold is documented in
    ``bitworld/among_them/players/how_to_make_a_bot.md`` § "Interstitial
    Detection" as the post-2024 replacement for the older corner check
    that broke when chat text touched a corner.

    Returns :class:`InterstitialKind.UNKNOWN` for any black-enough
    frame; OCR (S4.5) refines that to the specific subtype.
    """
    count = black_pixel_count(frame)
    if count >= INTERSTITIAL_BLACK_THRESHOLD:
        return InterstitialObservation(
            is_interstitial=True,
            kind=InterstitialKind.UNKNOWN,
            black_pixel_count=count,
        )
    return InterstitialObservation(
        is_interstitial=False,
        kind=InterstitialKind.NOT_INTERSTITIAL,
        black_pixel_count=count,
    )
