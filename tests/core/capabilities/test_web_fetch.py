from __future__ import annotations

import concurrent.futures
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import ClassVar

import pytest

from atelier.core.capabilities import web_fetch


class _FakeResponse:
    status = 200
    headers: ClassVar[dict[str, str]] = {"content-type": "text/markdown; charset=utf-8"}

    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, amt: int = 65536, decode_content: bool = True) -> Iterator[bytes]:
        _ = (amt, decode_content)
        yield self._body

    def release_conn(self) -> None:
        return None


class _FakeRedirectResponse:
    status = 302
    headers: ClassVar[dict[str, str]] = {}

    def __init__(self, location: str) -> None:
        self.headers = {"location": location}

    def stream(self, amt: int = 65536, decode_content: bool = True) -> Iterator[bytes]:
        return iter([b""])

    def release_conn(self) -> None:
        return None


class _FakeErrorResponse:
    status = 404
    headers: ClassVar[dict[str, str]] = {"content-type": "text/plain; charset=utf-8"}

    def __init__(self, body: bytes = b"Not Found") -> None:
        self._body = body

    def stream(self, amt: int = 65536, decode_content: bool = True) -> Iterator[bytes]:
        yield self._body

    def release_conn(self) -> None:
        return None


class _FakeBinaryResponse:
    status = 200
    headers: ClassVar[dict[str, str]] = {"content-type": "application/octet-stream"}

    def __init__(self) -> None:
        self._body = b"\x00\x01\x02"

    def stream(self, amt: int = 65536, decode_content: bool = True) -> Iterator[bytes]:
        yield self._body

    def release_conn(self) -> None:
        return None


class _FakeHTTP:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *args: object, **kwargs: object) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse(b"# Cached\n\nBody")


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    web_fetch.clear_web_fetch_cache()
    yield
    web_fetch.clear_web_fetch_cache()


# --------------------------------------------------------------------------- #
# URL validation (format — no DNS)                                            #
# --------------------------------------------------------------------------- #


def test_validate_url_rejects_control_chars() -> None:
    with pytest.raises(ValueError, match="control characters"):
        web_fetch._validate_public_url("http://example.com/\x00")


def test_validate_url_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        web_fetch._validate_public_url("")


def test_validate_url_rejects_no_hostname() -> None:
    with pytest.raises(ValueError, match="hostname"):
        web_fetch._validate_public_url("http:///path")


def test_validate_url_rejects_credentials() -> None:
    with pytest.raises(ValueError, match="credentials"):
        web_fetch._validate_public_url("http://user:pass@example.com")


def test_validate_url_rejects_bad_scheme() -> None:
    with pytest.raises(ValueError, match="only supports http and https"):
        web_fetch._validate_public_url("ftp://example.com")


def test_validate_url_accepts_loopback_url_format_only() -> None:
    """Format check alone should accept loopback — IP validation happens at connect time."""
    result = web_fetch._validate_public_url("http://127.0.0.1")
    assert result == "http://127.0.0.1"


def test_validate_url_accepts_standard_ports() -> None:
    """Explicit standard ports (80, 443) are on the allowlist."""
    assert web_fetch._validate_public_url("http://example.com:80/path") == "http://example.com:80/path"
    assert web_fetch._validate_public_url("https://example.com:443/path") == "https://example.com:443/path"


def test_validate_url_accepts_default_port() -> None:
    """No explicit port is allowed — the scheme default is used at connect time."""
    assert web_fetch._validate_public_url("http://example.com/path") == "http://example.com/path"


def test_validate_url_accepts_non_standard_ports() -> None:
    assert web_fetch._validate_public_url("http://localhost:8080/path") == "http://localhost:8080/path"
    assert web_fetch._validate_public_url("http://example.com:8443/path") == "http://example.com:8443/path"


def test_validate_url_rejects_malformed_port() -> None:
    """A malformed (non-numeric / out-of-range) port is rejected."""
    with pytest.raises(ValueError, match="malformed port"):
        web_fetch._validate_public_url("http://example.com:notaport/path")


# --------------------------------------------------------------------------- #
# IP validation (resolution + public-IP check)                                #
# --------------------------------------------------------------------------- #


def test_assert_fetchable_ip_accepts_loopback() -> None:
    web_fetch._assert_fetchable_ip("127.0.0.1")
    web_fetch._assert_fetchable_ip("127.23.45.67")
    web_fetch._assert_fetchable_ip("::1")


def test_assert_fetchable_ip_rejects_private() -> None:
    with pytest.raises(ValueError, match="private/local"):
        web_fetch._assert_fetchable_ip("10.0.0.1")


def test_assert_fetchable_ip_rejects_link_local() -> None:
    with pytest.raises(ValueError, match="private/local"):
        web_fetch._assert_fetchable_ip("169.254.1.1")


def test_assert_fetchable_ip_rejects_multicast() -> None:
    with pytest.raises(ValueError, match="private/local"):
        web_fetch._assert_fetchable_ip("224.0.0.1")


def test_assert_fetchable_ip_rejects_unspecified() -> None:
    with pytest.raises(ValueError, match="private/local"):
        web_fetch._assert_fetchable_ip("0.0.0.0")


def test_assert_fetchable_ip_accepts_public_ipv4() -> None:
    web_fetch._assert_fetchable_ip("8.8.8.8")


def test_assert_fetchable_ip_accepts_public_ipv6() -> None:
    web_fetch._assert_fetchable_ip("2001:4860:4860::8888")


def test_fetch_url_allows_loopback_on_non_standard_port(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"localhost fetch works"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(web_fetch, "_resolve_host_safe", lambda host, timeout: "127.0.0.1")

    try:
        port = server.server_address[1]
        result = web_fetch.fetch_url(f"http://localhost:{port}/health", output_format="text")
        assert result["content"] == "localhost fetch works"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)


# --------------------------------------------------------------------------- #
# DNS resolution with timeout                                                 #
# --------------------------------------------------------------------------- #


def test_resolve_host_safe_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    slow_future: concurrent.futures.Future = concurrent.futures.Future()

    monkeypatch.setattr(web_fetch._DNS_EXECUTOR, "submit", lambda *a, **kw: slow_future)
    monkeypatch.setattr(web_fetch._DNS_EXECUTOR, "_max_workers", 4)

    with pytest.raises(ValueError, match="timed out"):
        web_fetch._resolve_host_safe("example.com", timeout=0.05)


def test_resolve_host_safe_rejects_idn_failure() -> None:
    with pytest.raises(ValueError, match="invalid hostname"):
        web_fetch._resolve_host_safe("\ud800", timeout=5.0)


# --------------------------------------------------------------------------- #
# Content type rejection                                                      #
# --------------------------------------------------------------------------- #


def test_rejects_binary_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_http = _FakeHTTP()
    fake_http.request = lambda *a, **kw: _FakeBinaryResponse()
    monkeypatch.setattr(web_fetch, "_HTTP", fake_http)
    monkeypatch.setattr(web_fetch, "_resolve_host_safe", lambda host, timeout: "1.2.3.4")

    with pytest.raises(ValueError, match="unsupported content type"):
        web_fetch._fetch_uncached("https://example.com/file", accept="*/*", timeout_s=5.0)


# --------------------------------------------------------------------------- #
# HTTP error codes                                                            #
# --------------------------------------------------------------------------- #


def test_raises_on_http_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_http = _FakeHTTP()
    fake_http.request = lambda *a, **kw: _FakeErrorResponse()
    monkeypatch.setattr(web_fetch, "_HTTP", fake_http)
    monkeypatch.setattr(web_fetch, "_resolve_host_safe", lambda host, timeout: "1.2.3.4")

    with pytest.raises(ValueError, match="HTTP 404"):
        web_fetch._fetch_uncached("https://example.com/missing", accept="*/*", timeout_s=5.0)


# --------------------------------------------------------------------------- #
# Redirects                                                                   #
# --------------------------------------------------------------------------- #


def test_follows_redirect_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_target = "https://example.com/final"

    class _RedirectFakeHTTP:
        def __init__(self_):
            self_.step = 0

        def request(self_, *a, **kw):
            self_.step += 1
            if self_.step == 1:
                return _FakeRedirectResponse(redirect_target)
            return _FakeResponse(b"# Final\n\nContent")

    fake = _RedirectFakeHTTP()
    monkeypatch.setattr(web_fetch, "_HTTP", fake)
    monkeypatch.setattr(web_fetch, "_resolve_host_safe", lambda host, timeout: "1.2.3.4")

    result = web_fetch._fetch_uncached("https://example.com/redirect", accept="*/*", timeout_s=5.0)
    assert result.final_url == redirect_target
    assert result.status == 200
    body = result.body.decode()
    assert "# Final" in body


def test_raises_on_redirect_without_location(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoLocRedirectFakeHTTP:
        def request(self_, *a, **kw):
            return _FakeRedirectResponse("")

    fake = _NoLocRedirectFakeHTTP()
    monkeypatch.setattr(web_fetch, "_HTTP", fake)
    monkeypatch.setattr(web_fetch, "_resolve_host_safe", lambda host, timeout: "1.2.3.4")

    with pytest.raises(ValueError, match="redirect without Location"):
        web_fetch._fetch_uncached("https://example.com/redirect-no-loc", accept="*/*", timeout_s=5.0)


# --------------------------------------------------------------------------- #
# Cache correctness (thread-safe LRU)                                         #
# --------------------------------------------------------------------------- #


def test_fetch_cache_reuses_raw_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_http = _FakeHTTP()
    monkeypatch.setattr(web_fetch, "_HTTP", fake_http)
    monkeypatch.setattr(web_fetch, "_resolve_host_safe", lambda host, timeout: "1.2.3.4")

    first = web_fetch.fetch_url("https://example.com/docs", max_chars=100)
    second = web_fetch.fetch_url("https://example.com/docs", max_chars=100)

    assert first["content"] == second["content"]
    assert fake_http.calls == 1


def test_fetch_cache_distinct_urls_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_http = _FakeHTTP()
    monkeypatch.setattr(web_fetch, "_HTTP", fake_http)
    monkeypatch.setattr(web_fetch, "_resolve_host_safe", lambda host, timeout: "1.2.3.4")

    web_fetch.fetch_url("https://example.com/a", max_chars=100)
    web_fetch.fetch_url("https://example.com/b", max_chars=100)

    assert fake_http.calls == 2


# --------------------------------------------------------------------------- #
# HTML / Markdown conversion                                                  #
# --------------------------------------------------------------------------- #


def test_html_to_markdown_preserves_coding_docs_structure() -> None:
    html = """
    <html><head><title>API Reference</title><script>alert(1)</script></head>
    <body><main><h1>Client</h1><p>Use <code>fetch_url</code>.</p>
    <pre class="language-python">print('ok')</pre>
    <a href="/docs/auth">Auth</a><img alt="Architecture diagram" src="/a.png" />
    </main></body></html>
    """

    markdown = web_fetch.html_to_markdown_for_agent(html, base_url="https://example.com/base")

    assert "# Client" in markdown
    assert "`fetch_url`" in markdown
    assert "```" in markdown
    assert "print('ok')" in markdown
    assert "Auth" in markdown
    assert "Architecture diagram" in markdown
    assert "alert" not in markdown


def test_html_to_markdown_handles_decomposed_descendants() -> None:
    # Regression: a hidden container holding child tags. _remove_noise
    # decomposes the container, which nulls its descendants' .attrs while those
    # descendants are still pending in find_all(True)'s materialized list.
    # Reaching one used to raise "AttributeError: 'NoneType' object has no
    # attribute 'get'" and broke every fetch of a page with such markup.
    html = (
        "<html><body>"
        '<div style="display:none"><span>secret</span><p>hidden body</p></div>'
        "<p>visible body</p>"
        "</body></html>"
    )

    markdown = web_fetch.html_to_markdown_for_agent(html)

    assert "visible body" in markdown
    assert "secret" not in markdown
    assert "hidden body" not in markdown


def test_clean_markdown_removes_converter_noise() -> None:
    cleaned = web_fetch.clean_markdown_for_agent("Title\nTitle\n\n\n\n\n![](pixel.gif)\n[](/empty)\n    ```\ncode\n```")

    assert cleaned.count("Title") == 1
    assert "pixel.gif" not in cleaned
    assert "[](" not in cleaned
    assert "```\ncode\n```" in cleaned


# --------------------------------------------------------------------------- #
# Utility helpers                                                             #
# --------------------------------------------------------------------------- #


def test_is_ip_address() -> None:
    assert web_fetch._is_ip_address("8.8.8.8") is True
    assert web_fetch._is_ip_address("::1") is True
    assert web_fetch._is_ip_address("example.com") is False
    assert web_fetch._is_ip_address("") is False
