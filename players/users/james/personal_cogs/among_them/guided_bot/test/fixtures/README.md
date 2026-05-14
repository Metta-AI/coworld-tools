# Fixture frames

Raw 128x128 uint8 palette-indexed frame dumps, extracted by
`test/fixtures/extract_fixtures.py` from
`among_them/modulabot/tests/fixtures_frames.npy` at guided_bot
phase 1.0. Each file is 16384 bytes, row-major.

The source path above is provenance only. The local `modulabot/` tree is
deprecated; do not inspect or refresh fixtures from it unless James
explicitly asks for modulabot-related work. Prefer new guided_bot
captures for future fixture updates.

Regenerate with:

```text
PYTHONPATH=among_them .venv/bin/python \
    among_them/guided_bot/test/fixtures/extract_fixtures.py
```
