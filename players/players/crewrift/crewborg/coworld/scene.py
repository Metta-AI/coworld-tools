"""``SceneState`` — the bridge-owned mutable view of the Sprite-v1 stream.

Per design §3 this is the lone non-pydantic SDK-facing type: a plain dataclass
holding the retained scene (and, from P1, the decoded camera and walkability
mask) that ``Observation`` references by pointer. Raw buffers live here and
never reach the strategy.

**P0 scope.** The full three-table decoder (Layers/Sprites/Objects, design §3.1)
lands in P1. P0 keeps only the counters needed to drive and observe the tick
loop; ``apply`` is a placeholder that records that a message arrived.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SceneState:
    """Mutable scene the bridge maintains as Sprite-v1 messages arrive."""

    tick: int = 0
    messages_applied: int = 0
    last_message_len: int = 0

    def apply(self, message: bytes) -> None:
        """Fold one incoming binary message into the scene.

        P0 only records arrival; P1 decodes the message into the object/sprite/
        layer tables (design §3.1).
        """

        self.messages_applied += 1
        self.last_message_len = len(message)
