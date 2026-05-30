"""Shared primitives for Coworld reporter implementations.

Encodes the canonical reporter contract — defined in metta's
``packages/coworld/src/coworld/docs/roles/reporter.md`` and restated
locally in ``docs/REPORTER_DESIGN.md`` — once, in one importable place.
Concrete reporters (under ``reporters/<coworld>/``) and the summarizer
template (under ``reporters/templates/``) consume this package so they
do not each re-derive the bundle reader, the deterministic zip writer,
the in-zip ``manifest.json`` writer, the ``(ts, player, key, value)``
event-log schema, or the URI I/O surface.

The public surface is everything re-exported below. Submodules
(``io``, ``bundle``, ``zip_writer``, ``event_log``, ``output_manifest``)
exist for code organization; importers should reach for symbols via
``from reporter_sdk import X`` rather than the submodule paths so the
submodule layout can evolve.
"""

from .bundle import BundleInnerManifest, BundleReader
from .event_log import EVENT_LOG_SCHEMA, write_events_parquet
from .io import (
    ReporterInputs,
    load_reporter_inputs,
    read_json,
    read_uri,
    write_uri,
)
from .output_manifest import (
    EVENT_LOG_EXTENSIONS,
    RENDERABLE_EXTENSIONS,
    TRACE_EXTENSIONS,
    OutputManifest,
    build_report_zip,
)
from .zip_writer import MTIME_SENTINEL, stable_json, write_deterministic_zip

__all__ = [
    "EVENT_LOG_EXTENSIONS",
    "EVENT_LOG_SCHEMA",
    "MTIME_SENTINEL",
    "RENDERABLE_EXTENSIONS",
    "TRACE_EXTENSIONS",
    "BundleInnerManifest",
    "BundleReader",
    "OutputManifest",
    "ReporterInputs",
    "build_report_zip",
    "load_reporter_inputs",
    "read_json",
    "read_uri",
    "stable_json",
    "write_deterministic_zip",
    "write_events_parquet",
    "write_uri",
]
