#!/usr/bin/env python3
"""Pack the loose smoke fixtures into a canonical episode bundle zip.

Usage:
    python make_bundle.py <out_path>

Reads `results.json`, `replay.json`, and `metadata.json` from `fixtures/`
next to this script, packs them into a bundle zip with an inner
`manifest.json` per metta `EPISODE_BUNDLE_README.md`. Used by `smoke.sh`
so the reporter can be exercised through `COGAME_EPISODE_BUNDLE_URI`
without committing opaque binary fixtures.
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
    here = Path(__file__).resolve().parent
    fixtures = here / "fixtures"

    results = json.loads((fixtures / "results.json").read_text())
    replay = json.loads((fixtures / "replay.json").read_text())
    metadata = json.loads((fixtures / "metadata.json").read_text())

    manifest = {
        "ereq_id": "ereq_smoke_001",
        "status": "success",
        "include": ["results", "replay", "metadata"],
        "files": {
            "results": "results.json",
            "replay": "replay.json",
            "metadata": "metadata.json",
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("results.json", json.dumps(results))
        zf.writestr("replay.json", json.dumps(replay))
        zf.writestr("metadata.json", json.dumps(metadata))


if __name__ == "__main__":
    main()
