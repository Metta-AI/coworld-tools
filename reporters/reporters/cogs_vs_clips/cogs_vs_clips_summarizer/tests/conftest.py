"""Make cogs_vs_clips_summarizer.py importable from this test directory."""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_REPORTER_DIR = _TESTS_DIR.parent
for path in (_REPORTER_DIR, _TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
