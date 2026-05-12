# guided_bot Coworld / BitWorld policy image

The private daily Among Them flow expects a Coworld policy upload: a Docker
image-backed policy version with a `container_image_id`. Do not use
`guided_bot/cogames/ship.sh` for that path; it creates the older zip/S3 policy
format.

The same image also fits BitWorld's `coplayer_manifest.json` tournament runner
contract: the manifest points at `/bin/guided_bot`, and the runner may invoke it
as:

```sh
/bin/guided_bot --address:host.docker.internal --port:2000 \
  --name:guided_bot-t1 --slot:0 --token:...
```

The player manifest for that path is
`guided_bot/coplayer_manifest.json`. Update its `image_uri` if you push the
image under a different registry/name.

Build from the `among_them/` directory:

```sh
export IMAGE=ghcr.io/jamesboggs/bitworld-guided-bot:latest

docker build --platform=linux/amd64 \
  --provenance=false \
  -f guided_bot/coworld/Dockerfile \
  -t "$IMAGE" \
  .
```

Upload the image-backed policy without submitting it to a season:

```sh
export POLICY_NAME=$USER-guided-bot-coworld-$(date +%Y%m%d-%H%M%S)

PYTHONPATH=/Users/jamesboggs/coding/metta/packages/coworld/src:/Users/jamesboggs/coding/metta/packages/softmax-cli/src \
  /Users/jamesboggs/coding/metta/.venv/bin/python -m coworld upload-policy "$IMAGE" \
  --name "$POLICY_NAME"
```

Then submit that uploaded policy version through the private Softmax website. To
verify a policy upload, query the policy name you passed to `--name`; the latest
version must have a non-null `container_image_id`.

The Coworld policy upload API currently does not expose the older cogames
`--use-bedrock` / `--secret-env` flags. Without runtime credentials, guided_bot
falls back to non-LLM behavior instead of failing startup.

On 2026-05-11, Docker 29 on macOS pushed the ECR layers but failed the
standard `cogames coworld upload-policy` path with a registry `HEAD` 403
when writing the final manifest. The accepted workaround was to push the
`docker image save` tarball with `gcr.io/go-containerregistry/crane:debug`
using the same temporary ECR credentials from `/v2/container_images/upload`,
then call `/v2/container_images/upload/complete` and
`/stats/policies/docker-img/complete`.

Do not reuse the earlier `jamesboggs-guided-bot-coworld-20260511-120701`
ECR/local tags; later smoke checks found those image tags lacked
`/bin/guided_bot`. The verified 2026-05-11 upload was
`jamesboggs-guided-bot-coworld-20260511-142920:v1`, with
`container_image_id=img_e621b15a-84f0-4230-8a3c-37990afd7a35`,
policy version `29c89f00-03c2-4a04-aa87-35f1b56a40a2`, and Among Them Daily
submission `sub_3cc0fa25-c436-4b46-a4a3-f2b1a06ebad1` placed as
`lpm_ed695228-4241-4c28-b16c-c9372462b133`.

## Runtime

`/bin/guided_bot` is a tiny wrapper around `policy_player.py`.

The default runtime protocol is auto-detected:

- BitWorld/Among Them raw `/player` websocket: binary 8192-byte 4bpp frames in,
  binary input/chat packets out. This is the protocol described by
  `~/coding/bitworld/docs/player_protocol_spec.md` and used by
  `games_server/tournament_server.nim`.
- JSON `coworld.player.v1`: `player_config` / `observation` messages in,
  `action_index` / `action_name` responses out. This remains supported for
  generic Coworld adapters.

The Dockerfile compiles `libguidedbot.so` during image build. The runtime image
keeps the source tree only so the existing wrapper can locate its baked data and
ABI stamp; it should not rebuild the Nim library at tournament startup.
