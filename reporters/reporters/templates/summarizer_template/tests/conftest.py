"""Make summarizer.py importable from the tests directory.

Mirrors the conftest pattern used by every concrete reporter in this repo
(see e.g. ``reporters/paint_arena/paint_arena_summarizer/tests/conftest.py``).
The reporter is not installed as a package; the tests just put its directory
on ``sys.path`` so ``import summarizer`` resolves.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPORTER_DIR = Path(__file__).resolve().parent.parent
if str(_REPORTER_DIR) not in sys.path:
    sys.path.insert(0, str(_REPORTER_DIR))
