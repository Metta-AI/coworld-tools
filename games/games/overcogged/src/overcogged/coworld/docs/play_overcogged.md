# Play overcogged

Build the Coworld images from this repo:

```bash
docker build --platform=linux/amd64 -f Dockerfile -t coworld-overcogged-game:latest .
docker build --platform=linux/amd64 -f player/Dockerfile -t coworld-overcogged-player:latest .
```

Run locally with Coworld:

```bash
uv run --package coworld coworld play coworld_manifest.json
```

Certify the package:

```bash
uv run --package coworld coworld certify coworld_manifest.json --timeout-seconds 60
```
