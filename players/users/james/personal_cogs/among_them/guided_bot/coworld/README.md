# guided_bot public Among Them image

The current public Among Them submission guide is
<https://softmax.com/play_amongthem.md>. It uses a standalone linux/amd64 Docker
image uploaded with the Coworld v2 CLI, not the older Python policy bundle path
and not the legacy `cogames submit --season among-them` surface.

This directory contains guided_bot's image entrypoint. The Dockerfile builds
`libguidedbot.so`, installs the small Python bridge, and exposes
`/bin/guided_bot`.

## Runtime Contract

The hosted runner starts the image with:

```text
COGAMES_ENGINE_WS_URL=ws://<game-service>:8080/player?slot=<slot>&token=<token>
```

The raw Among Them player protocol is:

- receive binary websocket frames, one packed 128x128 4-bit screen per message
  (`8192` bytes);
- maintain the local 4-frame stack expected by `AmongThemPolicy`;
- send one input packet per frame: packet kind `0`, then one button-mask byte.

`policy_player.py` also still supports the generic JSON `coworld.player.v1`
protocol for older/local Coworld adapters. In auto mode it reads the first
message and chooses raw BitWorld when the first message is binary.

## Build

Run from `personal_cogs/among_them`:

```sh
export IMAGE=jamesboggs-guided-bot-public:$(date +%Y%m%d-%H%M%S)

docker buildx build \
  --platform linux/amd64 \
  -t "$IMAGE" \
  --load \
  -f guided_bot/coworld/Dockerfile \
  .

docker run --rm --platform linux/amd64 "$IMAGE" /bin/guided_bot --help
```

## Upload And Submit

Use the Metta checkout's Coworld v2 CLI:

```sh
cd /Users/jamesboggs/coding/metta
uv run softmax login
uv run coworld leagues
uv run coworld download among_them --output-dir ./coworld
uv run python -m json.tool ./coworld/coworld_manifest.json

# Optional but preferred before upload: local Coworld smoke episode.
uv run coworld run-episode ./coworld/coworld_manifest.json "$IMAGE"

export POLICY_NAME=jamesboggs-guided-bot-public-$(date +%Y%m%d-%H%M%S)

uv run coworld upload-policy "$IMAGE" \
  --name "$POLICY_NAME" \
  --use-bedrock \
  --secret-env GUIDED_BOT_BEDROCK_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0

uv run coworld submit "$POLICY_NAME:v1" \
  --league league_494db37d-d046-4cba-a99a-536b1439262f
uv run coworld submissions --policy "$POLICY_NAME:v1" --json
uv run coworld memberships --mine --policy "$POLICY_NAME:v1" --json
```

The website guide says to submit through the Among Them Daily league page in
Observatory v2. The local Coworld CLI also exposes `coworld submit POLICY
--league LEAGUE_ID`, which enters the uploaded policy version into that same
v2 league.

`coworld upload-policy --use-bedrock` stores `USE_BEDROCK=true` for the policy.
Repeated `--secret-env KEY=VALUE` flags store additional policy secret env;
guided_bot uses `GUIDED_BOT_BEDROCK_MODEL` when present and otherwise falls
back to its compiled Bedrock default.

Docker 29 on macOS can push the ECR layers and then fail the final manifest
publish with a registry `HEAD` 403. The successful workaround on 2026-05-12 was
to use the same temporary upload credentials and publish the linux/amd64 OCI
manifest via `aws ecr put-image`, then call the Coworld image-complete and
policy-complete APIs. The current Coworld uploader still shells out to plain
`docker push`, so this failure mode may recur.

For the full pain-point report from the 2026-05-12 submission, see
[`SUBMISSION_PAIN_POINTS_2026-05-12.md`](SUBMISSION_PAIN_POINTS_2026-05-12.md).

## Submission Log

| Date | Policy version | Season | Build / upload result | Submission result |
|---|---|---|---|---|
| 2026-05-11 | `jamesboggs-guided-bot-coworld-20260511-142920:v1` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 Docker build passed; smoke verified `/bin/guided_bot`; upload completed with the ECR manifest workaround | placed as `lpm_ed695228-4241-4c28-b16c-c9372462b133`; score pending |
| 2026-05-12 | `jamesboggs-guided-bot-public-20260512-152010:v1` | legacy `among-them` only | linux/amd64 `docker buildx build --load` passed; `/bin/guided_bot --help` smoke passed; image `img_c95d02c7-56ee-40a9-977f-b9d01a215de0` ready with digest `sha256:8da0ec28fb35ec43cd7084e2bc58d5f62628ac5fb8c6a7a91b021e071c8a6771` | policy id `de944167-b1ac-40d7-88ea-8c5495896795`; submitted to legacy `competition`, but Coworld v2 showed no Among Them Daily submission for this policy |
| 2026-05-13 | `jamesboggs-guided-bot-coworld-20260513-095131:v1` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 `docker buildx build --load` passed; `/bin/guided_bot --help` smoke passed; `coworld run-episode` against `among_them:0.1.11` completed; standard upload hit Docker 29 ECR `HEAD` 403 and completed via `crane`; image `img_b386faae-79ef-4f9e-81d9-32787588c736` digest `sha256:4fd6d88da39c74186fc8a0d5aef954b32eceeeb5eda1b98a4ffa20d907b16c54`; Bedrock env stored | policy id `cdac788e-8ae0-4b07-81ca-8bd45a84ebad`; submitted as `sub_9414c5e8-1e44-461b-a497-51b59cfa32d5`; placed as active champion `lpm_290240c5-2eea-4648-b479-d428a22e43d2` in `div_334593c6-da90-4651-98c7-606573ea1474` |
| 2026-05-14 | `jamesboggs-guided-bot-coworld-20260514-092239:v1` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | First submission with `GUIDED_BOT_TRACE_LEVEL=full` (bumped from `events` in Dockerfile to diagnose the early-websocket-close pattern seen in round 379 logs); linux/amd64 `docker buildx build --load` passed; `/bin/guided_bot --help` smoke passed; `coworld run-episode` against `among_them:0.1.14` completed with `[trace:decisions\|modes\|snapshots\|events]` lines (~315 per agent log, up from ~11 at events-only); standard upload succeeded on first try with no Docker 29 ECR 403 workaround needed; image `img_bfb9eadc-1ad7-4e48-ba9e-99df6a0d1938` (local manifest-list digest `sha256:a1fb7c731d3ad0deb5811d284d1ab9e93cbf23181e425b0bac0ffbbdbab50820`); Bedrock env stored | policy version id `96327238-9a16-484f-843b-ab735bc97d29`; submitted as `sub_ed4f9d4d-b9cb-4f50-a139-e9b422d475c4`; placed as active champion `lpm_5324f856-8a27-49e7-84c7-3a7efd0e9cd2` in `div_334593c6-da90-4651-98c7-606573ea1474` |
