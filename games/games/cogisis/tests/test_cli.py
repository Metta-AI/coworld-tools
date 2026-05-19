import json

from cogisis.cli import build_parser, main


def test_cli_defaults_to_gui_without_autorun() -> None:
    args = build_parser().parse_args([])

    assert args.render == "gui"
    assert args.autorun is False
    assert args.tunnel is False


def test_cli_without_autorun_does_not_play_or_print(capsys) -> None:
    exit_code = main(["--max-steps", "2", "--render", "none", "--policy", "noop"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_cli_root_cogs_sets_player_count_when_autorun(capsys) -> None:
    exit_code = main(["--cogs", "2", "--max-steps", "1", "--render", "json", "--policy", "noop", "--autorun"])

    captured = capsys.readouterr()
    assert exit_code == 0
    frame = json.loads(captured.out)
    assert set(frame["characters"]) == {"0", "1"}


def test_cli_play_render_none(capsys) -> None:
    exit_code = main(["play", "--max-steps", "3", "--render", "none", "--policy", "noop", "--autorun"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_cli_play_render_json(capsys) -> None:
    exit_code = main(["play", "--max-steps", "2", "--render", "json", "--policy", "survivor", "--autorun"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"ship"' in captured.out
    assert '"characters"' in captured.out


def test_cli_client_writes_html(tmp_path, capsys) -> None:
    output = tmp_path / "client.html"

    exit_code = main(["client", "--max-steps", "1", "--cogs", "1", "--policy", "noop", "--output", str(output)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Wrote Cogisis global client" in captured.out
    assert output.exists()
    assert "Cogisis global client" in output.read_text()


def test_cli_tunnel_flag_uses_public_tunnel_urls(monkeypatch, capsys) -> None:
    started = {}

    class FakeTunnel:
        public_url = "https://public-cogisis.trycloudflare.com"

        def __init__(self, local_url: str) -> None:
            started["local_url"] = local_url
            self.stopped = False

        def start(self) -> None:
            started["started"] = True
            return self.public_url

        def stop(self) -> None:
            started["stopped"] = True

    def stop_immediately(self) -> None:
        self.stop()

    monkeypatch.setattr("cogisis.cli.CloudflareQuickTunnel", FakeTunnel)
    monkeypatch.setattr("cogisis.cli.CogisisWebServer.wait", stop_immediately)

    exit_code = main(["--cogs", "1", "--port", "0", "--tunnel"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert started["started"] is True
    assert started["stopped"] is True
    assert started["local_url"].startswith("http://127.0.0.1:")
    assert "http://127.0.0.1" not in captured.out
    assert "https://public-cogisis.trycloudflare.com/player?slot=0&token=" in captured.out
    assert "Global client: https://public-cogisis.trycloudflare.com/global" in captured.out
    assert "Admin client: https://public-cogisis.trycloudflare.com/admin" in captured.out


def test_cli_tunnel_requires_gui_render() -> None:
    try:
        main(["--render", "none", "--tunnel"])
    except SystemExit as exc:
        assert str(exc) == "--tunnel requires --render gui or --render web"
    else:
        raise AssertionError("expected --tunnel to reject headless renders")


def test_cli_stops_server_when_tunnel_start_fails(monkeypatch) -> None:
    stopped = {}

    class FakeTunnel:
        def __init__(self, local_url: str) -> None:
            self.local_url = local_url

        def start(self) -> str:
            raise RuntimeError("tunnel failed")

        def stop(self) -> None:
            stopped["tunnel"] = True

    original_stop = None

    def tracked_stop(self) -> None:
        stopped["server"] = True
        original_stop(self)

    import cogisis.cli

    original_stop = cogisis.cli.CogisisWebServer.stop
    monkeypatch.setattr("cogisis.cli.CloudflareQuickTunnel", FakeTunnel)
    monkeypatch.setattr("cogisis.cli.CogisisWebServer.stop", tracked_stop)

    try:
        main(["--cogs", "1", "--port", "0", "--tunnel"])
    except RuntimeError as exc:
        assert str(exc) == "tunnel failed"
    else:
        raise AssertionError("expected tunnel startup failure")

    assert stopped["tunnel"] is True
    assert stopped["server"] is True
