"""MettaGrid replay atlas — an engine-generic reporter.

One image serves every MettaGrid-based game: reads the canonical episode
bundle (results JSON + MettaScope ``replay.json``), derives the canonical
``(ts, player, key, value)`` event log via ``episode_analysis.mettascope``,
and renders a self-contained HTML atlas — agent table, occupancy heatmaps,
and a per-agent swimlane timeline.

Output zip surfaces:

- ``summary.html`` (render): self-contained; charts embedded as data URIs.
- ``events.parquet`` (event_log): ``position``/``reward``/``death``/
  ``episode`` rows per the recommended key registry
  (``episode_analysis`` README).
- ``occupancy.png`` / ``timeline.png``: the raw charts as free-form aux
  files.

Configuration (env):

- ``ATLAS_LOCATION_ORDER``: ``xy`` (default) or ``rc`` — how to read the
  replay's 2-list agent locations (the axis order is game-defined; verify
  against a non-square map).
"""

from __future__ import annotations

import os
import sys
from typing import Any

from episode_analysis import EventLog, accumulate_by_group, to_event_rows, total_grid
from episode_analysis.charts import Lane, Marker, density_layer, render_heatmap, render_swimlanes
from episode_analysis.html import embed_png, page, section, table
from episode_analysis.mettascope import agent_objects, max_steps_of, value_at
from reporter_sdk import (
    BundleReader,
    OutputManifest,
    ReporterInputs,
    build_report_zip,
    load_reporter_inputs,
    stable_json,
    write_events_parquet,
    write_uri,
)

REPORTER_ID = "mettagrid-replay-atlas"


def _policy_name(obj: dict[str, Any], fallback: str) -> str:
    infos = value_at(obj.get("policy_infos"), 0)
    if isinstance(infos, dict) and isinstance(infos.get("policy_name"), str):
        return infos["policy_name"]
    return fallback


def _world_size(replay: dict, log: EventLog) -> tuple[float, float]:
    size = replay.get("map_size")
    if isinstance(size, list) and len(size) == 2:
        return float(size[0]), float(size[1])
    pts = log.positions()
    if pts:
        return max(x for _, _, x, _ in pts) + 1, max(y for _, _, _, y in pts) + 1
    return 1.0, 1.0


def build_zip_bytes(results: dict[str, Any], replay: dict, location_order: str) -> bytes:
    rows = to_event_rows(replay, location_order=location_order, stamp=stable_json)
    events_parquet = write_events_parquet(rows)
    log = EventLog.from_rows(rows)
    steps = max_steps_of(replay)
    width, height = _world_size(replay, log)
    scores = results.get("scores") or []

    # --- agent table ---------------------------------------------------------
    agent_rows = []
    for agent_id, obj in agent_objects(replay):
        reward = log.numeric_series("reward", player=agent_id, field="total")
        deaths = log.filter(key="death", player=agent_id)
        agent_rows.append(
            [
                agent_id,
                _policy_name(obj, f"agent {agent_id}"),
                f"{(scores[agent_id] if agent_id < len(scores) else 0.0):.2f}",
                f"{reward[-1][1]:.2f}" if reward else "0.00",
                deaths[0].ts if deaths else "—",
            ]
        )

    # --- charts -----------------------------------------------------------------
    chart_pngs: list[tuple[str, bytes]] = []
    sections: list[str] = [
        section(
            "Agents",
            table(["slot", "policy", "score", "total reward", "died at"], agent_rows),
        )
    ]

    samples = [(x, y, p) for _, p, x, y in log.positions()]
    grids = accumulate_by_group(samples, width, height)
    layer = density_layer(total_grid(grids)) if grids else None
    if layer is not None:
        png = render_heatmap(
            layer,
            title="occupancy — all agents",
            cbar_label="position samples per cell (log)",
            width=width,
            height=height,
        )
        chart_pngs.append(("occupancy.png", png))
        sections.append(section("Where the episode happened", embed_png(png, "occupancy heatmap")))

    lanes = []
    for agent_id, _ in agent_objects(replay):
        markers = [
            Marker(ts, label=f"{delta:+.0f}")
            for ts, delta in log.numeric_series("reward", player=agent_id, field="delta")
        ]
        deaths = log.filter(key="death", player=agent_id)
        lanes.append(
            Lane(
                label=f"agent {agent_id}",
                end_tick=steps,
                markers=markers,
                cross_tick=deaths[0].ts if deaths else None,
            )
        )
    if lanes:
        png = render_swimlanes(
            lanes,
            marker_label="reward change",
            alt_label="(unused)",
            cross_label="death",
            band_label="span",
            emphasized_label="span (emphasized)",
        )
        chart_pngs.append(("timeline.png", png))
        sections.append(section("When it happened", embed_png(png, "per-agent timeline")))

    sections.append(
        section(
            "About",
            "<p>Engine-generic MettaScope replay atlas: the canonical event log "
            "(<code>events.parquet</code>) plus the charts above, derived from "
            f"<code>replay.json</code> ({steps} steps, {len(agent_rows)} agents, "
            f"{int(width)}×{int(height)} world, location order "
            f"<code>{location_order}</code>).</p>",
        )
    )

    html = page("MettaGrid replay atlas", *sections).encode("utf-8")
    return build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            render="summary.html",
            event_log="events.parquet",
        ),
        [
            ("summary.html", html),
            ("events.parquet", events_parquet),
            *chart_pngs,
        ],
    )


def run(inputs: ReporterInputs) -> None:
    location_order = os.environ.get("ATLAS_LOCATION_ORDER", "xy")
    with BundleReader(inputs.episode_bundle_uri) as bundle:
        inner = bundle.inner_manifest()
        if inner.status != "success":
            raise RuntimeError(
                f"bundle status={inner.status!r}; reporter cannot operate on a failed episode"
            )
        results = bundle.read_json("results")
        replay = bundle.read_json("replay")
    if not isinstance(replay, dict) or "objects" not in replay:
        raise RuntimeError(
            "replay is not a MettaScope replay (no 'objects'); this reporter "
            "targets MettaGrid-based games only"
        )

    payload = build_zip_bytes(results, replay, location_order)
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    run(load_reporter_inputs())
