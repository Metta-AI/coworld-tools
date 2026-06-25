"""Binary raw-frame recorder for Eurydice policy runs."""

from __future__ import annotations

from pathlib import Path
import struct
from typing import BinaryIO


class FrameRecorder:
    """Append raw WebSocket frames with a compact tick/length prefix."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file: BinaryIO | None = self.path.open("wb")

    def record(self, tick: int, raw_bytes: bytes) -> None:
        """Write one frame record: tick, byte length, and raw frame bytes."""

        if self._file is None:
            return
        self._file.write(struct.pack("<II", int(tick), len(raw_bytes)))
        self._file.write(raw_bytes)

    def close(self) -> None:
        """Flush and close the recorder file. Safe to call more than once."""

        if self._file is None:
            return
        self._file.flush()
        self._file.close()
        self._file = None


__all__ = ["FrameRecorder"]
