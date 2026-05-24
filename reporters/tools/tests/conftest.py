"""Make ``validate_catalog`` importable from this tests directory.

Mirrors the conftest pattern used by every reporter in this repo
(see e.g. ``reporters/paint_arena/paint_arena_summarizer/tests/conftest.py``).
The validator is not installed as a package; the tests just put its
directory on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
