from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import urllib3

logger = logging.getLogger(__name__)

OutputFormat = Literal["auto", "markdown", "text", "html"]

DEFAULT_TIMEOUT_S = 20.0
DEFAULT_MAX_CHARS = 12_000
MAX_MAX_CHARS = 100_000
MAX_BODY_BYTES = 2_000_000
MAX_REDIRECTS = 5
FETCH_CACHE_TTL_S = 300.0
FETCH_CACHE_MAX_ITEMS = 128
TRANSFORM_CACHE_MAX_ITEMS = 128

DEFAULT_USER_AGENT = "Atelier web_fetch/0.2 (+https://github.com/atelier-runtime/atelier)"

_MARKDOWN_TYPES = {"text/markdown", "text/x-markdown", "text/vnd.daringfireball.markdown"}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {
    "text/plain",
    "application/json",
    "application/xml",
    "text/xml",
    *_MARKDOWN_TYPES,
    *_HTML_TYPES,
}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_NON_CONTENT_HTML_RE = re.compile(
    r"<!--.*?-->|<(?:script|style|noscript|template|svg|canvas|iframe)\b[^>]*>.*?</(?:script|style|noscript|template|svg|canvas|iframe)>",
    re.IGNORECASE | re.DOTALL,
)
_NOISE_CLASS_ID_RE = re.compile(
    r"(?:^|[-_\s])(?:cookie|consent|banner|modal|newsletter|subscribe|sponsor|advertisement|ad-container|social-share|share-buttons|feedback-widget|tracking|promo)(?:$|[-_\s])",
    re.IGNORECASE,
)
_CODE_LANG_RE = re.compile(
    r"(?:^|\s)(?:language|lang|highlight-source|brush|sourceCode)[-_:]([a-zA-Z0-9_+.#-]+)(?:\s|$)",
    re.IGNORECASE,
)
_HTTP = urllib3.PoolManager(num_pools=16, maxsize=16, retries=False, cert_reqs="CERT_REQUIRED")


@dataclass(frozen=True)
class _RawFetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    headers: dict[str, str]
    body: bytes
    truncated_body: bool


@dataclass(frozen=True)
class _FetchCacheEntry:
    expires_at: float
    value: _RawFetchResult


_FETCH_CACHE: OrderedDict[tuple[str, str], _FetchCacheEntry] = OrderedDict()
_FETCH_CACHE_LOCK = Lock()
_TRANSFORM_CACHE: OrderedDict[tuple[str, str], str] = OrderedDict()
_TRANSFORM_CACHE_LOCK = Lock()


def clear_web_fetch_cache() -> None:
    """Clear in-process fetch and transform caches. Intended for tests and debugging."""
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE.clear()
    with _TRANSFORM_CACHE_LOCK:
        _TRANSFORM_CACHE.clear()


def strip_non_content_html(html: str) -> str:
    """Remove expensive, unsafe, or non-content HTML blocks before parsing."""
    if not isinstance(html, str) or not html:
        return ""
    return _NON_CONTENT_HTML_RE.sub(" ", html)


def clean_markdown_for_agent(markdown: str) -> str:
    """Conservatively normalize Markdown for coding agents without dropping content."""
    if not isinstance(markdown, str) or not markdown:
        return ""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = text.replace("    ```", "```")
    text = re.sub(r"!\[(?:tracking|pixel|spacer|blank)?\]\([^)]+\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"!\[\]\([^)]+\)", "", text)
    text = re.sub(r"\[\]\([^)]+\)", "", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    deduped: list[str] = []
    previous: str | None = None
    for line in text.splitlines():
        key = line.strip()
        if key and key == previous:
            continue
        deduped.append(line)
        previous = key if key else None
    return "\n".join(deduped).strip()


def fetch_url(
    url: str,
    *,
    output_format: OutputFormat = "auto",
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    include_meta: bool = False,
) -> dict[str, Any]:
    """Fetch a public URL and return coding-agent-friendly content."""
    requested_format = _normalize_output_format(output_format)
    char_limit = _clamp_int(max_chars, 1_000, MAX_MAX_CHARS)
    timeout = float(min(max(float(timeout_s), 1.0), 60.0))
    accept = _accept_header(requested_format)
    raw = _fetch_with_cache(url.strip(), accept=accept, timeout_s=timeout)
    rendered = _render_content(raw, requested_format=requested_format)
    content = rendered["content"]
    truncated = False
    if len(content) > char_limit:
        content = content[:char_limit].rstrip() + "\n\n[truncated]"
        truncated = True

    payload: dict[str, Any] = {"content": content, "format": rendered["format"]}
    tokens_saved = _estimate_tokens_saved(raw, content)
    if tokens_saved > 0:
        payload["tokens_saved"] = tokens_saved
    if include_meta:
        payload.update(
            {
                "url": raw.url,
                "final_url": raw.final_url,
                "content_type": raw.content_type,
                "truncated": truncated or raw.truncated_body,
                "cache_ttl_seconds": int(FETCH_CACHE_TTL_S),
            }
        )
    return payload


def _normalize_output_format(output_format: str) -> OutputFormat:
    normalized = str(output_format or "auto").strip().lower()
    if normalized not in {"auto", "markdown", "text", "html"}:
        raise ValueError("output_format must be one of: auto, markdown, text, html")
    return normalized  # type: ignore[return-value]


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = DEFAULT_MAX_CHARS
    return max(minimum, min(maximum, coerced))


def _accept_header(output_format: OutputFormat) -> str:
    if output_format == "html":
        return "text/html, application/xhtml+xml;q=0.9, text/markdown;q=0.5, text/plain;q=0.4, */*;q=0.1"
    if output_format == "text":
        return "text/markdown, text/plain;q=0.9, text/html;q=0.8, application/json;q=0.6, */*;q=0.1"
    return "text/markdown, text/html;q=0.9, application/xhtml+xml;q=0.8, text/plain;q=0.7, application/json;q=0.6, */*;q=0.1"


def _fetch_with_cache(url: str, *, accept: str, timeout_s: float) -> _RawFetchResult:
    cache_key = (url, accept)
    now = time.monotonic()
    with _FETCH_CACHE_LOCK:
        cached = _FETCH_CACHE.get(cache_key)
        if cached is not None and cached.expires_at > now:
            _FETCH_CACHE.move_to_end(cache_key)
            return cached.value
        if cached is not None:
            _FETCH_CACHE.pop(cache_key, None)

    result = _fetch_uncached(url, accept=accept, timeout_s=timeout_s)
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE[cache_key] = _FetchCacheEntry(expires_at=now + FETCH_CACHE_TTL_S, value=result)
        _FETCH_CACHE.move_to_end(cache_key)
        while len(_FETCH_CACHE) > FETCH_CACHE_MAX_ITEMS:
            _FETCH_CACHE.popitem(last=False)
    return result


def _fetch_uncached(url: str, *, accept: str, timeout_s: float) -> _RawFetchResult:
    current_url = _validate_public_url(url)
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": accept}
    timeout = urllib3.Timeout(connect=timeout_s, read=timeout_s)

    for _redirect_index in range(MAX_REDIRECTS + 1):
        try:
            response = _HTTP.request(
                "GET",
                current_url,
                headers=headers,
                timeout=timeout,
                preload_content=False,
                redirect=False,
            )
        except urllib3.exceptions.HTTPError as exc:
            raise RuntimeError(f"web_fetch failed: {exc}") from exc

        try:
            status = int(response.status)
            location = response.headers.get("location")
            if status in _REDIRECT_STATUSES and location:
                response.release_conn()
                current_url = _validate_public_url(urljoin(current_url, location))
                continue
            if status in _REDIRECT_STATUSES:
                raise ValueError(f"web_fetch failed: HTTP {status} redirect without Location")
            body, truncated_body = _read_limited_body(response)
            content_type = response.headers.get("content-type", "") or ""
            media_type = _media_type(content_type)
            if media_type not in _TEXT_TYPES:
                raise ValueError(f"web_fetch unsupported content type: {media_type or 'unknown'}")
            if status < 200 or status >= 300:
                raise ValueError(f"web_fetch failed: HTTP {status}")
            return _RawFetchResult(
                url=url,
                final_url=current_url,
                status=status,
                content_type=content_type,
                headers={str(k).lower(): str(v) for k, v in response.headers.items()},
                body=body,
                truncated_body=truncated_body,
            )
        finally:
            response.release_conn()
    raise ValueError("web_fetch failed: too many redirects")


def _read_limited_body(response: urllib3.HTTPResponse) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    for chunk in response.stream(amt=65_536, decode_content=True):
        if not chunk:
            continue
        remaining = MAX_BODY_BYTES - total
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), truncated


def _validate_public_url(url: str) -> str:
    if not url or _CONTROL_CHARS_RE.search(url):
        raise ValueError("web_fetch URL is empty or contains control characters")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("web_fetch only supports http and https URLs")
    if not parsed.hostname:
        raise ValueError("web_fetch URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("web_fetch does not allow embedded credentials")
    _resolve_public_host(parsed.hostname)
    return url


def _resolve_public_host(hostname: str) -> None:
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
        infos = socket.getaddrinfo(ascii_hostname, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ValueError(f"web_fetch could not resolve host: {hostname}") from exc
    if not infos:
        raise ValueError(f"web_fetch could not resolve host: {hostname}")
    for info in infos:
        raw_ip = info[4][0]
        ip = ipaddress.ip_address(raw_ip)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("web_fetch blocked private/local network URL")


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _decode_body(body: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([^;]+)", content_type, flags=re.IGNORECASE)
    encoding = charset_match.group(1).strip().strip('"') if charset_match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")
