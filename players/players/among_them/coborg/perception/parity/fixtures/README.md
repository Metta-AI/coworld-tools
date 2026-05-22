# Perception parity fixtures

The 10 `.bin` files in this directory are checked-in 128×128 palette-index
frames captured from a real Among Them game. They are the parity oracle for
the perception port: every Python perception module under
`players/among_them/coborg/perception/` must, on each of these inputs, produce
the same output as the upstream Nim implementation at
`users/james/personal_cogs/among_them/{common,guided_bot}/perception/`.

## Provenance

These are byte-identical copies of the fixtures shipped with the upstream
`guided_bot` test suite. Source:

    users/james/personal_cogs/among_them/guided_bot/test/fixtures/*.bin

Copied verbatim into this checkout so the coborg tree is self-contained per
`users/james/personal_cogs/AGENTS.md`. The set is 164 KB total.

## Format

Each file is **16 384 bytes** = 128 × 128 × 1 byte/palette-index, row-major.
This is the **unpacked** representation, not the 4-bpp packed wire format
BitWorld serves over `bitscreen_v1` (which is 8 192 bytes per frame). The
upstream `guided_bot` tests load these files directly into a `seq[uint8]` of
length `FrameLen` (== 16 384) and skip the unpacker; the port mirrors that.

`perception/frame.py` covers pack ⇄ unpack round-trip in its own unit tests
using synthetic packed buffers and these fixtures as a reference for the
unpacked form.

## Phase coverage

| File                            | Game phase             |
|---------------------------------|------------------------|
| `interstitial_0.bin`            | Interstitial (round 0) |
| `interstitial_5.bin`            | Interstitial (early)   |
| `interstitial_100.bin`          | Interstitial (later)   |
| `gameplay_131.bin`              | Gameplay               |
| `gameplay_150.bin`              | Gameplay               |
| `gameplay_200.bin`              | Gameplay               |
| `gameplay_274.bin`              | Gameplay               |
| `voting_real_1432.bin`          | Voting screen          |
| `voting_real_1500.bin`          | Voting screen          |
| `gameover_crew_wins_real.bin`   | Game over (crew win)   |

## JSON sidecars

Each `<name>.bin` is paired with a `<name>.json` sidecar emitted by the Nim
oracle dumper at `perception/parity/extract_nim_oracle/`. The sidecar records
the percept fields the upstream Nim pipeline produces for that frame, and is
the table the Python parity harness asserts against. Sidecars are checked in
and regenerated with a single `nim c -r` invocation; see the dumper's own
README for the schema and regen procedure.

The first-pass sidecar schema (S2 stack entry) covers only `frame` and
`sprite_match` fields. Subsequent stack entries (S3, S4) widen the schema as
new percept modules are ported.

## Adding fixtures

The PLAN's expectation is that the existing 10 fixtures span the gameplay
phases the parity rig needs. If a percept code path turns out to be uncovered,
add fixtures via the optional opt-in `perception/parity/capture_fixtures.py`
(not yet implemented — only land it if needed). Per
`users/james/personal_cogs/AGENTS.md`, capture must happen *inside* a real
`uv run coworld play` session, never via a parallel non-Coworld run path.
