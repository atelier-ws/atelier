from __future__ import annotations

from typing import Iterator

import pytest

from atelier.core.capabilities import web_fetch


class _FakeResponse:
    status = 200
    headers = {"content-type": "text/markdown; charset=utf-8"}

    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, amt: int = 65536, decode_content: bool = True) -> Iterator[bytes]:
        _ = (amt, decode_content)
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


def test_blocks_private_loopback_url() -> None:
    with pytest.raises(ValueError, match="private/local"):
        web_fetch._validate_public_url("http://127.0.0.1:8080")


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
    assert "```python" in markdown
    assert "print('ok')" in markdown
    assert "[Auth](https://example.com/docs/auth)" in markdown
    assert "Architecture diagram" in markdown
    assert "alert" not in markdown


def test_fetch_cache_reuses_raw_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_http = _FakeHTTP()
    monkeypatch.setattr(web_fetch, "_HTTP", fake_http)
    monkeypatch.setattr(web_fetch, "_resolve_public_host", lambda hostname: None)

    first = web_fetch.fetch_url("https://example.com/docs", max_chars=100)
    second = web_fetch.fetch_url("https://example.com/docs", max_chars=100)

    assert first["content"] == second["content"]
    assert fake_http.calls == 1


def test_clean_markdown_removes_converter_noise() -> None:
    cleaned = web_fetch.clean_markdown_for_agent(
        "Title\nTitle\n\n\n\n\n![](pixel.gif)\n[](/empty)\n    ```\ncode\n```"
    )

    assert cleaned.count("Title") == 1
    assert "pixel.gif" not in cleaned
    assert "[](" not in cleaned
    assert "```\ncode\n```" in cleaned
