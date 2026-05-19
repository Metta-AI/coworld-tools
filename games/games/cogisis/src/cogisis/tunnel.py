"""Cloudflare quick tunnel support for local Cogisis clients."""

from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

TRYCLOUDFLARE_URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def parse_trycloudflare_url(text: str) -> str:
    match = TRYCLOUDFLARE_URL_RE.search(text)
    if match is None:
        raise ValueError("cloudflared output did not include a trycloudflare.com URL")
    return match.group(0).rstrip("/")


@dataclass
class CloudflareQuickTunnel:
    """Own a `cloudflared tunnel --url ...` process for one local server."""

    local_url: str
    startup_timeout: float = 30.0
    binary: str = "cloudflared"
    public_url: str | None = None
    _process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _reader_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lines: queue.Queue[str] = field(default_factory=queue.Queue, init=False, repr=False)

    @property
    def command(self) -> list[str]:
        return [
            self.binary,
            "tunnel",
            "--config",
            "/dev/null",
            "--url",
            self.local_url,
        ]

    def start(self) -> str:
        if self.public_url is not None:
            return self.public_url
        try:
            self._process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("cloudflared is required for --tunnel but was not found on PATH") from exc

        self._reader_thread = threading.Thread(target=self._read_output, name="cloudflared-output", daemon=True)
        self._reader_thread.start()

        output: list[str] = []
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                break
            try:
                line = self._lines.get(timeout=0.1)
            except queue.Empty:
                continue
            output.append(line)
            try:
                self.public_url = parse_trycloudflare_url(line)
                return self.public_url
            except ValueError:
                continue

        self.stop()
        details = "".join(output).strip()
        if details:
            raise RuntimeError(f"cloudflared did not create a quick tunnel: {details}")
        raise RuntimeError("cloudflared did not create a quick tunnel before the startup timeout")

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._process = None

    def _read_output(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._lines.put(line)
