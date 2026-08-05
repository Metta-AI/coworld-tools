#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

uv run python "${HERE}/smoke/make_bundle.py" "${TMPDIR}/bundle.zip"

COGAME_EPISODE_BUNDLE_URI="file://${TMPDIR}/bundle.zip" \
COGAME_REPORT_URI="file://${TMPDIR}/report.zip" \
uv run python "${HERE}/mettagrid_replay_atlas.py"

uv run python - <<PY
import json
import zipfile
from pathlib import Path

report = Path("${TMPDIR}/report.zip")
with zipfile.ZipFile(report) as zf:
    names = set(zf.namelist())
    manifest = json.loads(zf.read("manifest.json"))
    html = zf.read("summary.html").decode("utf-8")
expected = {"manifest.json", "summary.html", "events.parquet", "occupancy.png", "timeline.png"}
if names != expected:
    raise SystemExit(f"unexpected report entries: {sorted(names)}")
if manifest["render"] != "summary.html" or manifest["event_log"] != "events.parquet":
    raise SystemExit(f"unexpected manifest: {manifest}")
if "data:image/png;base64," not in html:
    raise SystemExit("render is not self-contained (no embedded charts)")
print(f"ok: {report}")
PY
