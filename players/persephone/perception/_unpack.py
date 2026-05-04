"""Frame unpacking: 8192 packed bytes -> (128, 128) uint8 array."""

from __future__ import annotations

import numpy as np

from ._common import PROTOCOL_BYTES, SCREEN_HEIGHT, SCREEN_WIDTH


def unpack_frame(data: bytes | bytearray | np.ndarray) -> np.ndarray:
    """Unpack a raw 8192-byte frame into a (128, 128) uint8 pixel array.

    Each input byte packs two 4-bit palette indices:
      - Low nibble (bits 0-3): left/even pixel
      - High nibble (bits 4-7): right/odd pixel

    Args:
        data: Raw frame bytes (must be exactly 8192 bytes).

    Returns:
        NumPy array of shape (128, 128), dtype uint8, values in [0, 15].

    Raises:
        ValueError: If data is not exactly 8192 bytes.
    """
    if isinstance(data, np.ndarray):
        raw = data.ravel()
    else:
        raw = np.frombuffer(data, dtype=np.uint8)

    if raw.size != PROTOCOL_BYTES:
        raise ValueError(
            f"Expected {PROTOCOL_BYTES} bytes, got {raw.size}"
        )

    # Unpack: low nibble = even pixels, high nibble = odd pixels
    pixels = np.empty(SCREEN_WIDTH * SCREEN_HEIGHT, dtype=np.uint8)
    pixels[0::2] = raw & 0x0F
    pixels[1::2] = raw >> 4

    return pixels.reshape((SCREEN_HEIGHT, SCREEN_WIDTH))
