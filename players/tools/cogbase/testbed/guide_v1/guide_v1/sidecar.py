"""Per-document sidecar JSON contracts.

guide_v1 documents that own pieces of the runtime contract may emit a JSON
sidecar alongside their Markdown. The aggregator in :mod:`contracts` prefers
sidecar values over prose-derived ones, removing the regex-archaeology step
that is brittle across different document layouts.

Sidecars are optional. Missing or malformed sidecars are ignored and the
prose-extraction path runs as before.

Today the only recognized sidecar is ``INTERFACE_CONTRACT.contract.json``.
Adding more is a two-step change: register a filename in
:data:`SIDECAR_FILENAMES`, then teach :func:`merge_sidecars` how to fold the
new fields into the aggregated contract.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


DOC_CONTRACT_SCHEMA_VERSION = "guide.doc_contract.v1"

SIDECAR_FILENAMES: dict[str, str] = {
    "INTERFACE_CONTRACT.md": "INTERFACE_CONTRACT.contract.json",
}


def sidecar_path(output_dir: Path, doc_filename: str) -> Path | None:
    """Return the expected sidecar path for ``doc_filename`` if one is registered."""

    name = SIDECAR_FILENAMES.get(doc_filename)
    if name is None:
        return None
    return output_dir / name


def read_sidecar(output_dir: Path, doc_filename: str) -> dict[str, Any] | None:
    """Read and validate the sidecar for ``doc_filename``.

    Returns ``None`` when no sidecar is registered, the file does not exist,
    the JSON is invalid, or the schema version does not match. Callers should
    treat ``None`` as "no sidecar, use prose extraction."
    """

    path = sidecar_path(output_dir, doc_filename)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != DOC_CONTRACT_SCHEMA_VERSION:
        return None
    return data


def merge_sidecars(contract: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Overlay sidecar fields onto the aggregated guide contract.

    Sidecar fields overwrite prose-extracted values. Fields absent from a
    sidecar leave the prose-extracted result untouched, so this is a strict
    upgrade: passing a missing or partial sidecar can only refine the result.

    A ``sidecar_sources`` dict is added at the top level listing which doc
    section was authoritative for each piece of the contract. Consumers and
    tests can use it to detect when prose extraction was the source of truth.
    """

    merged = dict(contract)
    sources: dict[str, str] = {}

    interface = read_sidecar(output_dir, "INTERFACE_CONTRACT.md")
    if interface is not None:
        if "observation" in interface:
            merged["observation"] = _merge_observation(
                merged.get("observation", {}), interface["observation"]
            )
            sources["observation"] = "INTERFACE_CONTRACT.contract.json"
        if "actions" in interface:
            merged["actions"] = _merge_actions(
                merged.get("actions", {}), interface["actions"]
            )
            sources["actions"] = "INTERFACE_CONTRACT.contract.json"
        if "runtime" in interface:
            merged["runtime"] = _merge_runtime(
                merged.get("runtime", {}), interface["runtime"]
            )
            sources["runtime"] = "INTERFACE_CONTRACT.contract.json"

    if sources:
        merged["sidecar_sources"] = sources
    return merged


def _merge_observation(prose: dict[str, Any], sidecar: Any) -> dict[str, Any]:
    if not isinstance(sidecar, dict):
        return prose
    merged = dict(prose)
    for key in ("surface_category", "confidence", "primary", "alternates"):
        if key in sidecar:
            merged[key] = sidecar[key]
    return merged


def _merge_actions(prose: dict[str, Any], sidecar: Any) -> dict[str, Any]:
    if not isinstance(sidecar, dict):
        return prose
    merged = dict(prose)
    for key in (
        "style",
        "default_action",
        "requires_message_type",
        "payload_prefix",
        "payloads",
    ):
        if key in sidecar:
            merged[key] = sidecar[key]
    candidates = sidecar.get("candidates")
    if isinstance(candidates, list):
        merged["candidates"] = list(_normalize_candidates(candidates))
    return merged


def _merge_runtime(prose: dict[str, Any], sidecar: Any) -> dict[str, Any]:
    if not isinstance(sidecar, dict):
        return prose
    merged = dict(prose)
    if isinstance(sidecar.get("endpoints"), list):
        merged["endpoints"] = sidecar["endpoints"]
    if "tick_rate_hz" in sidecar:
        merged["tick_rate_hz"] = sidecar["tick_rate_hz"]
    return merged


def _normalize_candidates(items: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for item in items:
        if not isinstance(item, dict):
            continue
        out: dict[str, Any] = {
            "action_id": item.get("action_id"),
            "source": "sidecar",
        }
        if "description" in item:
            out["description"] = item["description"]
        evidence = item.get("evidence")
        if isinstance(evidence, list):
            out["evidence"] = evidence
        yield out
