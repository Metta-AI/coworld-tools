"""Make paint_arena_summarizer.py importable from the tests directory."""

from __future__ import annotations

import sys
from pathlib import Path

_REPORTER_DIR = Path(__file__).resolve().parent.parent
if str(_REPORTER_DIR) not in sys.path:
    sys.path.insert(0, str(_REPORTER_DIR))
