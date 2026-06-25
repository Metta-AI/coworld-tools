from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def read_uri(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        with urllib.request.urlopen(uri) as response:
            return response.read()
    path = Path(parsed.path if parsed.scheme == "file" else uri)
    return path.read_bytes()


def write_uri(uri: str, payload: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(
            uri,
            data=payload.encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "text/markdown; charset=utf-8"},
        )
        with urllib.request.urlopen(request) as response:
            response.read()
        return
    path = Path(parsed.path if parsed.scheme == "file" else uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def optional_json_env(name: str) -> dict[str, object] | None:
    if name not in os.environ:
        return None
    return json.loads(read_uri(os.environ[name]))


def target_slot() -> str:
    return os.environ["COGAME_TARGET_PLAYER_SLOT"] if "COGAME_TARGET_PLAYER_SLOT" in os.environ else "unspecified"


def diagnosis() -> str:
    policy_uri = os.environ["COGAME_POLICY_URI"]
    results = optional_json_env("COGAME_RESULTS_URI")
    manifest = optional_json_env("COGAME_MANIFEST_URI")
    lines = [
        "# Crewrift Policy Diagnosis",
        "",
        f"Policy: `{policy_uri}`",
        f"Target player slot: `{target_slot()}`",
        "",
        "## Assay Checklist",
        "",
        "- Verify the policy joins with the expected token and claims exactly one slot.",
        "- Compare task completion rate against the episode median.",
        "- Compare kill participation and survival time against role expectations.",
        "- Inspect report timing around bodies and emergency meetings.",
        "- Review voting behavior for missed obvious reports, self-votes, or repeated timeouts.",
        "- Check movement around vents, bodies, and task rooms from replay stats when available.",
    ]
    if results is not None:
        lines.extend(
            [
                "",
                "## Episode Results Snapshot",
                "",
                "```json",
                json.dumps(results, indent=2, sort_keys=True),
                "```",
            ]
        )
    if manifest is not None:
        game = manifest["game"]
        assert isinstance(game, dict)
        lines.extend(["", "## Coworld", "", f"Game: `{game['name']}`"])
    if "COGAME_REPLAY_STATS_PARQUET_URI" in os.environ:
        lines.extend(
            [
                "",
                "## Replay Stats",
                "",
                f"Stats parquet: `{os.environ['COGAME_REPLAY_STATS_PARQUET_URI']}`",
                "",
                "Use the parquet columns `ts`, `player`, `key`, and `value` to build concrete examples for the checklist above.",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    write_uri(os.environ["COGAME_DIAGNOSIS_OUTPUT_URI"], diagnosis())
    print("wrote Crewrift diagnosis", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
