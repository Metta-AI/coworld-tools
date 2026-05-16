# COGAMES_CLI.md

The legacy CLI reference has been retired for this checkout's Among Them work.
The current repo-local UV project resolves public PyPI `coworld==0.1.4`.

Use the repo-local UV Coworld interface:

```sh
uv run coworld ...
```

Observed command groups from `uv run coworld --help`:

```text
leagues, divisions, results, rounds, pools, memberships, submissions, events,
episodes, episode-stats, episode-results, episode-logs, replays, replay-open,
certify, play, list, show, images, upload-coworld, download, make-policy,
upload-policy, submit, run-episode, replay, hosted-game
```

Match replacement:

```sh
uv run coworld play MANIFEST_URI [PLAYER_IMAGES]...
```

Saved validation episode:

```sh
uv run coworld run-episode MANIFEST_URI [PLAYER_IMAGES]... -o DIR
```

Use the manifest path printed by `coworld download`. Public PyPI
`coworld==0.1.4` writes directly under the requested output directory, while the
latest pulled Metta source is moving toward a cached
`<output-dir>/<coworld-id>/coworld_manifest.json` layout.

This file can be expanded into a fuller Coworld CLI reference after the next
live Coworld run.
