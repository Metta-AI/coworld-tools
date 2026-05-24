#!/usr/bin/env bash
# Containerized end-to-end smoke test for summarizer_template.
#
# Builds the template image, hand-builds a synthetic episode bundle zip,
# runs the container against it, and asserts that the emitted zip
# matches the canonical Coworld reporter contract -- specifically: a
# top-level manifest.json that parses, manifest.reporter_id is set, and
# manifest.render points at an existing entry inside the zip.
#
# The template doesn't analyze anything, so the assertions stay at the
# contract layer (valid manifest.json, valid render target) rather than
# at the content layer. That is what's appropriate for scaffolding -- a
# concrete reporter derived from this template will tighten the smoke
# assertions to cover its actual artifacts (HTML shape, parquet rows,
# stats sanity, etc.).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-summarizer-template:latest}"

echo "==> building ${IMAGE}"
IMAGE="${IMAGE}" "${HERE}/build.sh" >/dev/null

INDIR="$(mktemp -d)"
OUTDIR="$(mktemp -d)"
trap 'rm -rf "${INDIR}" "${OUTDIR}"' EXIT

echo "==> packing synthetic bundle -> ${INDIR}/bundle.zip"
python3 "${HERE}/smoke/make_bundle.py" "${INDIR}/bundle.zip"

echo "==> running ${IMAGE} (output -> ${OUTDIR})"
docker run --rm \
  -v "${INDIR}":/in:ro \
  -v "${OUTDIR}":/out \
  -e COGAME_EPISODE_BUNDLE_URI=file:///in/bundle.zip \
  -e COGAME_REPORT_URI=file:///out/report.zip \
  "${IMAGE}"

REPORT="${OUTDIR}/report.zip"
if [[ ! -f "${REPORT}" ]]; then
  echo "FAIL: container exited 0 but did not write ${REPORT}" >&2
  exit 1
fi

echo "==> validating zip at ${REPORT}"
python3 - "${REPORT}" <<'PY'
import json
import sys
import zipfile

path = sys.argv[1]

def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

RENDERABLE_EXTS = {".md", ".html"}

with zipfile.ZipFile(path) as zf:
    if zf.testzip() is not None:
        fail("zip failed integrity check (testzip)")
    names = set(zf.namelist())
    if "manifest.json" not in names:
        fail(f"output zip missing manifest.json; got entries: {sorted(names)!r}")

    manifest = json.loads(zf.read("manifest.json"))
    reporter_id = manifest.get("reporter_id")
    if not reporter_id:
        fail(f"manifest.reporter_id missing/empty: {manifest!r}")

    render = manifest.get("render")
    if render is not None:
        if render not in names:
            fail(f"manifest.render points at {render!r} which is missing from the zip")
        ext = "." + render.rsplit(".", 1)[-1].lower() if "." in render else ""
        if ext not in RENDERABLE_EXTS:
            fail(f"manifest.render extension {ext!r} not in {RENDERABLE_EXTS!r}")

    event_log = manifest.get("event_log")
    if event_log is not None and event_log not in names:
        fail(f"manifest.event_log points at {event_log!r} which is missing from the zip")

print(f"OK: zip shape and manifest.json valid (reporter_id={reporter_id!r}, render={render!r})")
PY

echo "==> smoke test passed"
