"""Parity rig for the among-them-coborg perception port.

Two pieces live here:

- ``fixtures/`` -- 10 checked-in ``.bin`` frames plus their JSON sidecars.
  The ``.bin`` files are byte-identical copies of the upstream
  ``guided_bot/test/fixtures/``; the sidecars are emitted by the Nim
  oracle dumper at ``extract_nim_oracle/`` and serve as ground truth.

- ``run_parity.py`` -- walks the fixture set, runs each ported Python
  perception kernel against every fixture, and compares the result to
  the sidecar. Surfaces a structured diff on mismatch. Also re-used by
  ``tests/test_perception_parity.py`` as the canonical CI parity gate.

S2 first pass covers ``frame`` + ``sprite_match`` only. S3 and S4 widen
the harness as additional perception modules are ported.
"""
