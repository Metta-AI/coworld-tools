#!/usr/bin/env bash
# Containerized end-to-end smoke test for paint_arena_summarizer.
#
# Builds the image, runs it against the checked-in synthetic fixtures
# (smoke/fixtures/{results,metadata,replay}.json), and asserts that the
# emitted envelope is well-formed, has the expected D3 shape, and preserves
# the contract-aligned key ordering across the container boundary.
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

OUTDIR="$(mktemp -d)"
trap 'rm -rf "${OUTDIR}"' EXIT
echo "==> running ${IMAGE} (output -> ${OUTDIR})"

# Mount the fixtures read-only and the output dir read-write. Use file://
# URIs against the in-container mount path.
docker run --rm \
  -v "${FIXTURES}":/in:ro \
  -v "${OUTDIR}":/out \
  -e COGAME_RESULTS_URI=file:///in/results.json \
  -e COGAME_REPLAY_URI=file:///in/replay.json \
  -e COGAME_EPISODE_METADATA_URI=file:///in/metadata.json \
  -e COGAME_REPORT_OUTPUT_URI=file:///out/report.json \
  -e COGAME_REPORTER_ID=paint-arena-summarizer \
  "${IMAGE}"

REPORT="${OUTDIR}/report.json"
if [[ ! -f "${REPORT}" ]]; then
  echo "FAIL: container exited 0 but did not write ${REPORT}" >&2
  exit 1
fi

echo "==> validating envelope at ${REPORT}"

# Structural + ordering assertions. Done in Python because the asserts are
# bytewise (key order) and parsed-shape (artifact list, content_types), both
# of which are awkward in pure bash. The host's python3 is sufficient -- no
# project deps required.
python3 - "${REPORT}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "rb") as f:
    raw = f.read()
text = raw.decode("utf-8")
env = json.loads(raw)

def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

if env.get("version") != "1":
    fail(f'expected version "1", got {env.get("version")!r}')

artifacts = env.get("artifacts")
if not isinstance(artifacts, list) or len(artifacts) != 2:
    fail(f"expected 2 artifacts, got {artifacts!r}")

ids_in_order = [a.get("id") for a in artifacts]
if ids_in_order != ["summary", "stats"]:
    fail(f'expected artifact order ["summary", "stats"], got {ids_in_order!r}')

if artifacts[0].get("content_type") != "text/markdown":
    fail(f'summary content_type expected text/markdown, got {artifacts[0].get("content_type")!r}')
if artifacts[1].get("content_type") != "application/json":
    fail(f'stats content_type expected application/json, got {artifacts[1].get("content_type")!r}')

# Top-level dict key order: "version" before "artifacts".
top_keys = list(env.keys())
if top_keys != ["version", "artifacts"]:
    fail(f'top-level key order expected ["version","artifacts"], got {top_keys!r}')

# Per-artifact key order: "id" before "content_type" before "content".
for a in artifacts:
    keys = list(a.keys())
    if keys[:3] != ["id", "content_type", "content"]:
        fail(f"artifact {a.get('id')!r} key order expected [id,content_type,content,...], got {keys!r}")

# Bytewise ordering check on the serialized form -- a regression where the
# host serialized correctly but the image somehow rewrote keys would still
# be caught.
i_version = text.index('"version"')
i_artifacts = text.index('"artifacts"')
if not i_version < i_artifacts:
    fail("serialized 'version' must appear before 'artifacts'")

# Stats sanity: variant_id propagates from metadata and grid dimensions came
# from the replay's `config` block (per D11 -- no manifest URI in v1).
stats = artifacts[1]["content"]
if stats.get("variant_id") != "default":
    fail(f"stats.variant_id expected 'default', got {stats.get('variant_id')!r}")
grid = stats.get("grid", {})
if grid.get("width") != 12 or grid.get("height") != 8:
    fail(f"stats.grid expected 12x8, got {grid!r}")
if stats.get("winner_slot") != 0:
    fail(f"stats.winner_slot expected 0, got {stats.get('winner_slot')!r}")

print("OK: envelope shape, content types, and key ordering all match contract")
PY

echo "==> smoke test passed"
