"""``SceneState`` — the bridge-owned mutable view of the Sprite-v1 stream.

Per design §3 this is the lone non-pydantic SDK-facing type: a plain dataclass
holding the three retained tables (Layers/Sprites/Objects), the decoded camera,
and the walkability mask, which ``Observation`` references by pointer. Raw sprite
pixels never reach the strategy — only the ``walkability map`` alpha is retained.

Byte-level decoding lives in :mod:`players.crewrift.crewborg.perception.decoder`;
``apply`` delegates to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from players.crewrift.crewborg.perception.decoder import apply_message
from players.crewrift.crewborg.perception.tables import LayerDef, ObjectState, SpriteDef


@dataclass
class SceneState:
    """Mutable scene the bridge maintains as Sprite-v1 messages arrive."""

    # Bridge bookkeeping.
    tick: int = 0
    messages_applied: int = 0

    # Retained tables, keyed by their protocol ids.
    sprites: dict[int, SpriteDef] = field(default_factory=dict)
    objects: dict[int, ObjectState] = field(default_factory=dict)
    layers: dict[int, LayerDef] = field(default_factory=dict)

    # Camera recovered from the world-map object (id 1, sprite 1). World coords
    # are unavailable until it first arrives; degrade gracefully meanwhile.
    camera_ready: bool = False
    camera_x: int = 0
    camera_y: int = 0

    # Decoded walkability: a bool grid (alpha > 0 ⇒ walkable), or None until the
    # ``walkability map`` sprite has been defined.
    walkability: np.ndarray | None = None
    walkability_width: int = 0
    walkability_height: int = 0

    def apply(self, message: bytes) -> None:
        """Decode one incoming binary message into the scene tables.

        Raises ``SpriteProtocolError`` on malformed input (the bridge lets it
        propagate, closing the connection per the protocol).
        """

        self.messages_applied += 1
        apply_message(self, message)
