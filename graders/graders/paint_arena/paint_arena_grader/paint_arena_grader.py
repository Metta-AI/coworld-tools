from __future__ import annotations

from io import BytesIO
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

GRADER_ID = "paint-arena-grader"


def read_uri(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        with urllib.request.urlopen(uri) as response:
            return response.read()
    if parsed.scheme == "s3":
        return read_s3_uri(parsed.netloc, parsed.path)
    path = Path(unquote(parsed.path) if parsed.scheme == "file" else uri)
    return path.read_bytes()


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
    if parsed.scheme == "s3":
        write_s3_uri(parsed.netloc, parsed.path, encoded)
        return
    path = Path(unquote(parsed.path) if parsed.scheme == "file" else uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def read_s3_uri(bucket: str, key_path: str) -> bytes:
    if not bucket or not key_path.strip("/"):
        raise ValueError("s3 URI must include a bucket and key")
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("s3 URI support requires boto3") from exc

    response = boto3.client("s3").get_object(Bucket=bucket, Key=key_path.lstrip("/"))
    return response["Body"].read()


def write_s3_uri(bucket: str, key_path: str, content: bytes) -> None:
    if not bucket or not key_path.strip("/"):
        raise ValueError("s3 URI must include a bucket and key")
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("s3 URI support requires boto3") from exc

    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key_path.lstrip("/"),
        Body=content,
        ContentType="application/json",
    )


def load_bundle_artifacts(bundle_content: bytes) -> tuple[dict[str, object], dict[str, object]]:
    with zipfile.ZipFile(BytesIO(bundle_content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        if not isinstance(manifest, dict):
            raise TypeError("bundle manifest.json must contain a JSON object")
        results = json.loads(bundle.read(bundle_file(manifest, "results", "results.json")))
        replay = json.loads(bundle.read(bundle_file(manifest, "replay", "replay.json")))
    if not isinstance(results, dict):
        raise TypeError("results artifact must contain a JSON object")
    if not isinstance(replay, dict):
        raise TypeError("replay artifact must contain a JSON object")
    return results, replay


def bundle_file(manifest: dict[str, object], token: str, fallback: str) -> str:
    files = manifest.get("files")
    if isinstance(files, dict) and isinstance(files.get(token), str):
        return files[token]
    return fallback


def paintarena_interestingness(results: dict[str, object], replay: dict[str, object]) -> float:
    scores = numeric_list(results.get("scores"))
    if len(scores) < 2:
        return 0.0

    width, height = replay_dimensions(replay)
    max_margin = float(width * height)
    if max_margin <= 0:
        raise ValueError("PaintArena replay dimensions must define a positive board area")

    ordered = sorted(scores, reverse=True)
    margin = ordered[0] - ordered[1]
    return round(clamp(margin / max_margin), 4)


def replay_dimensions(replay: dict[str, object]) -> tuple[int, int]:
    config = replay.get("config")
    if not isinstance(config, dict):
        raise ValueError("PaintArena replay must include config.width and config.height")
    width = positive_int(config.get("width"), "config.width")
    height = positive_int(config.get("height"), "config.height")
    return width, height


def positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"PaintArena replay {field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"PaintArena replay {field_name} must be a positive integer")
    return value


def numeric_list(value: object) -> list[float]:
    if not isinstance(value, list):
        raise TypeError("PaintArena results.scores must be a list")
    scores: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise TypeError("PaintArena results.scores must contain only numbers")
        scores.append(float(item))
    return scores


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def main() -> None:
    results, replay = load_bundle_artifacts(read_uri(os.environ["COGAME_EPISODE_BUNDLE_URI"]))
    score = paintarena_interestingness(results, replay)
    write_uri(os.environ["COGAME_GRADE_URI"], {"grader_id": GRADER_ID, "score": score})
    print(f"wrote PaintArena grade {score}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
