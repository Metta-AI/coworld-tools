#!/usr/bin/env bash
# Containerized end-to-end smoke test for paint_arena_summarizer.
#
# Builds the image, packs the checked-in synthetic fixtures
# (smoke/fixtures/{results,metadata,replay}.json) into a canonical
# episode bundle zip, runs the container against it, and asserts that
# the emitted zip matches the canonical Coworld reporter contract:
# four top-level entries (manifest.json, summary.html, stats.json,
# proximity.parquet), an in-zip manifest.json flagging summary.html as
# `render` and proximity.parquet as `event_log`, pinned mtimes for
# byte-identical reruns, stats sanity (grid + winner), and a non-empty
# proximity.parquet derived from the fixture's scripted frames.
#
# Use this as the integration-level check that complements the in-process
# pytest suite. The pytest suite exercises every code path; this script
# proves the packaged image actually works.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-paint-arena-summarizer:latest}"
FIXTURES="${HERE}/smoke/fixtures"

# Always build first -- the smoke test exists to verify the packaged image
# matches the source on disk, so staleness would defeat the point. Honors
# IMAGE so callers can smoke-test a specific tag.
echo "==> building ${IMAGE}"
IMAGE="${IMAGE}" "${HERE}/build.sh" >/dev/null

INDIR="$(mktemp -d)"
OUTDIR="$(mktemp -d)"
trap 'rm -rf "${INDIR}" "${OUTDIR}"' EXIT

echo "==> packing bundle from ${FIXTURES} -> ${INDIR}/bundle.zip"
python3 "${HERE}/smoke/make_bundle.py" "${INDIR}/bundle.zip"

echo "==> running ${IMAGE} (output -> ${OUTDIR})"

# Mount the bundle dir read-only and the output dir read-write. Use file://
# URIs against the in-container mount path.
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

# Structural assertions. Done in Python because zip inspection in pure bash
# is awkward. The host's python3 is sufficient -- only stdlib (zipfile, json).
python3 - "${REPORT}" <<'PY'
import json
import sys
import zipfile

path = sys.argv[1]

def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

RENDERABLE_EXTS = {".md", ".html"}
PINNED_MTIME = (1980, 1, 1, 0, 0, 0)
EXPECTED_ENTRIES = {"manifest.json", "summary.html", "stats.json", "proximity.parquet"}

with zipfile.ZipFile(path) as zf:
    if zf.testzip() is not None:
        fail("zip failed integrity check (testzip)")
    infos = zf.infolist()
    names = [i.filename for i in infos]
    if set(names) != EXPECTED_ENTRIES:
        fail(f"expected entries {EXPECTED_ENTRIES!r}, got {set(names)!r}")

    for info in infos:
        if info.date_time != PINNED_MTIME:
            fail(f"{info.filename} date_time {info.date_time} != pinned {PINNED_MTIME}")

    manifest = json.loads(zf.read("manifest.json"))
    if manifest.get("reporter_id") != "paint-arena-summarizer":
        fail(f"manifest.reporter_id expected 'paint-arena-summarizer', got {manifest.get('reporter_id')!r}")
    render = manifest.get("render")
    if render != "summary.html":
        fail(f"manifest.render expected 'summary.html', got {render!r}")
    if render not in names:
        fail(f"manifest.render points at {render!r} which is missing from the zip")
    ext = "." + render.rsplit(".", 1)[-1].lower() if "." in render else ""
    if ext not in RENDERABLE_EXTS:
        fail(f"manifest.render extension {ext!r} not in {RENDERABLE_EXTS!r}")
    event_log = manifest.get("event_log")
    if event_log != "proximity.parquet":
        fail(f"manifest.event_log expected 'proximity.parquet', got {event_log!r}")
    if event_log not in names:
        fail(f"manifest.event_log points at {event_log!r} which is missing from the zip")

    summary_html = zf.read("summary.html").decode("utf-8")
    if not summary_html.startswith("<!DOCTYPE html>"):
        fail("summary.html does not look like an HTML document")
    if "<script" in summary_html or "<link" in summary_html:
        fail("summary.html is not self-contained (found <script> or <link>)")

    stats = json.loads(zf.read("stats.json"))
    parquet_size = zf.getinfo("proximity.parquet").file_size

# Stats sanity: variant_id propagates from metadata and grid dimensions came
# from the replay's `config` block.
if stats.get("variant_id") != "default":
    fail(f"stats.variant_id expected 'default', got {stats.get('variant_id')!r}")
grid = stats.get("grid", {})
if grid.get("width") != 12 or grid.get("height") != 8:
    fail(f"stats.grid expected 12x8, got {grid!r}")
if stats.get("winner_slot") != 0:
    fail(f"stats.winner_slot expected 0, got {stats.get('winner_slot')!r}")
if stats.get("proximity_event_count", 0) < 1:
    fail(f"stats.proximity_event_count expected >= 1 (fixture has frames), got {stats.get('proximity_event_count')!r}")
if parquet_size == 0:
    fail("proximity.parquet is empty (file_size == 0)")

print("OK: zip shape, manifest.json, pinned mtimes, stats sanity, and parquet presence all match canonical contract")
PY

echo "==> smoke test passed"
