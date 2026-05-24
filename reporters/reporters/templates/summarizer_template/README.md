# summarizer_template

A runnable, game-agnostic scaffold for new Coworld reporters. Copy this directory into a new reporter location, rename the entrypoint, and fill in the game-specific logic. The template itself is **not** a runtime dependency — concrete reporters consume the shared [`reporter_sdk`](../../reporter_sdk/) package directly.

The template is intentionally minimal: it reads `COGAME_EPISODE_BUNDLE_URI`, opens the bundle (to demonstrate the read side of the contract), and writes a single output zip to `COGAME_REPORT_URI` containing only a placeholder `summary.md` plus the canonical in-zip `manifest.json`. It does not parse `results.json`, decode any replay, or emit a Parquet event log — those are game-specific behaviors a derived reporter adds.

## What the template produces

```
report.zip
├── manifest.json       # {reporter_id: "summarizer-template", render: "summary.md", event_log: null}
└── summary.md          # placeholder one-paragraph stub
```

| Entry | Role | Contents |
| --- | --- | --- |
| `manifest.json` | render manifest | `{"reporter_id": "summarizer-template", "render": "summary.md", "event_log": null}` — written via `reporter_sdk.build_report_zip`, which validates that `render` resolves to an existing entry with a renderable extension. |
| `summary.md` | `render` target | Single paragraph: "This is a template reporter. Customize me by adding game-specific analysis." |

No `event_log` is declared. The template has nothing to analyze, so there are no events to log; a derived reporter adds its own `events.parquet` (and flags it in the manifest) once it starts emitting events.

The output zip is built via the SDK's deterministic writer, so every entry's `date_time` is pinned to `(1980, 1, 1, 0, 0, 0)` — reruns over identical inputs produce byte-identical bytes.

## Deriving a concrete reporter

1. **Copy the directory:**

   ```bash
   cp -R reporters/templates/summarizer_template reporters/<your_coworld>/<your_summarizer>
   ```

2. **Rename the entrypoint** and update the module name used by `Dockerfile`, `build.sh`, and `smoke.sh`:

   ```bash
   mv reporters/<your_coworld>/<your_summarizer>/summarizer.py \
      reporters/<your_coworld>/<your_summarizer>/<your_summarizer>.py
   ```

3. **Edit `<your_summarizer>.py`:** change `REPORTER_ID` to your reporter's canonical id (the one that appears in the Coworld manifest's `reporter[]`), then replace the placeholder `summary.md` with the artifacts your reporter actually produces. Inside `run`, parse the bundle tokens your game needs (`bundle.read_json("results")`, etc.) and pass them into your `build_zip_bytes`. The two concrete reporters in this repo — [`paint_arena_summarizer`](../../paint_arena/paint_arena_summarizer/) and [`among_them_summarizer`](../../among_them/among_them_summarizer/) — are reference implementations.

4. **Update `Dockerfile` / `Dockerfile.dockerignore` / `build.sh`:** swap `templates/summarizer_template/...` for `<your_coworld>/<your_summarizer>/...` in the `COPY` lines, dockerignore allowlist, and the `IMAGE` default in `build.sh`. The Docker build context stays at `reporters/` so the shared SDK is reachable.

5. **Update `smoke/make_bundle.py`:** build a synthetic bundle that resembles the real one your game produces (results JSON shape, replay shape, optional metadata). The PaintArena and Among Them smoke fixtures are the patterns to follow.

6. **Tighten `smoke.sh`:** the template's smoke assertions stay at the contract layer (manifest parses, render target exists). Derived reporters typically add content-layer assertions — exact entry set, summary HTML shape, parquet row sanity.

7. **Register the new reporter in [`CATALOG.yaml`](../../../CATALOG.yaml)** at the repo root, with the appropriate `name`, `image`, `source`, `source_url`, `status`, `target`, `owner`, and `description`.

The template itself is **not** registered in `CATALOG.yaml` and is not referenced by any Coworld manifest — it is scaffolding, not a deployable reporter.

## Running the template locally

```bash
COGAME_EPISODE_BUNDLE_URI=file:///path/to/bundle.zip \
COGAME_REPORT_URI=file:///path/to/report.zip \
python summarizer.py
```

Both `file://` and `http(s)://` URIs are supported (via the SDK's I/O layer). The template's smoke harness builds a synthetic bundle with `smoke/make_bundle.py`; use that as the starting point if you need an example bundle zip.

## Building the image

```bash
./build.sh                              # builds summarizer-template:latest for linux/amd64
IMAGE=summarizer-template:dev ./build.sh
PLATFORM=linux/arm64 ./build.sh         # local-only platform override
```

The template image is built only so the smoke test can exercise the same containerized flow a concrete reporter uses; it is not pushed to any registry.

## Tests

```bash
uv run pytest reporters/templates/summarizer_template/tests/ -v
```

Locks the contract: the template runs against a synthetic in-memory bundle, the output zip contains `manifest.json` and `summary.md`, the in-zip `manifest.json` parses as `reporter_sdk.OutputManifest` with `render="summary.md"` and `event_log=None`, the render target points at an existing non-empty entry, and every zip entry uses the SDK's pinned mtime sentinel.

The test suite is intentionally thin — the template's whole purpose is to be specialized, so pinning more than the contract just becomes drag for whoever derives a real reporter from it.

### Containerized smoke test

```bash
./smoke.sh                  # builds + runs the image against a synthetic bundle
IMAGE=summarizer-template:dev ./smoke.sh
```

Builds the image, hand-builds a synthetic bundle zip via `smoke/make_bundle.py`, runs the container, and asserts the output zip's `manifest.json` parses, `reporter_id` is set, and `render` (if declared) points at an existing renderable entry. The smoke harness produces a **valid-shape but stub-content** output zip — that is exactly what a game-agnostic template can demonstrate; meaningful artifacts come from specialization.

## What lives where

| Path | Purpose |
| --- | --- |
| [`summarizer.py`](summarizer.py) | Runnable entrypoint. Reads the bundle, builds the stub output zip, writes it. |
| [`Dockerfile`](Dockerfile) | Builds the template image; installs the SDK from the build context. |
| [`Dockerfile.dockerignore`](Dockerfile.dockerignore) | Allowlist that keeps the build context to just the SDK + the template's entrypoint. |
| [`build.sh`](build.sh) | Wrapper around `docker build` with `--platform linux/amd64`. |
| [`smoke.sh`](smoke.sh) | End-to-end containerized smoke against a synthetic bundle. |
| [`smoke/make_bundle.py`](smoke/make_bundle.py) | Hand-builds the synthetic bundle zip the smoke run consumes. |
| [`tests/`](tests/) | In-process contract tests (thin; see above). |

For the broader rationale on templates — when to add one, when to migrate primitives into the SDK instead, what belongs in a template vs a concrete reporter — see [`../README.md`](../README.md).
