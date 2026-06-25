#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

uv run python "${HERE}/smoke/make_bundle.py" "${TMPDIR}/bundle.zip"

COGAME_EPISODE_BUNDLE_URI="file://${TMPDIR}/bundle.zip" \
COGAME_REPORT_URI="file://${TMPDIR}/report.zip" \
uv run python "${HERE}/cogs_vs_clips_summarizer.py"

uv run python - <<PY
import zipfile
from pathlib import Path

report = Path("${TMPDIR}/report.zip")
with zipfile.ZipFile(report) as zf:
    names = set(zf.namelist())
expected = {"manifest.json", "summary.md", "behavior_summary.json", "trace.jsonl", "events.parquet"}
if names != expected:
    raise SystemExit(f"unexpected report entries: {sorted(names)}")
print(f"ok: {report}")
PY
