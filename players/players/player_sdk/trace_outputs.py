from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any, Protocol, TextIO

from players.player_sdk.trace import MetricSample, MetricsSink, NullMetricsSink, TraceEvent, TraceSink

TraceFilter = Callable[[TraceEvent], bool]

DEFAULT_TRACE_OUTPUTS = "jsonl@stderr"
TRACE_OUTPUTS_ENV_SUFFIX = "_TRACE_OUTPUTS"
METRICS_ENV_SUFFIX = "_METRICS"


class TelemetryWriter(Protocol):
    """Common writer interface for trace and metric records."""

    def write_record(self, record: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class TraceOutputSpec:
    """One telemetry output target.

    Syntax is ``format@destination``. Supported formats are ``jsonl``, ``json``,
    ``csv``, and ``parquet``. Supported destinations are ``stderr``, ``stdout``,
    ``file:<path>``, and ``artifact[:path/in/zip]``.
    """

    format: str
    destination: str
    target: str | None = None

    @classmethod
    def parse(cls, raw: str) -> TraceOutputSpec:
        token = raw.strip()
        if not token:
            raise ValueError("empty trace output spec")
        if "@" not in token:
            raise ValueError(f"trace output spec must use format@destination: {raw!r}")
        raw_format, raw_destination = token.split("@", 1)
        fmt = _normalize_format(raw_format)
        destination, target = _parse_destination(raw_destination)
        return cls(format=fmt, destination=destination, target=target)


class TraceOutputs:
    """Context manager that owns configured trace and metric sinks.

    ``trace_sink`` and ``metrics_sink`` can be passed directly to
    :class:`players.player_sdk.AgentRuntime` and strategy runners. Outputs may
    stream to stderr/stdout/files and/or be bundled into the Coworld player
    artifact zip on close.
    """

    def __init__(
        self,
        writers: Iterable[TelemetryWriter],
        *,
        event_filter: TraceFilter | None = None,
        metrics_enabled: bool = False,
        artifact_bundle: _ArtifactBundle | None = None,
        fail_on_close_error: bool = False,
    ) -> None:
        self._writers = tuple(writers)
        self._artifact_bundle = artifact_bundle
        self._fail_on_close_error = fail_on_close_error
        self._closed = False
        self.errors: list[Exception] = []
        self.trace_sink: TraceSink = _FanoutTraceSink(self._writers, event_filter=event_filter)
        self.metrics_sink: MetricsSink = _FanoutMetricsSink(self._writers) if metrics_enabled else NullMetricsSink()

    @classmethod
    def from_env(
        cls,
        *,
        prefix: str,
        event_filter: TraceFilter | None = None,
        metrics_enabled: bool | None = None,
        artifact_upload_env: str = "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL",
        default_outputs: str = DEFAULT_TRACE_OUTPUTS,
        env: dict[str, str] | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> TraceOutputs:
        source = os.environ if env is None else env
        raw_outputs = source.get(f"{prefix}{TRACE_OUTPUTS_ENV_SUFFIX}", default_outputs)
        specs = parse_trace_output_specs(raw_outputs)
        if metrics_enabled is None:
            metrics_enabled = _truthy(source.get(f"{prefix}{METRICS_ENV_SUFFIX}", ""))
        return cls.from_specs(
            specs,
            event_filter=event_filter,
            metrics_enabled=metrics_enabled,
            artifact_upload_url=source.get(artifact_upload_env),
            stdout=stdout,
            stderr=stderr,
        )

    @classmethod
    def from_specs(
        cls,
        specs: Iterable[TraceOutputSpec],
        *,
        event_filter: TraceFilter | None = None,
        metrics_enabled: bool = False,
        artifact_upload_url: str | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> TraceOutputs:
        writers: list[TelemetryWriter] = []
        artifact_bundle: _ArtifactBundle | None = None
        for spec in specs:
            if spec.destination == "artifact":
                if artifact_upload_url is None:
                    raise ValueError("artifact trace output requires COWORLD_PLAYER_ARTIFACT_UPLOAD_URL")
                if artifact_bundle is None:
                    artifact_bundle = _ArtifactBundle(artifact_upload_url)
                path = artifact_bundle.path_for(_artifact_member_name(spec))
                writers.append(_writer_for_format(spec.format, path=path))
                continue
            if spec.destination == "file":
                if not spec.target:
                    raise ValueError("file trace output requires file:<path>")
                writers.append(_writer_for_format(spec.format, path=Path(spec.target)))
                continue
            if spec.destination in {"stdout", "stderr"}:
                stream = stdout if spec.destination == "stdout" else stderr
                if stream is None:
                    stream = sys.stdout if spec.destination == "stdout" else sys.stderr
                writers.append(_writer_for_format(spec.format, stream=stream, close_stream=False))
                continue
            raise ValueError(f"unsupported trace output destination: {spec.destination!r}")
        return cls(
            writers,
            event_filter=event_filter,
            metrics_enabled=metrics_enabled,
            artifact_bundle=artifact_bundle,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for writer in self._writers:
            try:
                writer.close()
            except Exception as exc:  # noqa: BLE001 - close should collect output failures.
                self._handle_close_error(exc)
        if self._artifact_bundle is not None:
            try:
                self._artifact_bundle.close()
            except Exception as exc:  # noqa: BLE001
                self._handle_close_error(exc)

    def _handle_close_error(self, exc: Exception) -> None:
        self.errors.append(exc)
        if self._fail_on_close_error:
            raise exc
        print(f"WARNING: failed to close trace output: {exc}", file=sys.stderr, flush=True)

    def __enter__(self) -> TraceOutputs:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, exc, traceback
        self.close()
        return False


class _FanoutTraceSink:
    def __init__(self, writers: Iterable[TelemetryWriter], *, event_filter: TraceFilter | None = None) -> None:
        self._writers = tuple(writers)
        self._event_filter = event_filter

    def record(self, event: TraceEvent) -> None:
        if self._event_filter is not None and not self._event_filter(event):
            return
        record = _trace_record(event)
        for writer in self._writers:
            writer.write_record(record)


class _FanoutMetricsSink:
    def __init__(self, writers: Iterable[TelemetryWriter]) -> None:
        self._writers = tuple(writers)

    def counter(self, name: str, value: float = 1.0, tags: dict[str, Any] | None = None) -> None:
        self._write(MetricSample(kind="counter", name=name, value=value, tags=dict(tags or {})))

    def histogram(self, name: str, value: float, tags: dict[str, Any] | None = None) -> None:
        self._write(MetricSample(kind="histogram", name=name, value=value, tags=dict(tags or {})))

    def gauge(self, name: str, value: float, tags: dict[str, Any] | None = None) -> None:
        self._write(MetricSample(kind="gauge", name=name, value=value, tags=dict(tags or {})))

    def _write(self, sample: MetricSample) -> None:
        record = _metric_record(sample)
        for writer in self._writers:
            writer.write_record(record)


class _JsonlWriter:
    def __init__(self, stream: TextIO, *, close_stream: bool = True) -> None:
        self._stream = stream
        self._close_stream = close_stream

    def write_record(self, record: dict[str, Any]) -> None:
        print(json.dumps(record, default=str, separators=(",", ":")), file=self._stream, flush=True)

    def close(self) -> None:
        self._stream.flush()
        if self._close_stream:
            self._stream.close()


class _JsonWriter:
    def __init__(self, stream: TextIO, *, close_stream: bool = True) -> None:
        self._stream = stream
        self._close_stream = close_stream
        self._records: list[dict[str, Any]] = []

    def write_record(self, record: dict[str, Any]) -> None:
        self._records.append(record)

    def close(self) -> None:
        json.dump({"schema_version": 1, "records": self._records}, self._stream, default=str)
        self._stream.write("\n")
        self._stream.flush()
        if self._close_stream:
            self._stream.close()


class _CsvWriter:
    _FIELDNAMES = ("kind", "tick", "name", "metric_kind", "value", "data_json", "tags_json")

    def __init__(self, stream: TextIO, *, close_stream: bool = True) -> None:
        self._stream = stream
        self._close_stream = close_stream
        self._writer = csv.DictWriter(self._stream, fieldnames=self._FIELDNAMES)
        self._writer.writeheader()
        self._stream.flush()

    def write_record(self, record: dict[str, Any]) -> None:
        self._writer.writerow(_csv_record(record))
        self._stream.flush()

    def close(self) -> None:
        self._stream.flush()
        if self._close_stream:
            self._stream.close()


class _ParquetWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: list[dict[str, Any]] = []

    def write_record(self, record: dict[str, Any]) -> None:
        self._records.append(_csv_record(record))

    def close(self) -> None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("parquet trace output requires the players[trace-parquet] extra") from exc
        self._path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(self._records)
        pq.write_table(table, self._path)


class _ArtifactBundle:
    def __init__(self, upload_url: str) -> None:
        self._upload_url = upload_url
        self._tempdir = Path(tempfile.mkdtemp(prefix="player-sdk-trace-artifact-"))
        self._members: list[str] = []

    def path_for(self, member_name: str) -> Path:
        clean_name = member_name.strip("/")
        path = PurePosixPath(clean_name)
        if not clean_name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"invalid artifact member path: {member_name!r}")
        if clean_name in self._members:
            raise ValueError(f"duplicate artifact member path: {member_name!r}")
        self._members.append(clean_name)
        return self._tempdir / clean_name

    def close(self) -> None:
        manifest_path = self._tempdir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "producer": "players.player_sdk.TraceOutputs",
                    "files": sorted(self._members),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        zip_path = self._tempdir / "player_trace_artifact.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, "manifest.json")
            for member in sorted(self._members):
                path = self._tempdir / member
                if path.exists():
                    archive.write(path, member)
        try:
            _upload_zip(self._upload_url, zip_path)
        finally:
            shutil.rmtree(self._tempdir, ignore_errors=True)


def parse_trace_output_specs(raw: str) -> tuple[TraceOutputSpec, ...]:
    if raw.strip().lower() in {"", "none", "off", "0", "false"}:
        return ()
    return tuple(TraceOutputSpec.parse(token) for token in _split_specs(raw))


def _split_specs(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for chunk in raw.split(";") for part in chunk.split(",") if part.strip())


def _normalize_format(raw_format: str) -> str:
    fmt = raw_format.strip().lower()
    aliases = {"ndjson": "jsonl"}
    fmt = aliases.get(fmt, fmt)
    if fmt not in {"jsonl", "json", "csv", "parquet"}:
        raise ValueError(f"unsupported trace output format: {raw_format!r}")
    return fmt


def _parse_destination(raw_destination: str) -> tuple[str, str | None]:
    destination = raw_destination.strip()
    if destination in {"stderr", "stdout"}:
        return destination, None
    if destination.startswith("file://"):
        return "file", destination.removeprefix("file://")
    if destination.startswith("file:"):
        return "file", destination.removeprefix("file:")
    if destination == "artifact":
        return "artifact", None
    if destination.startswith("artifact:"):
        return "artifact", destination.removeprefix("artifact:")
    raise ValueError(f"unsupported trace output destination: {raw_destination!r}")


def _writer_for_format(
    fmt: str,
    *,
    path: Path | None = None,
    stream: TextIO | None = None,
    close_stream: bool = True,
) -> TelemetryWriter:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "parquet":
            return _ParquetWriter(path)
        return _writer_for_format(fmt, stream=path.open("w", encoding="utf-8", newline=""), close_stream=True)
    if stream is None:
        raise ValueError("trace output writer requires a path or stream")
    if fmt == "jsonl":
        return _JsonlWriter(stream, close_stream=close_stream)
    if fmt == "json":
        return _JsonWriter(stream, close_stream=close_stream)
    if fmt == "csv":
        return _CsvWriter(stream, close_stream=close_stream)
    if fmt == "parquet":
        raise ValueError("parquet trace output requires file or artifact destination")
    raise ValueError(f"unsupported trace output format: {fmt!r}")


def _artifact_member_name(spec: TraceOutputSpec) -> str:
    if spec.target:
        return spec.target
    return f"telemetry.{_extension_for_format(spec.format)}"


def _extension_for_format(fmt: str) -> str:
    return "jsonl" if fmt == "jsonl" else fmt


def _trace_record(event: TraceEvent) -> dict[str, Any]:
    return {
        "kind": "trace",
        "tick": event.tick,
        "event": event.name,
        "name": event.name,
        "data": event.data,
    }


def _metric_record(sample: MetricSample) -> dict[str, Any]:
    return {
        "kind": "metric",
        "metric_kind": sample.kind,
        "name": sample.name,
        "value": sample.value,
        "tags": sample.tags,
    }


def _csv_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": record.get("kind", ""),
        "tick": record.get("tick", ""),
        "name": record.get("name") or record.get("event", ""),
        "metric_kind": record.get("metric_kind", ""),
        "value": record.get("value", ""),
        "data_json": json.dumps(record.get("data", {}), default=str, separators=(",", ":")),
        "tags_json": json.dumps(record.get("tags", {}), default=str, separators=(",", ":")),
    }


def _upload_zip(upload_url: str, zip_path: Path) -> None:
    if upload_url.startswith("file://"):
        destination = Path(upload_url.removeprefix("file://"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(zip_path, destination)
        return
    if upload_url.startswith("http://") or upload_url.startswith("https://"):
        request = urllib.request.Request(
            upload_url,
            data=zip_path.read_bytes(),
            method="PUT",
            headers={"Content-Type": "application/zip"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - URL is runner-provided upload URI.
            response.read()
        return
    raise ValueError(f"unsupported artifact upload URL: {upload_url!r}")


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
