"""Entry point for ``maker_v2``.

``maker_v2`` is the canonical successor to the deprecated ``maker_v1``
toolkit. This script currently runs a CLI stub that prints a "not yet
implemented" message; generation slices will land incrementally. See
``docs/designs/maker_v2_design.md`` for the direction.
"""

from __future__ import annotations

import sys

from maker_v2.cli import main


if __name__ == "__main__":
    sys.exit(main())
