"""PaintArena summarizer reporter.

Pure function of (results JSON, episode metadata JSON, manifest JSON) that
produces a JSON envelope with two artifacts: a Markdown summary and a JSON
stats blob. See DESIGN.md for the full specification.

The inline primitives in this file (ReporterInputs, read_uri/write_uri,
Envelope/Artifact, validate_envelope, lookup_variant) are SDK extraction
candidates -- once a second reporter exists, they'll be lifted into
reporter_sdk and this file will import them instead.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

# ---------- inline primitives (SDK extraction candidates) ----------

REQUIRED_ENV_VARS = (
    "COGAME_RESULTS_URI",
    "COGAME_EPISODE_METADATA_URI",
    "COGAME_MANIFEST_URI",
    "COGAME_REPORT_OUTPUT_URI",
    "COGAME_REPORTER_ID",
)


@dataclass(frozen=True)
class ReporterInputs:
    results_uri: str
    episode_metadata_uri: str
    manifest_uri: str
    report_output_uri: str
    reporter_id: str


def load_reporter_inputs(env: "os._Environ[str] | dict[str, str] | None" = None) -> ReporterInputs:
    e = os.environ if env is None else env
    missing = [k for k in REQUIRED_ENV_VARS if not e.get(k)]
    if missing:
        raise KeyError(f"missing required env vars: {', '.join(missing)}")
    return ReporterInputs(
        results_uri=e["COGAME_RESULTS_URI"],
        episode_metadata_uri=e["COGAME_EPISODE_METADATA_URI"],
        manifest_uri=e["COGAME_MANIFEST_URI"],
        report_output_uri=e["COGAME_REPORT_OUTPUT_URI"],
        reporter_id=e["COGAME_REPORTER_ID"],
    )


_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}
_HTTP_MAX_ATTEMPTS = 5


def _file_path_from_uri(uri: str) -> Path:
    parsed = urllib.parse.urlparse(uri)
    return Path(urllib.parse.unquote(parsed.path))


def read_uri(uri: str) -> bytes:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        return _file_path_from_uri(uri).read_bytes()
    if scheme in ("http", "https"):
        return _http_request_with_retry("GET", uri).content
    raise ValueError(f"unsupported URI scheme {scheme!r} for read: {uri}")


def write_uri(uri: str, payload: bytes, content_type: str) -> None:
    scheme = urllib.parse.urlparse(uri).scheme.lower()
    if scheme == "file":
        path = _file_path_from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return
    if scheme in ("http", "https"):
        _http_request_with_retry(
            "PUT", uri, data=payload, headers={"Content-Type": content_type}
        )
        return
    raise ValueError(f"unsupported URI scheme {scheme!r} for write: {uri}")


def _http_request_with_retry(
    method: str,
    uri: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    delay = 0.5
    for attempt in range(1, _HTTP_MAX_ATTEMPTS + 1):
        resp = requests.request(method, uri, data=data, headers=headers, timeout=30)
        if resp.status_code < 400:
            return resp
        if resp.status_code not in _HTTP_RETRY_STATUSES or attempt == _HTTP_MAX_ATTEMPTS:
            resp.raise_for_status()
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    raise RuntimeError("unreachable")  # loop above either returns or raises


def read_json(uri: str) -> Any:
    return json.loads(read_uri(uri).decode("utf-8"))


@dataclass(frozen=True)
class Artifact:
    id: str
    content_type: str
    content: Any
    encoding: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "content_type": self.content_type}
        if self.encoding is not None:
            d["encoding"] = self.encoding
        d["content"] = self.content
        return d


@dataclass(frozen=True)
class Envelope:
    version: str
    artifacts: list[Artifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "artifacts": [a.to_dict() for a in self.artifacts]}

    def to_json_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True).encode("utf-8")



_FIRST_CLASS_TEXT_TYPES = {"text/markdown", "text/plain", "application/json"}


def validate_envelope(envelope: dict[str, Any]) -> None:
    """Structural D3 check. Not a full JSON-Schema validator."""
    if not isinstance(envelope, dict):
        raise ValueError("envelope must be an object")
    if envelope.get("version") != "1":
        raise ValueError("envelope.version must be the string '1'")
    artifacts = envelope.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("envelope.artifacts must be a list")
    seen_ids: set[str] = set()
    for i, art in enumerate(artifacts):
        if not isinstance(art, dict):
            raise ValueError(f"artifact[{i}] must be an object")
        for key in ("id", "content_type"):
            if key not in art:
                raise ValueError(f"artifact[{i}] missing required field {key!r}")
        if "content" not in art:
            raise ValueError(f"artifact[{i}] missing required field 'content'")
        if not isinstance(art["id"], str) or not art["id"]:
            raise ValueError(f"artifact[{i}].id must be a non-empty string")
        if art["id"] in seen_ids:
            raise ValueError(f"duplicate artifact id {art['id']!r}")
        seen_ids.add(art["id"])
        if not isinstance(art["content_type"], str) or "/" not in art["content_type"]:
            raise ValueError(f"artifact[{i}].content_type must be a media-type string")


def lookup_variant(manifest: dict[str, Any], variant_id: str) -> dict[str, Any]:
    variants = manifest.get("variants") or []
    for v in variants:
        if v.get("id") == variant_id:
            return v
    raise KeyError(f"variant_id {variant_id!r} not found in manifest.variants")


# ---------- PaintArena-specific logic ----------

_REQUIRED_RESULTS_FIELDS = ("scores", "painted_tiles", "ticks")


def _validate_results(results: dict[str, Any]) -> None:
    if not isinstance(results, dict):
        raise ValueError("results JSON must be an object")
    missing = [f for f in _REQUIRED_RESULTS_FIELDS if f not in results]
    if missing:
        raise ValueError(f"results missing required field(s): {', '.join(missing)}")
    if not isinstance(results["painted_tiles"], list) or not all(
        isinstance(x, int) and x >= 0 for x in results["painted_tiles"]
    ):
        raise ValueError("results.painted_tiles must be a list of non-negative integers")
    if not isinstance(results["ticks"], int) or results["ticks"] < 0:
        raise ValueError("results.ticks must be a non-negative integer")


def _policy_name_for_slot(metadata: dict[str, Any], slot: int) -> str:
    for entry in metadata.get("players") or []:
        if entry.get("slot") == slot:
            name = entry.get("policy_name")
            if isinstance(name, str) and name:
                return name
            break
    return f"Slot {slot}"


def build_stats(
    results: dict[str, Any],
    metadata: dict[str, Any],
    variant: dict[str, Any],
) -> dict[str, Any]:
    _validate_results(results)
    game_config = variant.get("game_config") or {}
    width = int(game_config["width"])
    height = int(game_config["height"])
    total_tiles = width * height

    painted: list[int] = list(results["painted_tiles"])
    slots: list[dict[str, Any]] = []
    for i, count in enumerate(painted):
        share = (count / total_tiles * 100.0) if total_tiles > 0 else 0.0
        slots.append(
            {
                "slot": i,
                "policy_name": _policy_name_for_slot(metadata, i),
                "painted_tiles": int(count),
                "share_pct": round(share, 2),
            }
        )

    total_painted = sum(painted)
    unpainted = max(total_tiles - total_painted, 0)
    unpainted_share = (unpainted / total_tiles * 100.0) if total_tiles > 0 else 0.0

    # Winner / tie computation.
    if total_painted == 0:
        winner_slot: int | None = None
        margin = 0
        tie = False
    else:
        max_count = max(painted)
        leaders = [i for i, c in enumerate(painted) if c == max_count]
        if len(leaders) > 1:
            winner_slot = None
            margin = 0
            tie = True
        else:
            winner_slot = leaders[0]
            others = [c for i, c in enumerate(painted) if i != winner_slot]
            margin = max_count - max(others) if others else max_count
            tie = False

    return {
        "episode_id": metadata.get("episode_id"),
        "variant_id": metadata.get("variant_id"),
        "grid": {"width": width, "height": height, "total_tiles": total_tiles},
        "ticks": int(results["ticks"]),
        "duration_seconds": metadata.get("duration_seconds"),
        "slots": slots,
        "unpainted_tiles": int(unpainted),
        "unpainted_share_pct": round(unpainted_share, 2),
        "winner_slot": winner_slot,
        "margin_tiles": int(margin),
        "tie": tie,
    }



def _format_duration(stats: dict[str, Any]) -> str:
    dur = stats.get("duration_seconds")
    ticks = stats.get("ticks")
    if isinstance(dur, (int, float)):
        return f"{dur:.1f} s ({ticks} ticks)"
    return f"{ticks} ticks"


def render_summary_markdown(stats: dict[str, Any]) -> str:
    grid = stats["grid"]
    lines: list[str] = []
    lines.append(f"# PaintArena \u2014 Episode {stats.get('episode_id') or 'unknown'}")
    lines.append("")
    lines.append(
        f"**Variant:** {stats.get('variant_id') or 'unknown'} \u00b7 "
        f"**Grid:** {grid['width']} \u00d7 {grid['height']} ({grid['total_tiles']} tiles) \u00b7 "
        f"**Duration:** {_format_duration(stats)}"
    )
    lines.append("")
    lines.append("| Slot | Policy | Tiles painted | Share |")
    lines.append("| --- | --- | --- | --- |")
    for s in stats["slots"]:
        lines.append(
            f"| {s['slot']} | {s['policy_name']} | "
            f"{s['painted_tiles']} / {grid['total_tiles']} | {s['share_pct']:.1f}% |"
        )
    lines.append(
        f"| \u2014 | unpainted | {stats['unpainted_tiles']} / {grid['total_tiles']} "
        f"| {stats['unpainted_share_pct']:.1f}% |"
    )
    lines.append("")

    if stats["winner_slot"] is None and stats["unpainted_tiles"] == grid["total_tiles"]:
        lines.append("**Result:** no tiles were painted; no winner.")
    elif stats["tie"]:
        leaders = [s for s in stats["slots"] if s["painted_tiles"] == max(t["painted_tiles"] for t in stats["slots"])]
        lines.append(
            f"**Result:** tied at {leaders[0]['painted_tiles']} tiles "
            f"({', '.join(s['policy_name'] for s in leaders)})."
        )
    else:
        winner = next(s for s in stats["slots"] if s["slot"] == stats["winner_slot"])
        lines.append(
            f"**Winner:** Slot {winner['slot']} ({winner['policy_name']}) "
            f"by {stats['margin_tiles']} tiles."
        )
    return "\n".join(lines) + "\n"


def build_envelope(
    results: dict[str, Any],
    metadata: dict[str, Any],
    manifest: dict[str, Any],
) -> Envelope:
    variant_id = metadata.get("variant_id")
    if not isinstance(variant_id, str) or not variant_id:
        raise ValueError("episode metadata is missing 'variant_id'")
    variant = lookup_variant(manifest, variant_id)
    stats = build_stats(results, metadata, variant)
    summary = render_summary_markdown(stats)
    return Envelope(
        version="1",
        artifacts=[
            Artifact(id="summary", content_type="text/markdown", content=summary),
            Artifact(id="stats", content_type="application/json", content=stats),
        ],
    )


# ---------- orchestration ----------


def _log(reporter_id: str, msg: str) -> None:
    print(f"[{reporter_id}] {msg}", file=sys.stderr, flush=True)


def run(inputs: ReporterInputs) -> None:
    """Read inputs, build envelope, validate, write to output URI."""
    results = read_json(inputs.results_uri)
    metadata = read_json(inputs.episode_metadata_uri)
    manifest = read_json(inputs.manifest_uri)
    envelope = build_envelope(results=results, metadata=metadata, manifest=manifest)
    payload = envelope.to_json_bytes()
    validate_envelope(json.loads(payload))  # self-check round-tripped output
    write_uri(inputs.report_output_uri, payload, content_type="application/json")


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001 -- reserved for future flags
    reporter_id = os.environ.get("COGAME_REPORTER_ID", "paint-arena-summarizer")
    try:
        inputs = load_reporter_inputs()
    except KeyError as exc:
        _log(reporter_id, f"startup error: {exc}")
        return 1
    try:
        run(inputs)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        _log(inputs.reporter_id, f"reporter failed: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover -- last-resort surface
        _log(inputs.reporter_id, f"unexpected error: {exc!r}")
        return 1
    _log(inputs.reporter_id, "wrote envelope to " + inputs.report_output_uri)
    return 0


if __name__ == "__main__":
    sys.exit(main())
