"""DEPRECATED entry point.

``maker_v1`` is deprecated. New agent-making work should target ``maker_v2``
under ``testbed/maker_v2/``. This script still runs the legacy pipeline for
short-term continuity but emits a deprecation banner. See
``docs/designs/maker_v1_deprecation.md``.
"""

from __future__ import annotations

import sys

from maker_v1.cli import main


if __name__ == "__main__":
    sys.exit(main())
