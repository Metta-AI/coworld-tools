"""Make among_them_summarizer.py and the per-suite fixtures module
importable from the tests directory.

Two paths are added to sys.path:
  - the reporter source directory (parent of `tests/`), so
    `import among_them_summarizer` works;
  - the `tests/` directory itself, so tests can `import fixtures`
    without making `tests/` a Python package (which would collide
    with paint_arena_summarizer's `tests/__init__.py` under pytest's
    default conftest-loading behavior).
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_REPORTER_DIR = _TESTS_DIR.parent
for path in (_REPORTER_DIR, _TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
