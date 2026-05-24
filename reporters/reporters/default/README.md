# default-reporter

The Softmax-published default reporter. Any Coworld manifest whose `reporter[]` array does not declare a game-specific reporter can reference this image to satisfy the `min_length=1` requirement on the schema's supporting-role arrays. The image is explicitly **placeholder** — it produces a one-paragraph Markdown summary listing the per-slot scores from `results.json` and nothing else. Concrete reporters with real game-specific analysis (PaintArena, Among Them, ...) live elsewhere in this repo.

> **Spec source (canonical):** `~/coding/metta_checkouts/metta_1/docs/plans/coworld-schema-migration-plan.md:179`. The default reporter "reads `COGAME_EPISODE_BUNDLE_URI`, unzips it, writes a minimal `.zip` to `COGAME_REPORT_URI` containing an inner `manifest.json` (with `reporter_id: 'softmax/default-reporter'` and a `render` pointing to a generated `summary.md`) plus a one-paragraph summary derived from `results.json`'s `scores` field. No parquet event log."
>
> **In-repo spec:** [`docs/reports/reporter-migration-remaining-2026-05-23.md`](../../docs/reports/reporter-migration-remaining-2026-05-23.md) §5.1.

## What it produces

```
report.zip
├── manifest.json       # {reporter_id: "softmax/default-reporter", render: "summary.md", event_log: null}
└── summary.md          # one section per slot, plus a note that this is the default reporter
```

| Entry | Role | Contents |
| --- | --- | --- |
| `manifest.json` | render manifest | `{"reporter_id": "softmax/default-reporter", "render": "summary.md", "event_log": null}` — built via `reporter_sdk.build_report_zip`, which validates `render` points at an existing renderable entry. |
| `summary.md` | `render` target | Episode-request id, bundle status, one bullet per slot (`Slot {i} scored {score}.`), and a footer naming this reporter as the placeholder. No event log; the default reporter does not analyze events. |

No `event_log` is declared. The default reporter has nothing to log — its whole purpose is to be a valid Coworld reporter without performing analysis. Reporters that need an event log (most concrete ones do) declare their own Parquet path.

The output zip is built via the SDK's deterministic writer (every entry's `date_time` pinned to `(1980, 1, 1, 0, 0, 0)`), so reruns over identical inputs produce byte-identical bytes. Useful for caching.

## Never-crashes contract

The default reporter runs against every Coworld that hasn't shipped a game-specific reporter, so it cannot assume anything about the bundle beyond what the canonical episode-bundle contract guarantees. It explicitly handles each of the degenerate inputs below without raising:

| Bundle state | Behavior |
| --- | --- |
| `results.json` present, `scores` is a non-empty list | Per-slot lines in `summary.md` |
| `results.json` present, `scores` missing or not a list | Summary records "no scores were available" |
| `results.json` present, `scores` is an empty list | Summary records "empty scores list (zero players)" |
| `results.json` present, score entries are non-numeric (`None`, string, bool, dict) | Each entry formats via a `_format_score` helper; no crash |
| `results.json` not in `manifest.include` (e.g. failed episodes) | Summary records the missing data |
| `results.json` in `manifest.include` but unparseable | Reporter logs to stderr, writes the zip with a "no scores" summary |
| Bundle inner manifest reports `status="failed"` | Summary surfaces the failure status; per-slot section absent |

The only failures the reporter does not catch are ones it has no recourse against: an unreadable `COGAME_EPISODE_BUNDLE_URI`, an unwritable `COGAME_REPORT_URI`, or a bundle whose root `manifest.json` cannot be parsed at all. Those propagate via the SDK's exception path.

## Inputs

Per the canonical reporter contract (`packages/coworld/src/coworld/docs/roles/reporter.md` in metta):

| Env var | Direction | Purpose |
| --- | --- | --- |
| `COGAME_EPISODE_BUNDLE_URI` | read | URI of the episode-bundle zip. The reporter opens it, inspects its inner `manifest.json`, and reads `results.json` if `results` is in `manifest.include`. |
| `COGAME_REPORT_URI` | write | Write target for the output zip (`Content-Type: application/zip`). |

Both `file://` and `http(s)://` URIs are supported (via the SDK's I/O layer).

## Running locally

```bash
COGAME_EPISODE_BUNDLE_URI=file:///path/to/bundle.zip \
COGAME_REPORT_URI=file:///path/to/report.zip \
python default_reporter.py
```

The smoke harness (`./smoke.sh`) builds a synthetic three-slot bundle via `smoke/make_bundle.py` and runs the container end-to-end — use it as the local-bundle starting point.

## Building the image

```bash
./build.sh                                # builds default-reporter:latest for linux/amd64
IMAGE=ghcr.io/metta-ai/reporters-default:dev ./build.sh
PLATFORM=linux/arm64 ./build.sh           # local-only platform override
```

The Docker build context is `reporters/` (the directory containing `reporter_sdk/` and the per-coworld reporter trees), so the Dockerfile can `COPY` both the shared SDK and this reporter's source from one context. The image is published to GHCR via `.github/workflows/build-default-reporter-image.yml`.

## Tests

```bash
uv run pytest reporters/default/tests/ -v
```

Covers the happy path, missing `results` token, missing `scores` field, empty scores list, non-numeric score entries, unparseable `results.json`, failed bundle status, manifest-shape pinning (`reporter_id`, `render`, no `event_log`), pinned zip-entry mtimes, and a determinism check (two runs over the same inputs produce byte-identical bytes).

### Containerized smoke test

```bash
./smoke.sh                  # builds + runs the image against a synthetic bundle
IMAGE=ghcr.io/metta-ai/reporters-default:dev ./smoke.sh
```

Builds the image, hand-builds a synthetic bundle zip with three slots via `smoke/make_bundle.py`, runs the container, and asserts the output zip's `manifest.json` declares `reporter_id == "softmax/default-reporter"`, `render` points at an existing `summary.md`, no `event_log`, and `summary.md` is non-empty and names the reporter.

## Image name and reporter id

- The image is published as `ghcr.io/metta-ai/reporters-default:latest` (GHCR namespace, following the established `metta-ai/coworld-runner` convention).
- The in-zip `manifest.json::reporter_id` is `softmax/default-reporter` (the canonical id Coworld manifests reference, per the master plan).

These two identifiers are independent: the image registry path is how the platform pulls the container; the `reporter_id` is how downstream consumers identify the reporter in cached artifacts. Changing one does not require changing the other.

## Referencing this reporter from a Coworld manifest

A Coworld whose `reporter[]` is otherwise empty can satisfy `min_length=1` by adding an entry like:

```json
{
  "type": "reporter",
  "id": "softmax/default-reporter",
  "image": "ghcr.io/metta-ai/reporters-default:latest"
}
```

The exact manifest entry shape is defined in `~/coding/metta_checkouts/metta_1/packages/coworld/src/coworld/MANIFEST_README.md` and tracked under master-plan item C3 (populating `worlds/cogs_vs_clips/coworld_manifest_template.json::reporter[]`). C3 is metta-side work, not in scope for this repo.
