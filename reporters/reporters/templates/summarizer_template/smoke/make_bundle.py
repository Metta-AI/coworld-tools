#!/usr/bin/env python3
"""Pack a minimal synthetic episode bundle zip for the template's smoke run.

Usage:
    python make_bundle.py <out_path>

The template is game-agnostic and doesn't consume any bundle tokens, but
the canonical reporter contract still requires a real bundle zip on the
input side -- the SDK's BundleReader opens the zip and parses its inner
manifest.json. So this builder constructs a syntactically valid bundle
zip with a trivial `results` token, matching the schema in metta's
`EPISODE_BUNDLE_README.md`. A concrete reporter derived from this
template will typically replace this with the real fixtures its tests
exercise.
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
        "ereq_id": "ereq_template_smoke_0001",
        "status": "success",
        "include": ["results"],
        "files": {"results": "results.json"},
    }
    # Trivial results payload; the template ignores it.
    results = {"scores": [0.5, 0.5]}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("results.json", json.dumps(results))


if __name__ == "__main__":
    main()
