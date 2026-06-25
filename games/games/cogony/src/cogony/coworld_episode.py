"""Small Coworld play-session primitives used by the local Cogony runner.

These mirror the play-session and artifact contract from
``packages/coworld/src/coworld`` in Metta-AI/metta while keeping Cogony's local
in-process episode loop.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode


@dataclass(frozen=True)
class EpisodeArtifacts:
    workspace: Path
    config_path: Path
    results_path: Path
    replay_path: Path
    logs_dir: Path
    game_stdout_path: Path
    game_stderr_path: Path

    @classmethod
    def create(cls, workspace: Path | str | None = None, *, prefix: str = "coworld-play-") -> EpisodeArtifacts:
        path = Path(workspace) if workspace is not None else _new_workspace(prefix)
        path.mkdir(parents=True, exist_ok=True)
        logs_dir = path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            workspace=path,
            config_path=path / "config.json",
            results_path=path / "results.json",
            replay_path=path / "replay.json",
            logs_dir=logs_dir,
            game_stdout_path=logs_dir / "game.stdout.log",
            game_stderr_path=logs_dir / "game.stderr.log",
        )


@dataclass(frozen=True)
class PlayLinks:
    players: list[str]
    global_: str
    admin: str


@dataclass(frozen=True)
class PlaySession:
    artifacts: EpisodeArtifacts
    links: PlayLinks


def build_play_links(tokens: list[str], *, game_port: int) -> PlayLinks:
    players = [
        f"http://127.0.0.1:{game_port}/player?{urlencode({'slot': slot, 'token': token})}"
        for slot, token in enumerate(tokens)
    ]
    return PlayLinks(
        players=players,
        global_=f"http://127.0.0.1:{game_port}/global",
        admin=f"http://127.0.0.1:{game_port}/admin",
    )


def artifact_status(artifacts: EpisodeArtifacts) -> dict[str, str]:
    return {
        "workspace": str(artifacts.workspace),
        "config": str(artifacts.config_path),
        "results": str(artifacts.results_path),
        "replay": str(artifacts.replay_path),
        "logs": str(artifacts.logs_dir),
    }


def _new_workspace(prefix: str) -> Path:
    temp_root = Path.cwd() / "tmp"
    temp_root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=temp_root))
