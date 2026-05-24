#!/usr/bin/env python3
"""Pack a minimal synthetic episode bundle zip for the default reporter's smoke run.

Usage:
    python make_bundle.py <out_path>

The default reporter only consumes ``results.json::scores``, so this
builder ships a tiny ``results`` payload with three slots. The bundle
schema matches metta's ``EPISODE_BUNDLE_README.md``: a root
``manifest.json`` declares ``include`` and maps tokens to in-zip paths.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <out_path>", file=sys.stderr)
        sys.exit(2)
    out_path = Path(sys.argv[1])

    manifest = {
        "ereq_id": "ereq_default_smoke_0001",
        "status": "success",
        "include": ["results"],
        "files": {"results": "results.json"},
    }
    # A trivial three-slot results.json. The default reporter renders one
    # line per slot in summary.md; the smoke test asserts the output is
    # non-empty and mentions the reporter id, not the specific scores,
    # so the exact values here are not load-bearing.
    results = {"scores": [1.0, 2.5, 0.0]}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("results.json", json.dumps(results))


if __name__ == "__main__":
    main()
