from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from ainulindale_api.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_ip_curl_default_plain_text(client: TestClient):
    """curl with default Accept: */* receives plain text with trailing newline."""
    res = client.get("/ip", headers={"User-Agent": "curl/8.5.0", "Accept": "*/*"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert res.text == "127.0.0.1\n"
    assert "no-store" in res.headers.get("cache-control", "")


def test_ip_forwarded_for_ipv4(client: TestClient):
    """X-Forwarded-For single IPv4 extraction."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "X-Forwarded-For": "203.0.113.195",
        },
    )
    assert res.status_code == 200
    assert res.text == "203.0.113.195\n"


def test_ip_forwarded_for_multiple_ips(client: TestClient):
    """X-Forwarded-For leftmost IP is preferred."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "X-Forwarded-For": "198.51.100.42, 10.1.3.176, 127.0.0.1",
        },
    )
    assert res.status_code == 200
    assert res.text == "198.51.100.42\n"


def test_ip_forwarded_for_with_port(client: TestClient):
    """IPv4 with port stripped."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "X-Forwarded-For": "203.0.113.50:54321",
        },
    )
    assert res.status_code == 200
    assert res.text == "203.0.113.50\n"


def test_ip_x_real_ip(client: TestClient):
    """X-Real-IP fallback when X-Forwarded-For is absent."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "X-Real-IP": "198.51.100.99",
        },
    )
    assert res.status_code == 200
    assert res.text == "198.51.100.99\n"


def test_ip_cf_connecting_ip(client: TestClient):
    """CF-Connecting-IP header fallback."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "CF-Connecting-IP": "198.51.100.77",
        },
    )
    assert res.status_code == 200
    assert res.text == "198.51.100.77\n"


def test_ip_ipv6_plain(client: TestClient):
    """IPv6 address extraction."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "X-Forwarded-For": "2001:db8:85a3::8a2e:370:7334",
        },
    )
    assert res.status_code == 200
    assert res.text == "2001:db8:85a3::8a2e:370:7334\n"


def test_ip_ipv6_bracketed_with_port(client: TestClient):
    """IPv6 address with brackets and port."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "X-Forwarded-For": "[2001:db8:85a3::8a2e:370:7334]:8443",
        },
    )
    assert res.status_code == 200
    assert res.text == "2001:db8:85a3::8a2e:370:7334\n"


def test_ip_browser_renders_html(client: TestClient):
    """Web browser requesting text/html receives rich HTML page."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "X-Forwarded-For": "203.0.113.88",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "203.0.113.88" in res.text
    assert "IPv4" in res.text
    assert "diederich.ai" in res.text
    assert "copyIp" in res.text


def test_ip_browser_ipv6_renders_html(client: TestClient):
    """Web browser with IPv6 displays IPv6 badge and formatted address."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "X-Forwarded-For": "2600:1700:ccd0:1234::1",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "2600:1700:ccd0:1234::1" in res.text
    assert "IPv6" in res.text


def test_ip_json_accept_header(client: TestClient):
    """Accept: application/json returns JSON structure."""
    res = client.get(
        "/ip",
        headers={
            "User-Agent": "curl/8.5.0",
            "Accept": "application/json",
            "X-Forwarded-For": "203.0.113.10",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    data = res.json()
    assert data == {"ip": "203.0.113.10", "version": "IPv4"}


def test_ip_json_query_param(client: TestClient):
    """Query parameter ?format=json returns JSON."""
    res = client.get(
        "/ip?format=json",
        headers={"X-Forwarded-For": "2001:db8::1"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    assert res.json() == {"ip": "2001:db8::1", "version": "IPv6"}


def test_ip_json_query_flag(client: TestClient):
    """Query parameter ?json returns JSON."""
    res = client.get(
        "/ip?json",
        headers={"X-Forwarded-For": "198.51.100.1"},
    )
    assert res.status_code == 200
    assert res.json() == {"ip": "198.51.100.1", "version": "IPv4"}


def test_ip_format_overrides(client: TestClient):
    """Explicit ?format=text overrides browser Accept header."""
    res = client.get(
        "/ip?format=text",
        headers={
            "Accept": "text/html",
            "X-Forwarded-For": "198.51.100.2",
        },
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert res.text == "198.51.100.2\n"

    # Explicit ?format=html overrides curl User-Agent
    res_html = client.get(
        "/ip?format=html",
        headers={
            "User-Agent": "curl/8.5.0",
            "X-Forwarded-For": "198.51.100.2",
        },
    )
    assert res_html.status_code == 200
    assert res_html.headers["content-type"].startswith("text/html")
    assert "198.51.100.2" in res_html.text


def test_myip_alias_and_trailing_slashes(client: TestClient):
    """Verify /myip and trailing slash routes work identically."""
    headers = {"User-Agent": "curl/8.5.0", "X-Forwarded-For": "203.0.113.77"}

    for path in ("/ip", "/ip/", "/myip", "/myip/"):
        res = client.get(path, headers=headers)
        assert res.status_code == 200
        assert res.text == "203.0.113.77\n"
