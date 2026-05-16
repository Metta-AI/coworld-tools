# COGAMES.md

This repo no longer uses the legacy run or bundle workflow for Among Them.

## Current Direction

Among Them work should use Coworld through a repo-local UV project:

```sh
uv run coworld ...
```

Do not fall back to old local run scripts or a local Metta checkout.

## Coworld Tasks To Support

- list leagues and submissions;
- download the Among Them Coworld manifest;
- run a local Coworld match with `uv run coworld play MANIFEST_URI
  [PLAYER_IMAGES]...`;
- run a saved validation episode with `uv run coworld run-episode MANIFEST_URI
  [PLAYER_IMAGES]... -o DIR`;
- upload a policy image;
- submit a policy version to Among Them Daily;
- inspect rounds, episodes, logs, and results.

## Among Them Boundary

Use the docs under `among_them/guided_bot/coworld/` for operational details.
Do not add legacy bundle, local server, hosted-play, or direct old CLI
instructions back into this file.
