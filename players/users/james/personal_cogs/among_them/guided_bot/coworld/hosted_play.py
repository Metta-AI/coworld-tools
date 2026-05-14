#!/usr/bin/env python3
"""Orchestrate a Coworld hosted-game session end-to-end.

Creates a server-side play session, claims player slots, and launches a
local client process per slot. The Among Them server runs natively on
Softmax infrastructure; the local clients are thin WebSocket+ctypes
processes, so the whole loop avoids the qemu emulation that makes
`coworld run-episode` slow on arm64 dev machines.

Typical invocation:

    python guided_bot/coworld/hosted_play.py

Per-slot overrides:

    python guided_bot/coworld/hosted_play.py \
        --player 0=guided_bot:image:latest \
        --player 7=skip \
        --pull-episode-logs
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlsplit

REPO_DIR = Path(__file__).resolve().parents[2]
GUIDED_BOT_DIR = REPO_DIR / "guided_bot"
POLICY_PLAYER = GUIDED_BOT_DIR / "coworld" / "policy_player.py"
BUILD_SCRIPT = GUIDED_BOT_DIR / "build_guided_bot.py"

DEFAULT_COWORLD_ID = "cow_a7418f9b-4f4e-4f93-bfa4-91bb9655bc76"  # among_them
DEFAULT_COWORLD_CLI = Path.home() / "coding/metta/.venv/bin/coworld"
DEFAULT_PYTHON = Path.home() / "coding/metta/.venv/bin/python"
DEFAULT_SERVER = "https://api.observatory.softmax-research.net"


def _library_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "libguidedbot.dylib"
    if system == "Windows":
        return "guidedbot.dll"
    return "libguidedbot.so"


@dataclass
class PlayerSpec:
    """Describes how to launch one player against a given WS URL."""

    kind: str  # "local" | "image" | "raw_image" | "cmd" | "skip"
    image_tag: Optional[str] = None
    image_uri: Optional[str] = None
    argv: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.kind == "local":
            return "guided_bot:local"
        if self.kind == "image":
            return f"guided_bot:image:{self.image_tag}"
        if self.kind == "raw_image":
            return f"image:{self.image_uri}"
        if self.kind == "cmd":
            return "cmd:" + " ".join(shlex.quote(a) for a in self.argv)
        return self.kind


def parse_spec(spec_str: str) -> PlayerSpec:
    if spec_str == "skip":
        return PlayerSpec(kind="skip")
    if spec_str == "guided_bot:local":
        return PlayerSpec(kind="local")
    if spec_str == "guided_bot:image":
        return PlayerSpec(kind="image", image_tag="latest")
    if spec_str.startswith("guided_bot:image:"):
        tag = spec_str[len("guided_bot:image:") :]
        if not tag:
            raise ValueError(f"empty image tag in {spec_str!r}")
        return PlayerSpec(kind="image", image_tag=tag)
    if spec_str.startswith("image:"):
        uri = spec_str[len("image:") :]
        if not uri:
            raise ValueError(f"empty image uri in {spec_str!r}")
        return PlayerSpec(kind="raw_image", image_uri=uri)
    if spec_str.startswith("cmd:"):
        rest = spec_str[len("cmd:") :]
        argv = shlex.split(rest)
        if not argv:
            raise ValueError(f"empty argv in {spec_str!r}")
        return PlayerSpec(kind="cmd", argv=argv)
    raise ValueError(
        f"unknown policy spec: {spec_str!r} "
        "(expected guided_bot:local | guided_bot:image[:TAG] | "
        "image:URI | cmd:ARGV | skip)"
    )


def build_argv_for_spec(spec: PlayerSpec, ws_url: str, python_bin: str) -> list[str]:
    if spec.kind == "local":
        return [python_bin, str(POLICY_PLAYER), "--url", ws_url]
    if spec.kind == "image":
        image = f"guided_bot_coworld:{spec.image_tag}"
        return [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "-e", f"COGAMES_ENGINE_WS_URL={ws_url}",
            image,
        ]
    if spec.kind == "raw_image":
        return [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "-e", f"COGAMES_ENGINE_WS_URL={ws_url}",
            spec.image_uri,
        ]
    if spec.kind == "cmd":
        substituted = [a.replace("{URL}", ws_url) for a in spec.argv]
        # If no placeholder, append the URL as an env var via env(1).
        if substituted == spec.argv:
            return ["env", f"COGAMES_ENGINE_WS_URL={ws_url}", *substituted]
        return substituted
    raise ValueError(f"cannot launch spec kind {spec.kind!r}")


def coworld_json(cli: Path, server: str, *args: str) -> dict | list:
    cmd = [str(cli), *args, "--json", "--server", server]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(
            f"`{' '.join(cmd)}` failed with exit code {result.returncode}"
        )
    return json.loads(result.stdout)


def anonymous_join(server: str, session_id: str) -> dict:
    """POST /v2/coworlds/play/session/<id>/join with NO auth headers.

    The route uses OPTIONAL_AUTH; an authenticated user who joins twice
    gets the same slot back (existing_claim shortcut in coworld_routes.py).
    Anonymous joins skip that check and always claim the next free slot,
    which is what we want when filling all N slots from one machine.
    """
    url = f"{server.rstrip('/')}/v2/coworlds/play/session/{session_id}/join"
    req = urllib.request.Request(url, method="POST", data=b"")
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(
            f"anonymous join failed: HTTP {exc.code} {exc.reason}: {detail}"
        ) from exc
    return json.loads(body)


def extract_ws_url(player_url: str) -> str:
    """The CLI's player_url is an https wrapper containing the real
    WS endpoint inside an `address=` query parameter (URL-encoded).
    Extract the inner wss:// URL so policy_player.py can connect directly.
    """
    parts = urlsplit(player_url)
    qs = parse_qs(parts.query)
    if "address" in qs and qs["address"]:
        return qs["address"][0]
    return player_url


def ensure_native_built(python_bin: str) -> None:
    """guided_bot:local needs a native libguidedbot.{so,dylib}. The
    AmongThemPolicy loader will auto-build on first instantiation, but
    when we spawn N clients in parallel they'd race on the rebuild.
    Pre-build once here.
    """
    lib_path = GUIDED_BOT_DIR / _library_name()
    if lib_path.exists() and (
        GUIDED_BOT_DIR / f"{_library_name()}.abi"
    ).exists():
        return
    print(
        f"[hosted_play] native {_library_name()} not found — building "
        f"({python_bin} {BUILD_SCRIPT})",
        flush=True,
    )
    subprocess.run([python_bin, str(BUILD_SCRIPT)], check=True)


def parse_overrides(spec_args: list[str]) -> dict[int, PlayerSpec]:
    out: dict[int, PlayerSpec] = {}
    for raw in spec_args:
        if "=" not in raw:
            raise SystemExit(
                f"--player expects SLOT=SPEC, got {raw!r}"
            )
        slot_s, spec_part = raw.split("=", 1)
        try:
            slot = int(slot_s)
        except ValueError as exc:
            raise SystemExit(f"--player SLOT must be an integer: {raw!r}") from exc
        if slot in out:
            raise SystemExit(f"--player slot {slot} specified twice")
        out[slot] = parse_spec(spec_part)
    return out


def wait_with_timeout(
    procs: list[tuple[int, subprocess.Popen, "Path"]], timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if all(p.poll() is not None for _, p, _ in procs):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(1.0)


def terminate_all(procs: list[tuple[int, subprocess.Popen, "Path"]]) -> None:
    for _, p, _ in procs:
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if all(p.poll() is not None for _, p, _ in procs):
            return
        time.sleep(0.2)
    for _, p, _ in procs:
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def pull_episode_logs(
    cli: Path, server: str, output_dir: Path, started_at_iso: str
) -> None:
    print("[hosted_play] querying recent episodes for log pull...", flush=True)
    eps = coworld_json(cli, server, "episodes", "--mine", "--limit", "20")
    if not isinstance(eps, list):
        print(f"[hosted_play] unexpected episodes shape: {type(eps).__name__}")
        return
    new_eps = [e for e in eps if str(e.get("created_at", "")) >= started_at_iso]
    if not new_eps:
        print("[hosted_play] no new episodes found")
        return
    for ep in new_eps:
        ereq = ep["id"]
        print(f"[hosted_play] pulling logs for {ereq}", flush=True)
        subprocess.run(
            [
                str(cli), "episode-logs", ereq,
                "--mine", "-d", str(output_dir),
                "--server", server,
            ],
            check=False,
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Orchestrate a Coworld hosted-game session: create the session, "
            "claim all player slots, launch a local client per slot."
        )
    )
    ap.add_argument("--coworld", default=DEFAULT_COWORLD_ID,
                    help=f"Coworld ID (default: {DEFAULT_COWORLD_ID} — among_them)")
    ap.add_argument("--variant", default="default",
                    help="Coworld variant ID (default: default)")
    ap.add_argument("--server", default=DEFAULT_SERVER,
                    help=f"Observatory API server URL (default: {DEFAULT_SERVER})")
    ap.add_argument("--coworld-cli", type=Path, default=DEFAULT_COWORLD_CLI,
                    help=f"Path to coworld CLI (default: {DEFAULT_COWORLD_CLI})")
    ap.add_argument("--python", default=str(DEFAULT_PYTHON),
                    help=f"Python interpreter for guided_bot:local "
                         f"(default: {DEFAULT_PYTHON})")
    ap.add_argument("--output-dir", type=Path, default=None,
                    help="Where to put per-slot logs (default: /tmp/hosted_play_<ts>)")
    ap.add_argument("--default-player", default="guided_bot:local",
                    help="Policy spec for slots not pinned by --player "
                         "(default: guided_bot:local)")
    ap.add_argument("--player", action="append", default=[], metavar="SLOT=SPEC",
                    help="Override one slot's policy spec. Repeatable. "
                         "Specs: guided_bot:local | guided_bot:image[:TAG] | "
                         "image:URI | cmd:ARGV | skip")
    ap.add_argument("--timeout", type=float, default=1200.0,
                    help="Max wall time to wait for clients to exit (default: 1200s)")
    ap.add_argument("--keep-running", action="store_true",
                    help="Don't launch player processes — just claim slots and "
                         "print URLs so you can attach manually")
    ap.add_argument("--open-browser", action="store_true",
                    help="Open the global viewer URL after session creation")
    ap.add_argument("--pull-episode-logs", action="store_true",
                    help="After clients exit, query coworld episodes --mine and "
                         "download new ereq logs into the output dir")
    args = ap.parse_args()

    if not args.coworld_cli.exists():
        ap.error(f"coworld CLI not found at {args.coworld_cli}")

    overrides = parse_overrides(args.player)
    default_spec = parse_spec(args.default_player)

    if args.output_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.output_dir = Path(f"/tmp/hosted_play_{ts}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create session.
    print(
        f"[hosted_play] creating session: coworld={args.coworld} "
        f"variant={args.variant}",
        flush=True,
    )
    session = coworld_json(
        args.coworld_cli, args.server,
        "hosted-game", "create", args.coworld,
        "--variant", args.variant,
    )
    session_id = session["session_id"]
    player_count = int(session["player_count"])
    global_url = session.get("global_url", "")
    print(f"[hosted_play] session_id   = {session_id}")
    print(f"[hosted_play] player_count = {player_count}")
    if global_url:
        print(f"[hosted_play] global_url   = {global_url}")
    print(f"[hosted_play] output_dir   = {args.output_dir}")

    # 2. Build the per-slot plan.
    plan: list[PlayerSpec] = []
    for slot in range(player_count):
        plan.append(overrides.get(slot, default_spec))

    # Validate overrides that point past player_count.
    over_max = [s for s in overrides if s >= player_count or s < 0]
    if over_max:
        ap.error(
            f"--player slot(s) {sorted(over_max)} out of range "
            f"for variant with {player_count} slots"
        )

    needs_native = any(s.kind == "local" for s in plan)
    if needs_native:
        ensure_native_built(args.python)

    if args.open_browser and global_url:
        webbrowser.open(global_url)

    # 3. Claim slots and spawn one subprocess per non-skip slot.
    started_at_iso = datetime.now(timezone.utc).isoformat()
    procs: list[tuple[int, subprocess.Popen, Path]] = []

    print()
    print(f"{'slot':>4}  {'spec':<40}  log")
    print("-" * 80)

    try:
        for slot, spec in enumerate(plan):
            if spec.kind == "skip":
                print(f"{slot:>4}  {'(skipped)':<40}")
                continue
            claim = anonymous_join(args.server, session_id)
            actual_slot = int(claim["slot"])
            player_url = claim["player_url"]
            ws_url = extract_ws_url(player_url)
            if actual_slot != slot:
                print(
                    f"[hosted_play] warning: claimed slot {actual_slot} but "
                    f"planned for slot {slot}; using actual slot",
                    file=sys.stderr,
                )
            argv = build_argv_for_spec(spec, ws_url, args.python)
            log_path = args.output_dir / f"policy_agent_{actual_slot}.txt"
            log_fh = log_path.open("w", buffering=1)
            log_fh.write(f"[hosted_play] slot={actual_slot} spec={spec.describe()}\n")
            log_fh.write(f"[hosted_play] argv={argv}\n")
            log_fh.write(f"[hosted_play] ws_url={ws_url}\n")
            log_fh.flush()
            print(f"{actual_slot:>4}  {spec.describe():<40}  {log_path}")
            env = os.environ.copy()
            if spec.kind == "local":
                # policy_player.py imports `guided_bot.cogames.amongthem_policy`;
                # make the repo root visible so that namespace package resolves.
                existing = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = (
                    f"{REPO_DIR}{os.pathsep}{existing}" if existing else str(REPO_DIR)
                )
            popen = subprocess.Popen(
                argv,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
            procs.append((actual_slot, popen, log_path))

        print()
        print(f"[hosted_play] {len(procs)} client(s) launched")

        if args.keep_running:
            print("[hosted_play] --keep-running: leaving clients detached and exiting")
            return 0

        if not procs:
            print("[hosted_play] no clients to wait on; exiting")
            return 0

        print(f"[hosted_play] waiting up to {args.timeout:.0f}s for clients to exit "
              "(Ctrl-C to terminate)")
        finished = wait_with_timeout(procs, args.timeout)
        if not finished:
            print("[hosted_play] timeout exceeded; terminating clients",
                  file=sys.stderr)
            terminate_all(procs)

    except KeyboardInterrupt:
        print("\n[hosted_play] interrupted; terminating clients", file=sys.stderr)
        terminate_all(procs)
        return 130

    # 4. Summary.
    print()
    print("[hosted_play] === summary ===")
    any_nonzero = False
    for slot, popen, log_path in procs:
        rc = popen.returncode
        marker = "" if rc == 0 else "  <-- non-zero"
        print(f"  slot {slot}: exit={rc} log={log_path}{marker}")
        if rc != 0:
            any_nonzero = True

    if args.pull_episode_logs:
        pull_episode_logs(args.coworld_cli, args.server,
                          args.output_dir, started_at_iso)

    return 1 if any_nonzero else 0


if __name__ == "__main__":
    raise SystemExit(main())
