from __future__ import annotations

import html
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse


def read_uri(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        with urllib.request.urlopen(uri) as response:
            return response.read()
    path = Path(parsed.path if parsed.scheme == "file" else uri)
    return path.read_bytes()


def write_uri(uri: str, payload: bytes, content_type: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(
            uri,
            data=payload,
            method="PUT",
            headers={"Content-Type": content_type},
        )
        with urllib.request.urlopen(request) as response:
            response.read()
        return
    path = Path(parsed.path if parsed.scheme == "file" else uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def load_json_env(name: str) -> dict[str, object]:
    return json.loads(read_uri(os.environ[name]))


def sequence(name: str, payload: dict[str, object]) -> list[object]:
    value = payload[name] if name in payload else []
    if isinstance(value, list):
        return value
    return []


def summarize(results: dict[str, object]) -> dict[str, object]:
    names = [str(name) for name in sequence("names", results)]
    scores = sequence("scores", results)
    wins = sequence("win", results)
    tasks = sequence("tasks", results)
    kills = sequence("kills", results)
    slots = max(len(names), len(scores), len(wins), len(tasks), len(kills))
    players: list[dict[str, object]] = []
    for slot in range(slots):
        players.append(
            {
                "slot": slot,
                "name": names[slot] if slot < len(names) else f"slot-{slot}",
                "score": scores[slot] if slot < len(scores) else 0,
                "won": wins[slot] if slot < len(wins) else False,
                "tasks": tasks[slot] if slot < len(tasks) else 0,
                "kills": kills[slot] if slot < len(kills) else 0,
            }
        )
    winners = [player for player in players if player["won"]]
    return {
        "game": "among_them",
        "reporter_id": os.environ["COGAME_REPORTER_ID"] if "COGAME_REPORTER_ID" in os.environ else "among-them-summarizer",
        "players": players,
        "winner_names": [winner["name"] for winner in winners],
        "total_tasks": sum(int(player["tasks"]) for player in players),
        "total_kills": sum(int(player["kills"]) for player in players),
    }


def markdown(summary: dict[str, object]) -> str:
    players = summary["players"]
    assert isinstance(players, list)
    lines = [
        "# Among Them Episode Report",
        "",
        f"Winners: {', '.join(str(name) for name in summary['winner_names']) or 'none recorded'}",
        f"Total tasks completed: {summary['total_tasks']}",
        f"Total kills recorded: {summary['total_kills']}",
        "",
        "| Slot | Player | Score | Won | Tasks | Kills |",
        "| ---: | --- | ---: | :---: | ---: | ---: |",
    ]
    for player in players:
        assert isinstance(player, dict)
        lines.append(
            "| {slot} | {name} | {score} | {won} | {tasks} | {kills} |".format(
                slot=player["slot"],
                name=player["name"],
                score=player["score"],
                won="yes" if player["won"] else "no",
                tasks=player["tasks"],
                kills=player["kills"],
            )
        )
    return "\n".join(lines) + "\n"


def html_report(summary: dict[str, object], markdown_report: str) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            "<title>Among Them Episode Report</title>",
            "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;line-height:1.5}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ddd;padding:8px;text-align:left}td:first-child,td:nth-child(3),td:nth-child(5),td:nth-child(6){text-align:right}</style>",
            "</head>",
            "<body>",
            "<pre>",
            html.escape(markdown_report),
            "</pre>",
            "</body>",
            "</html>",
        ]
    )


def package_report(summary: dict[str, object]) -> bytes:
    markdown_report = markdown(summary)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.md", markdown_report)
        archive.writestr("index.html", html_report(summary, markdown_report))
        archive.writestr("summary.json", json.dumps(summary, indent=2) + "\n")
    return buffer.getvalue()


def main() -> None:
    results = load_json_env("COGAME_RESULTS_URI")
    report = package_report(summarize(results))
    write_uri(os.environ["COGAME_REPORT_OUTPUT_URI"], report, "application/zip")
    print("wrote Among Them report", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
