from __future__ import annotations

from io import BytesIO
import json
import math
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

GRADER_ID = "default-grader"


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
        if not isinstance(manifest, dict):
            raise TypeError("bundle manifest.json must contain a JSON object")
        results = json.loads(bundle.read(bundle_file(manifest, "results", "results.json")))
    if not isinstance(results, dict):
        raise TypeError("results artifact must contain a JSON object")
    return results


def bundle_file(manifest: dict[str, object], token: str, fallback: str) -> str:
    files = manifest.get("files")
    if isinstance(files, dict) and isinstance(files.get(token), str):
        return files[token]
    return fallback


def default_interestingness(results: dict[str, object]) -> float:
    return round(normalized_spread(numeric_list(results.get("scores"))), 4)


def numeric_list(value: object) -> list[float]:
    if not isinstance(value, list):
        return []
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        number = float(item)
        if math.isfinite(number):
            numbers.append(number)
    return numbers


def normalized_spread(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    high = max(values)
    low = min(values)
    return clamp((high - low) / max(abs(high), abs(low), 1.0))


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def main() -> None:
    results = load_bundle_results(read_uri(os.environ["COGAME_EPISODE_BUNDLE_URI"]))
    score = default_interestingness(results)
    write_uri(os.environ["COGAME_GRADE_URI"], {"grader_id": GRADER_ID, "score": score})
    print(f"wrote default grade {score}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
