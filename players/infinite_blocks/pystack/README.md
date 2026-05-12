# Pystack

Python clone of the symbolic Infinite Blocks `stacker` agent, packaged as
`pystack`.

The original Nim agent lives at:

```text
~/coding/agent-policies/policies/symbolic/bitworld/infinite-blocks/stacker/stacker.nim
```

This clone preserves the original global-protocol behavior and adds an
auto fallback for the current `~/coding/bitworld/infinite_blocks` server, which
serves packed 128x128 player framebuffers on `/player` but does not currently
serve `/global`.

## Run Locally

Commands in this section assume `infinite_blocks/pystack` as the current
directory.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
./pystack.py --address localhost --port 2000
```

Useful flags:

```sh
./pystack.py --mode global --url ws://localhost:2000/player
./pystack.py --mode framebuffer --address localhost --port 2000
./pystack.py --max-steps 300 --debug-interval 30
```

`COGAMES_ENGINE_WS_URL` is honored when present, matching the original
agent.

## Docker

The manifest image is:

```text
ghcr.io/jboggsy/bitworld-pystack:latest
```

Local build and smoke test:

```sh
docker build -t bitworld-pystack:latest .
docker run --rm bitworld-pystack:latest
```

The manifest entrypoint is `/usr/local/bin/pystack`.
