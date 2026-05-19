# maker_v1

> **DEPRECATED.** `maker_v1` is no longer the canonical Cogbase agent-making
> stage. New work should go into [`maker_v2`](../maker_v2/). The code below is
> preserved for short-term continuity and for any in-flight games that still
> rely on it, but it is not receiving new features and every entry point emits
> a deprecation warning. See
> [`docs/designs/maker_v1_deprecation.md`](../../docs/designs/maker_v1_deprecation.md)
> for the rationale and
> [`docs/designs/maker_v2_design.md`](../../docs/designs/maker_v2_design.md)
> for the replacement direction.

Status: deprecated. The historical implementation notes below are kept for
reference.

Historical status: early implementation. Phase 1 plan artifacts, Phase 2 symbolic agent
scaffolds, Phase 3 visual starter agents/VLM contract tooling, and Phase 4
offline visual bootstrap exist. Visual and mixed games now receive a live
`run_agent.py` when the guide proves a serializable action wire contract, such
as binary button-mask packets. The Phase 4 bootstrap can use mock labeling or
call Claude through AWS Bedrock for image fixtures, then generate a
label-derived starter policy. Maker can also run a local smoke test against an
already-running server or a user-supplied server command. Automatic run-config
discovery, deterministic parser generation, and submission packaging are not
implemented yet.

`maker_v1` is the next meta-pipeline stage after `guide_v1`. It consumes
generated guide bundles and prefers `guide_contract.json` when present. That
machine-readable contract is the stable handoff for observation surface,
observation encoding hints, action candidates, action wire serialization, and
runtime notes. Markdown extraction remains as a fallback for older or partial
guide bundles, but new Guide output should not require Maker to parse prose in
exactly the same way every time. In the current slice, Maker produces:

- `maker_manifest.json`
- `AGENT_BUILD_PLAN.md`
- `visual_bootstrap/play_card.md`
- `visual_bootstrap/vlm_request_schema.json`
- `visual_bootstrap/vlm_schema.json`
- `agent/README.md`
- `agent/perception/decoder_spec.json`
- `agent/perception/DECODER_GENERATION_TASK.md`
- `agent/perception/decoder.py` and generated decoder tests
- `agent/framework_bootstrap.py`, `agent/cyborg_agent.py`,
  `agent/protocol.py`, `agent/policy.py`, `agent/run_agent.py`, and
  `agent/tests/` for symbolic-primary games
- `agent/framework_bootstrap.py`, `agent/cyborg_agent.py`,
  `agent/protocol.py`, `agent/policy.py`, `agent/run_agent.py`,
  `agent/frame_store.py`, `agent/vlm_client.py`, `agent/run_visual_shell.py`,
  and `agent/tests/` for visual-primary or mixed/alternate games
- `Dockerfile` and `.dockerignore` at the bundle root that wrap
  `agent/run_agent.py` into a Coworld-compatible player image
- `visual_bootstrap/frames/`, `visual_bootstrap/labels/`,
  `visual_bootstrap/decoded_frames/`, `visual_bootstrap/cache/`, and
  `visual_bootstrap/runs/` when `--visual-bootstrap` is run
- `agent/policy_from_labels.py` and `agent/POLICY_BOOTSTRAP.md` when
  `--build-policy-from-labels` is run
- `smoke_tests/runs/`, `smoke_tests/logs/`, and `smoke_tests/live_runs/` when
  `--smoke-test` is run

The generated bundle is shaped to ship through the
[Coworld CLI](https://github.com/Metta-AI/metta/tree/main/packages/coworld):

```bash
docker build --platform=linux/amd64 -t <game>-player:latest .
uv run coworld run-episode ./coworld/coworld_manifest.json <game>-player:latest
uv run coworld upload-policy <game>-player:latest --name <game>-player
uv run coworld submit <game>-player --league league_...
```

`agent/run_agent.py` is the container entrypoint. It reads
`COGAMES_ENGINE_WS_URL` from the runner's env, connects to the player
websocket, plays the episode, and exits. `agent/framework_bootstrap.py`
records host-absolute paths to the Cyborg framework at generation time, so
the generated `Dockerfile` documents how to vendor or pip-install
`players_lib` into the image before building. Coworld manifest ingestion
and starter-policy template seeding (`coworld make-policy`) are listed as
not-yet-implemented in `maker_manifest.json` and are tracked for future
slices.

The full design continues from these artifacts toward stronger baseline agents.
For visual games, that means first generating a game-specific decoder from
guide/source evidence, then using a schema-bound VLM bootstrap loop only long
enough to generate deterministic perception fixtures, parsers, and tests.

The canonical design is
[`../../docs/designs/maker_v1_design.md`](../../docs/designs/maker_v1_design.md).

## Usage

```bash
# From this directory:
# cd testbed/maker_v1

python generate_agent.py ../guide_v1/output/paint_arena \
  --output-dir ./output/paint_arena \
  --plan-only
```

`--plan-only` is retained for compatibility; the command always emits the
currently implemented artifact set. For symbolic-primary games, that includes a
starter agent scaffold. For visual or mixed games with a proven action wire
contract, that includes a conservative live starter agent that records frames,
decodes observations when possible, chooses simple movement actions, and sends
only protocol-serialized actions. Generated live runners use
`agent/cyborg_agent.py` to build a small Cyborg `AgentRuntime` around
game-specific percept, belief, mode, strategy, and action-resolution functions;
`policy.py` and `protocol.py` remain small helpers for policy iteration and
serialization tests.
`--game-source <path>` may be provided to record the original game source path
in the generated manifest.
`--agent-framework-dir <path>` may be provided for an explicit compatibility
experiment with another Cyborg framework checkout. If omitted, Maker uses
`src/players_lib/coborg` from this repository. For runnable
symbolic or visual scaffolds, Maker validates that the selected framework source
root imports `players_lib.coborg` and exports the API used by
`agent/cyborg_agent.py` before writing output artifacts.

The generated `maker_manifest.json` records the consumed guide bundle hash,
`guide_contract_hash`, `guide_contract_schema_version`, and
`agent_framework`. When no `guide_contract.json` is present, the manifest marks
`markdown_contract_fallback` instead of `guide_contract_ingestion`.

Run offline visual bootstrap over captured frame/message files:

```bash
python generate_agent.py ../guide_v1/output/among_them \
  --output-dir ./output/among_them \
  --visual-bootstrap \
  --frames-dir ./seed_frames/among_them \
  --decode-observations \
  --vlm-provider bedrock \
  --build-policy-from-labels \
  --vlm-budget 25
```

Run a local smoke test against an already-running server:

```bash
python generate_agent.py ../guide_v1/output/among_them \
  --output-dir ./output/among_them \
  --smoke-test \
  --agent-url 'ws://127.0.0.1:2000/player?name=maker_smoke' \
  --agent-max-frames 25 \
  --smoke-timeout 30
```

Or let Maker start the server first:

```bash
python generate_agent.py ../guide_v1/output/among_them \
  --output-dir ./output/among_them \
  --smoke-test \
  --server-command 'python path/to/server.py --port 2000' \
  --server-cwd /path/to/game \
  --health-url http://127.0.0.1:2000/healthz \
  --agent-url 'ws://127.0.0.1:2000/player?name=maker_smoke'
```

The smoke harness writes a JSON report under `smoke_tests/runs/`, stores server
logs when it launches the server, and stores live agent frame captures when the
generated runner supports `--output-root`.

Implemented VLM providers:

- `--vlm-provider mock`: deterministic, no API key, no network calls.
- `--vlm-provider bedrock`: calls AWS Bedrock Converse with a Claude model via
  `boto3`, using the local AWS credential chain. Override the default model with
  `MAKER_V1_BEDROCK_MODEL_ID` and the region with `MAKER_V1_BEDROCK_REGION` if
  needed. The default model/profile id is
  `us.anthropic.claude-sonnet-4-20250514-v1:0`.

The Bedrock provider requires PNG, JPEG, GIF, or WebP image bytes. If
`--frames-dir` contains raw observations, pass `--decode-observations` so
`agent/perception/decoder.py` converts them into image fixtures before VLM
labeling. From a clean checkout, run Bedrock commands through `uv run python` so
the `boto3` dependency is available. Direct `--vlm-provider openai` and
`--vlm-provider anthropic` adapters remain future work. `--update-parsers`
remains a reserved flag and currently fails fast.

## Artifact Boundary

Reusable generator code belongs directly under this directory, for example
`maker_v1/` and `generate_agent.py`.

Generated game-specific outputs must go under `output/<game>/`. Those outputs
may include code, tests, prompts, fixtures, VLM labels, parser tasks, and final
agent packages, but they are artifacts produced by `maker_v1`, not part of the
toolkit itself.
