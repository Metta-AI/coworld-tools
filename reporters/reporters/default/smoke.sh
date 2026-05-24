#!/usr/bin/env bash
# Containerized end-to-end smoke test for the default reporter.
#
# Builds the image, hand-builds a synthetic episode bundle zip, runs the
# container against it, and asserts the emitted zip matches the
# canonical Coworld reporter contract: a top-level manifest.json that
# parses, reporter_id == "softmax/default-reporter", render points at a
# .md file present in the zip, no event_log, and the rendered summary.md
# is non-empty.
#
# Use this as the integration-level check that complements the
# in-process pytest suite. The pytest suite covers the defensive null
# paths; this script proves the packaged image actually works.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-default-reporter:latest}"

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
    if manifest.get("reporter_id") != "softmax/default-reporter":
        fail(
            "manifest.reporter_id expected 'softmax/default-reporter', "
            f"got {manifest.get('reporter_id')!r}"
        )
    render = manifest.get("render")
    if render != "summary.md":
        fail(f"manifest.render expected 'summary.md', got {render!r}")
    if render not in names:
        fail(
            f"manifest.render points at {render!r} which is missing from "
            "the zip"
        )
    ext = "." + render.rsplit(".", 1)[-1].lower() if "." in render else ""
    if ext not in RENDERABLE_EXTS:
        fail(f"manifest.render extension {ext!r} not in {RENDERABLE_EXTS!r}")

    event_log = manifest.get("event_log")
    if event_log is not None:
        fail(
            "the default reporter must declare event_log=None, got "
            f"{event_log!r}"
        )

    body = zf.read("summary.md").decode("utf-8")
    if not body.strip():
        fail("summary.md is empty")
    if "softmax/default-reporter" not in body:
        fail("summary.md does not mention the reporter id")

print(
    "OK: zip shape, manifest.json, and summary.md content all match the "
    "default reporter's contract"
)
PY

echo "==> smoke test passed"
