"""Softmax default reporter — placeholder for Coworlds without a custom one.

Any Coworld whose ``manifest.reporter[]`` does not declare a game-specific
reporter can reference this image (``softmax/default-reporter:latest``) to
satisfy the schema's ``min_length=1`` requirement on supporting-role arrays.

The default reporter is intentionally **placeholder** — it surfaces just
enough about the episode to be a valid Coworld reporter, but does not
attempt any game-specific analysis. Concrete reporters (PaintArena,
Among Them, etc.) live elsewhere in this repo and are the real article;
this image exists so a Coworld author can ship before a custom reporter
does.

Behavior:

1. Read ``COGAME_EPISODE_BUNDLE_URI`` and open the episode bundle.
2. Read ``results.json`` from the bundle if it's available; fall back to
   ``None`` if the token isn't in ``manifest.include`` or the bundle is
   missing data.
3. Generate a one-section ``summary.md`` listing the reporter id, the
   bundle's status, the number of players visible in ``results.scores``,
   and one line per slot reporting that slot's score. Every field is
   defensively handled — if ``results.json`` is missing, malformed, or
   carries no ``scores``, the summary records that fact instead of
   crashing.
4. Write a single output zip to ``COGAME_REPORT_URI`` with a top-level
   ``manifest.json`` declaring ``reporter_id="softmax/default-reporter"``,
   ``render="summary.md"``, and no ``event_log``. The zip is built via
   :func:`reporter_sdk.build_report_zip`, which validates the manifest
   against the entries before producing bytes.

The reporter never raises on a "well-formed but minimal" bundle. The only
errors it can produce are ones it cannot do anything about — an
unreadable bundle URI, an unwritable report URI, or a bundle whose root
``manifest.json`` is itself unparseable. Those propagate via the SDK's
normal exception path.

See ``docs/reports/reporter-migration-remaining-2026-05-23.md`` §5.1 and
metta's ``docs/plans/coworld-schema-migration-plan.md:179`` for the
spec; see ``README.md`` here for the user-facing description.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from reporter_sdk import (
    BundleReader,
    OutputManifest,
    ReporterInputs,
    build_report_zip,
    load_reporter_inputs,
    read_json,
    write_uri,
)

# Stamped into the output zip's ``manifest.json::reporter_id`` and the
# value Coworld manifests should use when referencing this image. Keeps
# the ``softmax/`` prefix from the master plan even though the image
# itself is published under ``metta-ai/`` on GHCR — the reporter_id and
# the image tag are independent identifiers.
REPORTER_ID = "softmax/default-reporter"
REPORT_REQUEST_ENV_VAR = "COGAME_REPORT_REQUEST"


def _safe_scores(results: Any) -> list[Any] | None:
    """Return ``results['scores']`` if it is a list, otherwise ``None``.

    The default reporter never trusts the shape of ``results.json``: this
    image runs against every Coworld that hasn't written its own reporter
    yet, so the score field may be missing, ``None``, a scalar, or a
    completely different schema. Anything other than a list is treated as
    "no scores available" rather than as an error.
    """
    if not isinstance(results, dict):
        return None
    scores = results.get("scores")
    if not isinstance(scores, list):
        return None
    return scores


def _format_score(value: Any) -> str:
    """Format a single score for display in the Markdown summary.

    Returns a stringified number when ``value`` is numeric, ``"missing"``
    when it is ``None``, and ``repr(value)`` otherwise. Keeping this
    permissive prevents an unusual score type (a string, a dict, ...)
    from crashing the report build.
    """
    if value is None:
        return "missing"
    if isinstance(value, bool):
        # Order matters: ``bool`` is a subclass of ``int``, so the
        # numeric branch would otherwise stringify ``True`` as ``"1"``.
        return repr(value)
    if isinstance(value, (int, float)):
        return f"{value}"
    return repr(value)


def _render_summary_md(
    *,
    ereq_id: str | None,
    status: str | None,
    results: Any,
) -> str:
    """Compose the placeholder ``summary.md`` body.

    The summary intentionally avoids any game-specific interpretation —
    the default reporter has no idea what game the episode came from —
    and just enumerates whatever it can see in ``results.json::scores``.
    Missing data shows up as explicit prose ("no scores were available"),
    not as an empty section, so a reader can tell at a glance that the
    default reporter ran without crashing on a degenerate input.
    """
    lines: list[str] = ["# Episode summary (default reporter)\n"]

    metadata_lines: list[str] = []
    if ereq_id:
        metadata_lines.append(f"- Episode request id: `{ereq_id}`")
    if status:
        metadata_lines.append(f"- Bundle status: `{status}`")
    metadata_lines.append(f"- Reporter id: `{REPORTER_ID}`")
    lines.append("\n".join(metadata_lines))
    lines.append("")

    scores = _safe_scores(results)
    if scores is None:
        lines.append(
            "No scores were available in this episode's `results.json` — "
            "either the bundle did not include a `results` token, the file "
            "was unparseable, or `results.scores` was missing. The default "
            "reporter cannot produce a per-slot summary without scores."
        )
    elif not scores:
        lines.append(
            "This episode's `results.json` contained an empty `scores` "
            "list (zero players). The default reporter has nothing to "
            "report per slot."
        )
    else:
        lines.append(f"## Scores ({len(scores)} slot{'s' if len(scores) != 1 else ''})")
        lines.append("")
        for slot, score in enumerate(scores):
            lines.append(f"- Slot {slot} scored {_format_score(score)}.")

    lines.append("")
    lines.append(
        "_This is the Softmax default reporter — a placeholder for "
        "Coworlds that have not yet shipped a game-specific reporter. "
        "To produce a richer report, point the Coworld's "
        "`manifest.reporter[]` at a game-specific image (see the "
        "`Metta-AI/reporters` repository for examples)._"
    )
    return "\n".join(lines) + "\n"


def build_zip_bytes(
    *,
    ereq_id: str | None,
    status: str | None,
    results: Any,
) -> bytes:
    """Build the default reporter's output zip: a top-level
    ``manifest.json`` flagging ``summary.md`` as ``render`` (no
    ``event_log``) plus the rendered Markdown body. The SDK's
    :func:`build_report_zip` enforces that ``render`` resolves to an
    existing ``.md``/``.html`` entry.
    """
    summary_md = _render_summary_md(
        ereq_id=ereq_id, status=status, results=results
    ).encode("utf-8")
    return build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            render="summary.md",
            event_log=None,
        ),
        [("summary.md", summary_md)],
    )


def run(inputs: ReporterInputs) -> None:
    """Read the bundle, build the placeholder zip, write it.

    The reporter swallows any failure to read ``results.json`` — the
    bundle may legitimately omit it (for failed episodes whose status is
    ``"failed"``, or for access-control-filtered bundles where the
    ``results`` token isn't in ``manifest.include``). In every such case
    the reporter still writes a valid zip; the rendered ``summary.md``
    just notes that no scores were available.
    """
    with BundleReader(inputs.episode_bundle_uri) as bundle:
        inner = bundle.inner_manifest()
        results: Any = None
        try:
            results = bundle.read_json_optional("results")
        except Exception as exc:  # noqa: BLE001 — defensive by design
            # The bundle's inner manifest said ``results`` was included,
            # but the entry didn't parse. The default reporter still
            # produces a report in this case — see ``_render_summary_md``
            # for how a missing/unparseable results.json surfaces. Log
            # so an operator can investigate, but do not raise.
            print(
                f"[{REPORTER_ID}] warning: could not read results.json "
                f"from bundle: {exc!r}",
                file=sys.stderr,
                flush=True,
            )

    payload = build_zip_bytes(
        ereq_id=inner.ereq_id,
        status=inner.status,
        results=results,
    )
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}",
        file=sys.stderr,
        flush=True,
    )


def _direct_episode_results(episode: dict[str, Any]) -> Any:
    """Read results from a direct report_request episode if present."""
    try:
        uri = episode["artifacts"]["results"]["uri"]
    except (KeyError, TypeError):
        return None
    try:
        return read_json(uri)
    except Exception as exc:  # noqa: BLE001 — defensive by design
        print(
            f"[{REPORTER_ID}] warning: could not read direct results: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return None


def run_report_request(raw_request: str) -> None:
    """Read a direct COGAME_REPORT_REQUEST, build the zip, and write it."""
    request = json.loads(raw_request)
    episodes = request.get("episodes")
    if isinstance(episodes, list) and episodes:
        episode = episodes[0]
    else:
        episode = {}

    if isinstance(episode, dict):
        manifest = episode.get("manifest", {})
    else:
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    if isinstance(episode, dict):
        results = _direct_episode_results(episode)
    else:
        results = None

    payload = build_zip_bytes(
        ereq_id=manifest.get("ereq_id"),
        status=manifest.get("status"),
        results=results,
    )
    write_uri(request["report_uri"], payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {request['report_uri']}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    raw_request = os.environ.get(REPORT_REQUEST_ENV_VAR)
    if raw_request:
        run_report_request(raw_request)
    else:
        run(load_reporter_inputs())
