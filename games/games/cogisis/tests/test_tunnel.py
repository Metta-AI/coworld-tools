import pytest

from cogisis.tunnel import CloudflareQuickTunnel, parse_trycloudflare_url


def test_parse_trycloudflare_url_from_cloudflared_output() -> None:
    text = """
    Your quick Tunnel has been created!
    |  https://example-name.trycloudflare.com  |
    """

    assert parse_trycloudflare_url(text) == "https://example-name.trycloudflare.com"


def test_parse_trycloudflare_url_rejects_missing_url() -> None:
    with pytest.raises(ValueError, match="trycloudflare"):
        parse_trycloudflare_url("Requesting new quick Tunnel")


def test_cloudflare_quick_tunnel_command_ignores_default_config() -> None:
    tunnel = CloudflareQuickTunnel("http://127.0.0.1:12345")

    assert tunnel.command == [
        "cloudflared",
        "tunnel",
        "--config",
        "/dev/null",
        "--url",
        "http://127.0.0.1:12345",
    ]
