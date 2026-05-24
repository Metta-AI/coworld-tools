#!/usr/bin/env python3
"""Pack the loose smoke fixtures into a canonical episode bundle zip.

Usage:
    python make_bundle.py <out_path>

Reads `results.json`, `metadata.json`, and `replay.bitreplay` from
`fixtures/` next to this script, packs them into a bundle zip with an
inner `manifest.json` per metta `EPISODE_BUNDLE_README.md`. Used by
`smoke.sh` so the reporter can be exercised through
`COGAME_EPISODE_BUNDLE_URI` without committing the bundle as opaque bytes.

Note: the bundle's `files["replay"]` token maps to a path named
`replay.json` per the canonical bundle convention, even though the
bytes inside are the binary `.bitreplay` payload. The reporter's
`BundleReader.read_bytes("replay")` returns bytes either way, and Among
Them uses the binary format. Anyone opening the bundle in a file
browser will see `replay.json` and may be momentarily surprised; this
is documented in DESIGN.md.
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
    metadata = json.loads((fixtures / "metadata.json").read_text())
    replay_bytes = (fixtures / "replay.bitreplay").read_bytes()

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
        zf.writestr("replay.json", replay_bytes)
        zf.writestr("metadata.json", json.dumps(metadata))


if __name__ == "__main__":
    main()
