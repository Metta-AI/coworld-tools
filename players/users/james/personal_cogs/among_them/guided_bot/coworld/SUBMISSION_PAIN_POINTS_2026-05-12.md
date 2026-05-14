# Among Them Public Submission Pain Points - 2026-05-12

This report records the operational pain points encountered while submitting
`guided_bot` with the latest public Among Them instructions:
<https://softmax.com/play_amongthem.md>.

## Correction - 2026-05-13

The 2026-05-12 run mixed two tournament surfaces. The currently correct
Among Them Daily path is the Coworld v2 CLI from the Metta checkout:

```sh
cd /Users/jamesboggs/coding/metta
uv run softmax login
uv run coworld leagues
uv run coworld download among_them --output-dir ./coworld
uv run coworld upload-policy "$IMAGE" --name "$POLICY_NAME"
uv run coworld submit "$POLICY_NAME:v1" \
  --league league_494db37d-d046-4cba-a99a-536b1439262f
```

The local Metta source for `play_amongthem.md` says to use `uv run coworld`
and the **Among Them Daily** Observatory v2 league. It explicitly says not to
use `cogames season list` for Among Them Daily because that command lists
legacy seasons. The `jamesboggs-guided-bot-public-20260512-152010:v1`
submission below was accepted by the legacy `among-them` / `competition`
surface, but Coworld v2 showed no Daily league submission for that policy.

## End State

The legacy-surface submission succeeded, but this was not a Coworld v2 Among
Them Daily submission.

- Policy version: `jamesboggs-guided-bot-public-20260512-152010:v1`
- Policy id: `de944167-b1ac-40d7-88ea-8c5495896795`
- Container image id: `img_c95d02c7-56ee-40a9-977f-b9d01a215de0`
- Container image digest:
  `sha256:8da0ec28fb35ec43cd7084e2bc58d5f62628ac5fb8c6a7a91b021e071c8a6771`
- Legacy season: `among-them`
- Pool: `competition`
- Submission check: active with `0` matches
- Leaderboard check: no filtered entry yet because the policy has not played
- Coworld v2 check: no Among Them Daily submission for this policy version

## What Worked

The public guide's image shape is correct for guided_bot.

```sh
docker buildx build \
  --platform linux/amd64 \
  -t jamesboggs-guided-bot-public:20260512-152010 \
  --load \
  -f guided_bot/coworld/Dockerfile \
  .
```

The image built successfully and the local smoke check worked:

```sh
docker run --rm --platform linux/amd64 \
  jamesboggs-guided-bot-public:20260512-152010 \
  /bin/guided_bot --help
```

The legacy `cogames` season and submission commands worked once the policy
version existed, but they targeted the wrong surface for Among Them Daily:

```sh
cogames season list
cogames season show among-them
cogames submit jamesboggs-guided-bot-public-20260512-152010:v1 --season among-them
cogames submissions --season among-them --policy jamesboggs-guided-bot-public-20260512-152010
```

## Pain Points And Broken Instructions

### 1. Stale Guide Variant Referenced A Missing Module

The guide content used during the 2026-05-12 run said to clone
`https://github.com/Metta-AI/cogames.git`, install `cogames`, then run:

```sh
PYTHONPATH=./src python -m cogames.coworld upload-policy "$IMAGE" \
  --name "$POLICY_NAME"
```

That command did not work from the public clone or the PyPI install:

```text
/private/tmp/cogames-public-amongthem-20260512/.venv/bin/python: No module named cogames.coworld
```

Verification:

- Public clone was on `main` at `6c38c63` / tag `cogames-v0.26.21`.
- `src/cogames/` in that clone did not contain `coworld`.
- PyPI installed `cogames==0.26.19`, also without `cogames.coworld`.
- `cogames upload --help` exposed the older policy-bundle uploader, not
  Docker-image `upload-policy`.

Impact: that guide variant could not be followed exactly for the upload step.
The current Metta source guide no longer uses this command; it uses
`uv run coworld upload-policy`.

Workaround used: run the newer local Coworld uploader from the local `metta`
checkout for the missing Docker-image upload step, then return to the legacy
`cogames submit` command for season entry. The second half was the mistake:
current Among Them Daily submission should stay on Coworld v2.

Recommendation: use the Coworld CLI directly:

```sh
cd /Users/jamesboggs/coding/metta
uv run coworld upload-policy --help
uv run coworld submit --help
```

### 2. Network Access Needed Explicit Escalation In Codex

Several commands failed inside the sandbox with DNS or network errors before
being rerun with network access:

- `curl https://softmax.com/play_amongthem.md`
- `uv pip install cogames`
- `cogames season list`
- `cogames season show among-them`
- `cogames submit ...`
- `cogames submissions ...`
- `cogames leaderboard ...`

Typical failure:

```text
ConnectError: [Errno 8] nodename nor servname provided, or not known
```

Impact: this is Codex-environment friction, not a Softmax guide bug. Future
agents should expect networked guide, install, auth, season, upload, and
submission commands to require explicit network approval.

### 3. `uv venv` Tried To Write Outside The Writable Sandbox

The public-guide setup command initially hit sandbox friction because `uv`
wanted to use the default cache under the user home directory.

Workaround:

```sh
env UV_CACHE_DIR=/private/tmp/uv-cache-amongthem-submit \
  uv venv .venv --python 3.12
```

The same cache override was used for `uv pip install`.

Impact: local Codex runs should set `UV_CACHE_DIR` to a writable temp directory
when creating the public guide venv in `/private/tmp`.

### 4. Legacy `among-them` Reports `Status: complete` But Still Accepted Submission

`cogames season show among-them` reported:

```text
Status: complete
Type: freeplay
Pools:
  competition: Among Them (8 players, 8 policies)
```

Despite that status, `cogames submit ... --season among-them` succeeded and
added the policy to `competition`.

Impact: `Status: complete` was confusing and made the legacy surface look
plausible. For current Among Them Daily, this status is not relevant; use
`uv run coworld leagues`, the Observatory v2 league page, and Coworld
membership/submission commands.

### 5. Docker 29 Hit ECR `HEAD` 403 After Pushing Layers

The local Coworld uploader requested a temporary ECR upload and invoked
`docker push`. Docker pushed all image layers, then failed on the final manifest
step:

```text
unknown: unexpected status from HEAD request to
https://.../manifests/sha256:083fe464262bf264150e0988d9f9460132877a708b6e9f8fe510a1425a712c38:
403 Forbidden
```

The uploader exited before calling the image-complete and policy-complete APIs.
The server showed the image row as `pending`:

```text
img_c95d02c7-56ee-40a9-977f-b9d01a215de0 status=pending
```

Impact: a failed Docker push can leave a reusable pending image row. Do not
blindly re-upload under new names until checking `coworld images`. The current
Coworld uploader still shells out to plain `docker push`, so this risk remains.

2026-05-13 recurrence: the correct Coworld v2 upload for
`jamesboggs-guided-bot-coworld-20260513-095131` hit the same `HEAD` 403 after
all layers pushed. Re-requesting the same image upload returned the pending
image row `img_b386faae-79ef-4f9e-81d9-32787588c736`; saving the
linux/amd64 image and pushing it with `crane` completed the image with digest
`sha256:4fd6d88da39c74186fc8a0d5aef954b32eceeeb5eda1b98a4ffa20d907b16c54`.
The recovered policy version `jamesboggs-guided-bot-coworld-20260513-095131:v1`
then submitted successfully to Among Them Daily as
`sub_9414c5e8-1e44-461b-a497-51b59cfa32d5` and placed as active champion
membership `lpm_290240c5-2eea-4648-b479-d428a22e43d2`.

### 6. Completing The Pending Image Failed Until The Manifest Was Published

Calling the image-complete API directly after Docker's failed push returned:

```text
400
{"detail":"Uploaded image manifest was not found"}
```

Impact: all layers were present, but the manifest tag the server expected was
not published.

### 7. `docker push --platform linux/amd64` Did Not Fix The ECR Failure

Trying to avoid the multi-platform index and attestation manifest with:

```sh
docker push --platform linux/amd64 <temporary-ecr-image-uri>
```

still failed:

```text
unknown: unexpected status from HEAD request to .../manifests/v1: 403 Forbidden
```

Impact: Docker's platform-specific push was not sufficient with Docker 29 on
macOS in this environment.

### 8. Manual ECR `put-image` Was Required

The successful workaround was:

1. Save the local image with `docker image save`.
2. Read the nested OCI index from the archive.
3. Extract the linux/amd64 image manifest digest.
4. Use the same temporary ECR credentials from `/v2/container_images/upload`.
5. Publish that linux/amd64 manifest with `aws ecr put-image`.
6. Call `/v2/container_images/upload/complete`.
7. Call `/stats/policies/docker-img/complete`.

Result:

```text
Upload complete: jamesboggs-guided-bot-public-20260512-152010:v1
Image: img_c95d02c7-56ee-40a9-977f-b9d01a215de0 status=ready
digest=sha256:8da0ec28fb35ec43cd7084e2bc58d5f62628ac5fb8c6a7a91b021e071c8a6771
```

Impact: this is the highest-risk workaround in the flow. It uses the same
server-issued upload credentials, but it bypasses the broken Docker manifest
push path. Prefer the documented `upload-policy` path whenever it works.

### 9. Docker Socket Access Needed Escalation

Docker commands from the Codex sandbox can fail with:

```text
permission denied while trying to connect to the docker API at
unix:///Users/jamesboggs/.docker/run/docker.sock
```

Impact: build, run, inspect, tag, and push commands should be expected to need
Docker escalation in this environment.

### 10. Post-submit Leaderboard Check Was Empty

The guide asks for a leaderboard check. Immediately after submission:

```text
No leaderboard entries for season 'among-them'.
```

The submissions endpoint showed the real state:

```text
competition (active): 0 matches
```

Impact: an empty filtered leaderboard immediately after submission is not a
submission failure. Check `cogames submissions` first; leaderboard entries need
matches.

### 11. Browser Launch Is Skipped In Non-interactive Sessions

After `cogames submit`, the CLI printed:

```text
Browser launch skipped: non-interactive session detected
Observatory: https://softmax.com/observatory/home
```

Impact: harmless in Codex. Use CLI status commands instead of expecting a
browser to open.

### 12. `uv run coworld` May Trigger Unrelated Workspace Rebuilds

On 2026-05-13, `uv run coworld leagues --json` from `~/coding/metta` tried to
resync the full Metta workspace and failed while building `cogames-agents`
because `nimby` reported an existing `~/.nimby/nimbylock`.

Workaround used for submission commands:

```sh
env PYTHONPATH=/Users/jamesboggs/coding/metta/packages/coworld/src:/Users/jamesboggs/coding/metta/packages/softmax-cli/src \
  /Users/jamesboggs/coding/metta/.venv/bin/python -m coworld ...
```

Impact: this is local development friction, not a Coworld API issue. The public
instructions should still say `uv run coworld`; Codex agents can use the
existing venv path when workspace sync is blocked by unrelated packages.

## Recommended Next Submission Procedure

1. Read the current Metta source guide at
   `/Users/jamesboggs/coding/metta/web/softmax.com/public/play_amongthem.md`
   or fetch <https://softmax.com/play_amongthem.md> and verify it says
   `uv run coworld`.
2. Build and smoke the image from `personal_cogs/among_them`:

   ```sh
   docker buildx build --platform linux/amd64 -t "$IMAGE" --load \
     -f guided_bot/coworld/Dockerfile .
   docker run --rm --platform linux/amd64 "$IMAGE" /bin/guided_bot --help
   ```

3. Use the Metta checkout Coworld CLI:

   ```sh
   cd /Users/jamesboggs/coding/metta
   uv run softmax login
   uv run coworld leagues
   uv run coworld download among_them --output-dir ./coworld
   uv run coworld upload-policy --help
   uv run coworld submit --help
   ```

4. Upload with Bedrock enabled for guided_bot's LLM path:

   ```sh
   uv run coworld upload-policy "$IMAGE" \
     --name "$POLICY_NAME" \
     --use-bedrock \
     --secret-env GUIDED_BOT_BEDROCK_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0
   ```

5. Submit to Among Them Daily v2:

   ```sh
   uv run coworld submit "$POLICY_NAME:v1" \
     --league league_494db37d-d046-4cba-a99a-536b1439262f
   ```

6. If Docker fails after pushing layers with an ECR `HEAD` 403:
   - query `coworld images` for a pending image row;
   - avoid duplicate policy names until the image state is known;
   - complete by publishing the linux/amd64 OCI manifest with ECR `put-image`
     only if the documented upload path remains blocked.
7. Verify in this order:

   ```sh
   uv run coworld submissions --policy "$POLICY_NAME:v1" --json
   uv run coworld memberships --mine --policy "$POLICY_NAME:v1" --json
   uv run coworld results <DIVISION_ID> --json
   ```

## Documentation Updates Made From This Run

- `guided_bot/coworld/README.md` now treats Coworld v2 as the current public
  source of truth and records the Docker 29 ECR workaround.
- `guided_bot/cogames/README.md` is marked as legacy Python-bundle tooling.
- `among_them/README.md`, `guided_bot/README.md`, `guided_bot/DESIGN.md`,
  `COGAMES.md`, and `MISSION.md` now distinguish Coworld v2 Among Them Daily
  from the legacy bundle and legacy `among-them` season paths.
