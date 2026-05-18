# Vendored Native Dependency

The Among Them SDK depends on the Nim-built `evidencebot_v2` shared library
for its FFI core. To make the SDK installable from this repo without the
upstream `bitworld` monorepo, the build artifact is vendored here.

## Layout

```
vendor/
├── README.md           ← this file
├── native/
│   ├── libevidencebot_v2.dylib       ← prebuilt for arm64-darwin
│   └── libevidencebot_v2.dylib.abi   ← ABI version stamp ("1")
└── nim_source/
    ├── build_evidencebot_v2.py       ← upstream build script (kept for inspection)
    ├── evidencebot_v2.nim            ← Nim entry point
    └── evidencebot_v2/               ← Nim modules used by the entry point
```

The SDK's `ffi.py` looks up the shared library here by default. Override
with the `AMONG_THEM_PLAYERS_DIR` environment variable to point at a
different directory containing `libevidencebot_v2.{dylib,so,dll}` plus its
`.abi` stamp file.

## Platform support out of the box

| Platform              | Status                                         |
| --------------------- | ---------------------------------------------- |
| macOS arm64           | Works zero-config (vendored `.dylib`).         |
| macOS x86_64          | Needs rebuild — see "Rebuilding" below.        |
| Linux x86_64 / arm64  | Needs rebuild — vendored only `.dylib` ships.  |
| Windows               | Needs rebuild — vendored only `.dylib` ships.  |

Vendoring a single binary keeps the wheel small. Multi-platform binaries
should be added under `native/` next to the existing `.dylib` (the loader
selects by `platform.system()`).

## Rebuilding

`build_evidencebot_v2.py` and the Nim sources here are sufficient to read
and review the Nim policy, but **rebuilding the shared library requires
the full `bitworld` monorepo**. The build needs:

* `nim 2.2.4` on `PATH` (the script can fetch it via `nimby`).
* `common/`, `src/bitworld`, and `nimby.lock` from the bitworld checkout.
  The build script imports these as `--path:` arguments and uses
  `nimby.lock` to pin transitive packages such as `pixie`, `mummy`, etc.

If you have a bitworld checkout, the simplest path is:

```bash
cd /path/to/bitworld
python among_them/players/build_evidencebot_v2.py
cp among_them/players/libevidencebot_v2.{dylib,so,dll}* \
   /path/to/this/sdk/vendor/native/
```

If you only have this SDK checked out, set
`AMONG_THEM_PLAYERS_DIR=/path/to/your/own/players` to point the loader at
your own build output. Reproducing the full Nim build from this directory
alone is intentionally out of scope — the transitive Nim package surface
is large and the bitworld monorepo is the canonical source.
