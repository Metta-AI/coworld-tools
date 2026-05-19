# Among Them Starter

This is the canonical source for the bundled `ivotewell` starter player used by
the uploaded Among Them Coworld.

The player is a Nim screen-reading policy. It connects to the Bitscreen player
websocket, localizes the screen, navigates to tasks, holds the action button to
complete them, reports bodies, and votes from observed evidence.

## Files

- `ivotewell.nim`: player source.
- `Dockerfile`: builds the player from a BitWorld source tree.
- `coplayer_manifest.json`: player metadata.

## Build Context

The Dockerfile expects a BitWorld checkout as its build context because the
player imports game/runtime modules from `among_them/` and `common/`.

From a BitWorld checkout:

```bash
docker build --platform=linux/amd64 \
  -f among_them/players/ivotewell/Dockerfile \
  -t amongthemstarter:latest \
  .
```

The metta Coworld bundle upload script stages this source into the matching
BitWorld path before building and uploading the canonical Among Them Coworld.

For public league participation, use the Coworld guide:
<https://softmax.com/play_amongthem.md>.
