# Documentation

System-level references for building and shipping players in this repo:

- [Coworld Integration Guide](coworld-integration-guide.md) —
  developer-facing reference for the player runtime: episode lifecycle,
  environment variables the runner injects, player websocket protocol
  expectations, log/replay visibility, and the `coworld` CLI commands used
  to debug a live or finished hosted episode. Start here when building a
  new player.
- [Coworld Player Packaging Contract](coworld-player-packaging.md) —
  authoritative reference for what every `players/<game>/<policy>/build.sh`
  must produce (Docker image, `player[]` manifest snippet,
  `coplayer_manifest.json`) and the underlying Coworld upload/manifest
  requirements.

Tool-specific documentation lives with its tool. Cogbase documentation is
under `tools/cogbase/docs/` and is indexed from `tools/cogbase/README.md`.
