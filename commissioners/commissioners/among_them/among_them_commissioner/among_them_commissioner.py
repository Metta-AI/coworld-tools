from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def write_uri(uri: str, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(
            uri,
            data=encoded,
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            response.read()
        return
    path = Path(parsed.path if parsed.scheme == "file" else uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def descriptor() -> dict[str, object]:
    return {
        "id": "among-them-commissioner",
        "commissioner_key": "among_them",
        "hosted_source": "app_backend/src/metta/app_backend/v2/commissioners.py",
        "responsibilities": [
            "schedule tournament episodes",
            "compute rankings from completed episodes",
            "move players between divisions",
            "place new players into initial divisions",
        ],
    }


def main() -> None:
    write_uri(os.environ["COGAME_COMMISSIONER_OUTPUT_URI"], descriptor())
    print("wrote Among Them commissioner descriptor", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
