# Python Infinite Blocks Stacker

Python clone of the symbolic Infinite Blocks `stacker` agent.

The original Nim agent lives at:

```text
~/coding/agent-policies/policies/symbolic/bitworld/infinite-blocks/stacker/stacker.nim
```

This clone preserves the original global-protocol stacker path and adds an
auto fallback for the current `~/coding/bitworld/infinite_blocks` server, which
serves packed 128x128 player framebuffers on `/player` but does not currently
serve `/global`.

## Run Locally

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
./stacker.py --address localhost --port 2000
```

Useful flags:

```sh
./stacker.py --mode global --url ws://localhost:2000/player
./stacker.py --mode framebuffer --address localhost --port 2000
./stacker.py --max-steps 300 --debug-interval 30
```

`COGAMES_ENGINE_WS_URL` is honored when present, matching the original stacker
agent.

## Docker

```sh
docker build -t bitworld-py-stacker:latest .
docker run --rm bitworld-py-stacker:latest
```

The manifest entrypoint is `/usr/local/bin/stacker`.
