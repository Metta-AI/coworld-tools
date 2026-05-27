from __future__ import annotations

from io import BytesIO
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

GRADER_ID = "among-them-grader"


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


def load_bundle_results(bundle_content: bytes) -> dict[str, object]:
    with zipfile.ZipFile(BytesIO(bundle_content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        results_path = "results.json"
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if isinstance(files, dict) and isinstance(files.get("results"), str):
            results_path = files["results"]
        results = json.loads(bundle.read(results_path))
    if not isinstance(results, dict):
        raise TypeError("results.json must contain a JSON object")
    return results


def values(results: dict[str, object], key: str) -> list[object]:
    value = results[key] if key in results else []
    if isinstance(value, list):
        return value
    return []


def interestingness(results: dict[str, object]) -> float:
    scores = [float(score) for score in values(results, "scores")]
    wins = [bool(win) for win in values(results, "win")]
    tasks = [int(task) for task in values(results, "tasks")]
    kills = [int(kill) for kill in values(results, "kills")]

    win_balance = 1.0 if any(wins) and not all(wins) else 0.25
    score_spread = (max(scores) - min(scores)) / max(abs(max(scores)), 1.0) if scores else 0.0
    task_signal = min(sum(tasks) / max(len(tasks), 1) / 8.0, 1.0) if tasks else 0.0
    kill_signal = min(sum(kills) / max(len(kills), 1), 1.0) if kills else 0.0
    return round(min(1.0, 0.35 * win_balance + 0.25 * score_spread + 0.25 * task_signal + 0.15 * kill_signal), 4)


def main() -> None:
    results = load_bundle_results(read_uri(os.environ["COGAME_EPISODE_BUNDLE_URI"]))
    score = interestingness(results)
    write_uri(os.environ["COGAME_GRADE_URI"], {"grader_id": GRADER_ID, "score": score})
    print(f"wrote Among Them grade {score}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
