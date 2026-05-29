from __future__ import annotations

from collections.abc import Callable, Iterable
from io import BytesIO
import json
import math
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse


JsonObject = dict[str, object]


def read_uri(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        with urllib.request.urlopen(uri) as response:
            return response.read()
    if parsed.scheme == "s3":
        return read_s3_uri(parsed.netloc, parsed.path)
    path = Path(unquote(parsed.path) if parsed.scheme == "file" else uri)
    return path.read_bytes()


def write_uri(uri: str, payload: JsonObject) -> None:
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


def load_bundle_results(bundle_content: bytes) -> JsonObject:
    artifacts = load_bundle_json_artifacts(bundle_content, ["results"])
    return artifacts["results"]


def load_bundle_json_artifacts(bundle_content: bytes, tokens: Iterable[str]) -> dict[str, JsonObject]:
    artifacts: dict[str, JsonObject] = {}
    with zipfile.ZipFile(BytesIO(bundle_content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        if not isinstance(manifest, dict):
            raise TypeError("bundle manifest.json must contain a JSON object")
        artifacts["manifest"] = manifest
        for token in tokens:
            artifact = json.loads(bundle.read(bundle_file(manifest, token, f"{token}.json")))
            if not isinstance(artifact, dict):
                raise TypeError(f"{token} artifact must contain a JSON object")
            artifacts[token] = artifact
    return artifacts


def bundle_file(manifest: JsonObject, token: str, fallback: str) -> str:
    files = manifest.get("files")
    if isinstance(files, dict) and isinstance(files.get(token), str):
        return files[token]
    return fallback


def run_grader(grader_id: str, scorer: Callable[[JsonObject], float], label: str) -> None:
    results = load_bundle_results(read_uri(os.environ["COGAME_EPISODE_BUNDLE_URI"]))
    score = round(clamp(float(scorer(results))), 4)
    write_uri(os.environ["COGAME_GRADE_URI"], {"grader_id": grader_id, "score": score})
    print(f"wrote {label} grade {score}", file=sys.stderr, flush=True)


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


def truthy_list(value: object) -> list[bool]:
    if not isinstance(value, list):
        return []
    flags: list[bool] = []
    for item in value:
        if isinstance(item, bool):
            flags.append(item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            flags.append(item != 0)
    return flags


def numeric_scalar(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def normalized_spread(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    high = max(values)
    low = min(values)
    return clamp((high - low) / max(abs(high), abs(low), 1.0))


def normalized_top_margin(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    ordered = sorted(values, reverse=True)
    return clamp((ordered[0] - ordered[1]) / max(abs(ordered[0]), abs(ordered[1]), 1.0))


def magnitude_signal(values: list[float], scale: float) -> float:
    if not values or scale <= 0:
        return 0.0
    mean_abs = sum(abs(value) for value in values) / len(values)
    return clamp(mean_abs / scale)


def scalar_signal(value: object, scale: float) -> float:
    number = numeric_scalar(value)
    if number is None or scale <= 0:
        return 0.0
    return clamp(number / scale)


def truthy_ratio(value: object) -> float:
    flags = truthy_list(value)
    if not flags:
        return 0.0
    return sum(1 for flag in flags if flag) / len(flags)


def mixed_flag_signal(value: object) -> float:
    flags = truthy_list(value)
    if len(flags) < 2:
        return 0.0
    return 1.0 if any(flags) and not all(flags) else 0.25


def numeric_leaf_sum(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else 0.0
    if isinstance(value, list):
        return sum(numeric_leaf_sum(item) for item in value)
    if isinstance(value, dict):
        return sum(numeric_leaf_sum(item) for item in value.values())
    return 0.0


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
