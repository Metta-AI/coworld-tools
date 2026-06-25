"""Summarizer template — a runnable scaffold for new Coworld reporters.

This is **scaffolding**, not a runtime dependency. To start a new
game-specific summarizer:

1. Copy this directory (``reporters/templates/summarizer_template/``)
   to ``reporters/<your_coworld>/<your_summarizer>/``.
2. Rename ``summarizer.py`` (e.g. ``my_coworld_summarizer.py``) and
   replace :data:`REPORTER_ID` below with the reporter's canonical id
   (the one that appears in the Coworld manifest's ``reporter[]``).
3. Inside :func:`run`, parse the bundle tokens your game needs
   (``results``, ``replay``, ``metadata`` — whatever ``manifest.include``
   actually delivers) and replace the placeholder ``summary.md`` with
   the artifacts your reporter actually produces.
4. Update the per-reporter ``Dockerfile``, ``build.sh``, ``smoke.sh``,
   and ``README.md`` to reflect the new entrypoint and image tag.
5. Add the new reporter to ``CATALOG.yaml`` at the repo root.

The template itself is **game-agnostic**: it opens the bundle, ignores
every token inside it, and emits an output zip whose only payload is a
placeholder ``summary.md``. The output zip's ``manifest.json`` is
canonical (``reporter_id``, ``render``), so the template demonstrates
the full reporter wiring end-to-end without pretending to analyze
anything.

See ``reporters/templates/README.md`` for the broader rationale; see
``docs/REPORTER_DESIGN.md`` (and metta's
``packages/coworld/src/coworld/docs/roles/reporter.md``) for the
canonical reporter contract this template implements.
"""

from __future__ import annotations

import sys

from reporter_sdk import (
    BundleReader,
    OutputManifest,
    ReporterInputs,
    build_report_zip,
    load_reporter_inputs,
    write_uri,
)

# The reporter's self-identifying id, stamped into the output zip's
# ``manifest.json::reporter_id``. Conventionally matches the runnable's
# ``id`` in the Coworld manifest's ``reporter[]``. Change this when you
# copy the template into a concrete reporter directory.
REPORTER_ID = "summarizer-template"

# Placeholder render target. A concrete reporter typically replaces this
# with a self-contained ``summary.html`` rendered from the game's
# results/replay data; until then, the template ships a one-paragraph
# Markdown stub so the output zip has *some* renderable artifact and the
# in-zip ``manifest.json::render`` is non-null.
_PLACEHOLDER_SUMMARY_MD = (
    "# Summarizer template\n"
    "\n"
    "This is a template reporter. Customize me by adding game-specific "
    "analysis.\n"
)


def build_zip_bytes() -> bytes:
    """Build the template's stub output zip.

    Game-specific reporters typically take the parsed bundle artifacts
    (results, replay, metadata) as arguments here and derive an HTML
    summary, a JSON stats blob, and a Parquet event log. The template
    takes nothing and emits a placeholder ``summary.md`` so the wiring
    is exercised end-to-end without pretending to analyze.
    """
    summary_md = _PLACEHOLDER_SUMMARY_MD.encode("utf-8")
    return build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            render="summary.md",
            event_log=None,
        ),
        [("summary.md", summary_md)],
    )


def run(inputs: ReporterInputs) -> None:
    """Read the bundle at ``inputs.episode_bundle_uri``, build the stub
    output zip, write it to ``inputs.report_uri``.

    The template opens the bundle just to demonstrate the read side of
    the contract; it doesn't consume any of the bundle's tokens. A
    concrete reporter would replace the ``with BundleReader(...)``
    block with calls like ``bundle.read_json("results")`` and would
    pass the parsed artifacts into :func:`build_zip_bytes`.
    """
    with BundleReader(inputs.episode_bundle_uri) as bundle:
        inner = bundle.inner_manifest()
        # A concrete reporter would typically refuse to operate on a
        # failed bundle; the template just notes the status and
        # proceeds, since it doesn't read any of the bundle's tokens.
        _ = inner.ereq_id

    payload = build_zip_bytes()
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
