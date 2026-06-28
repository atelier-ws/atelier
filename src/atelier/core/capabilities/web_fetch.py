from __future__ import annotations

import asyncio
import concurrent.futures
import functools
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

import aiohttp
import urllib3
from aiohttp.abc import AbstractResolver, ResolveResult
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import SSL_KEYWORDS
from urllib3.response import BaseHTTPResponse
from urllib3.util.connection import _set_socket_options

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
DNS_TIMEOUT_S = 10.0
_DNS_MAX_WORKERS = 4

DEFAULT_USER_AGENT = "Atelier web_fetch/0.2 (+https://github.com/atelier-ws/atelier)"

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

_DNS_EXECUTOR: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
    max_workers=_DNS_MAX_WORKERS, thread_name_prefix="atelier-dns"
)


def _resolve_host_safe(hostname: str, timeout: float) -> str:
    """Resolve *hostname* with a timeout and reject unsafe network destinations.

    Public and loopback addresses are allowed. Private-network, link-local, and
    otherwise non-routable addresses are rejected.
    """
    try:
        ascii_host = hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        raise ValueError(f"web_fetch invalid hostname: {hostname}") from None
    try:
        future = _DNS_EXECUTOR.submit(socket.getaddrinfo, ascii_host, None, proto=socket.IPPROTO_TCP)
        effective_timeout = min(timeout, DNS_TIMEOUT_S)
        infos = future.result(timeout=effective_timeout)
    except concurrent.futures.TimeoutError:
        raise ValueError(f"web_fetch DNS resolution timed out for: {hostname}") from None
    except OSError as exc:
        raise ValueError(f"web_fetch could not resolve host: {hostname}") from exc
    if not infos:
        raise ValueError(f"web_fetch could not resolve host: {hostname}")
    for info in infos:
        raw_ip = str(info[4][0])
        _assert_fetchable_ip(raw_ip)
    return str(infos[0][4][0])


_CGNAT_RANGE = ipaddress.ip_network("100.64.0.0/10")


def _assert_fetchable_ip(raw_ip: str) -> None:
    ip = ipaddress.ip_address(raw_ip)
    if ip.is_loopback:
        return
    if ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise ValueError(f"web_fetch blocked private/local network IP: {raw_ip}")
    if ip.version == 4 and ip in _CGNAT_RANGE:
        raise ValueError(f"web_fetch blocked private/local network IP: {raw_ip}")


# --------------------------------------------------------------------------- #
# Custom urllib3 connection classes — DNS + IP validation at connect time     #
# --------------------------------------------------------------------------- #


class _ValidatingHTTPConnection(HTTPConnection):
    """HTTPConnection that resolves DNS with timeout and rejects unsafe IPs."""

    def _new_conn(self) -> socket.socket:
        host = self.host
        timeout = self.timeout if isinstance(self.timeout, (int, float)) else DNS_TIMEOUT_S
        if _is_ip_address(host):
            _assert_fetchable_ip(host)
        else:
            host = _resolve_host_safe(host, timeout=timeout)
        # Connect the socket to the validated IP via a local variable only. Do NOT
        # assign self._dns_host: urllib3 backs the self.host property (used for the
        # outgoing Host header) with _dns_host, so overwriting it with the IP would
        # send `Host: <ip>` and break name-based virtual hosting.
        conn = socket.create_connection(
            (host, self.port),
            self.timeout,
            source_address=self.source_address,
        )
        _set_socket_options(conn, self.socket_options)
        return conn


class _ValidatingHTTPSConnection(HTTPSConnection):
    """HTTPSConnection that resolves DNS with timeout and rejects unsafe IPs."""

    def _new_conn(self) -> socket.socket:
        host = self.host
        timeout = self.timeout if isinstance(self.timeout, (int, float)) else DNS_TIMEOUT_S
        if _is_ip_address(host):
            _assert_fetchable_ip(host)
        else:
            host = _resolve_host_safe(host, timeout=timeout)
        # Connect the socket to the validated IP via a local variable only. Do NOT
        # assign self._dns_host: urllib3 derives the TLS server_hostname from
        # self.host (HTTPSConnection.connect: `server_hostname = self.host`), and the
        # self.host property is backed by _dns_host. Overwriting it with the IP makes
        # TLS verify the certificate against the IP -> CERTIFICATE_VERIFY_FAILED
        # (IP address mismatch). Keep the hostname so SNI + cert matching are correct.
        conn = socket.create_connection(
            (host, self.port),
            self.timeout,
            source_address=self.source_address,
        )
        _set_socket_options(conn, self.socket_options)
        return conn


class _ValidatingHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _ValidatingHTTPConnection


class _ValidatingHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _ValidatingHTTPSConnection


class _ValidatingPoolManager(urllib3.PoolManager):
    """PoolManager that uses validating connection classes for HTTP/HTTPS."""

    def _new_pool(
        self,
        scheme: str,
        host: str,
        port: int | None,
        request_context: dict[str, Any] | None = None,
    ) -> HTTPConnectionPool | HTTPSConnectionPool:
        pool_cls: type[Any]
        if scheme == "http":
            pool_cls = _ValidatingHTTPConnectionPool
        elif scheme == "https":
            pool_cls = _ValidatingHTTPSConnectionPool
        else:
            pool_cls = self.pool_classes_by_scheme[scheme]

        pool_kwargs = (self.connection_pool_kw if request_context is None else request_context).copy()
        for key in ("scheme", "host", "port"):
            pool_kwargs.pop(key, None)
        if scheme == "http":
            for key in SSL_KEYWORDS:
                pool_kwargs.pop(key, None)
        return pool_cls(host, port, **pool_kwargs)


_HTTP = _ValidatingPoolManager(num_pools=16, maxsize=16, retries=False, cert_reqs="CERT_REQUIRED")


def _is_ip_address(value: str) -> bool:
    """Return True when *value* is a bare IP address (no DNS resolution needed)."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


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
    """Fetch an HTTP(S) URL and return coding-agent-friendly content."""
    requested_format = _normalize_output_format(output_format)
    char_limit = _clamp_int(max_chars, 1_000, MAX_MAX_CHARS)
    timeout = float(min(max(float(timeout_s), 1.0), 60.0))
    accept = _accept_header(requested_format)
    raw = _fetch_with_cache(url.strip(), accept=accept, timeout_s=timeout)
    rendered = _render_content(raw, requested_format=requested_format)
    return _finish_fetch(raw, rendered=rendered, char_limit=char_limit, include_meta=include_meta)


def _finish_fetch(
    raw: _RawFetchResult,
    *,
    rendered: dict[str, str],
    char_limit: int,
    include_meta: bool,
) -> dict[str, Any]:
    """Assemble the public fetch payload from a raw result + rendered content.

    Shared by the synchronous ``fetch_url`` and the async ``async_fetch_url`` so
    both return a byte-identical payload shape for the same inputs.
    """
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


# --------------------------------------------------------------------------- #
# Async fetch path (Phase 3) — aiohttp with the SAME SSRF guard.              #
# A custom resolver validates every resolved IP and returns ONLY validated    #
# records, so aiohttp connects to exactly those addresses (no second          #
# resolution) — closing the DNS-rebinding TOCTOU. The original hostname is     #
# preserved for TLS SNI + certificate verification + the Host header.         #
# --------------------------------------------------------------------------- #


class _ValidatingResolver(AbstractResolver):
    """aiohttp resolver that applies web_fetch's SSRF guard at resolve time."""

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        if _is_ip_address(host):
            _assert_fetchable_ip(host)
            return [
                ResolveResult(
                    hostname=host,
                    host=host,
                    port=port,
                    family=int(family),
                    proto=0,
                    flags=int(socket.AI_NUMERICHOST),
                )
            ]
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM),
                timeout=DNS_TIMEOUT_S,
            )
        except TimeoutError:
            raise ValueError(f"web_fetch DNS resolution timed out for: {host}") from None
        except OSError as exc:
            raise ValueError(f"web_fetch could not resolve host: {host}") from exc
        results: list[ResolveResult] = []
        for fam, _type, _proto, _canon, sockaddr in infos:
            ip = str(sockaddr[0])
            _assert_fetchable_ip(ip)  # raises ValueError on a blocked address
            results.append(
                ResolveResult(
                    hostname=host,
                    host=ip,
                    port=int(sockaddr[1]) if len(sockaddr) > 1 else port,
                    family=int(fam),
                    proto=0,
                    flags=int(socket.AI_NUMERICHOST),
                )
            )
        if not results:
            raise ValueError(f"web_fetch could not resolve host: {host}")
        return results

    async def close(self) -> None:
        return None


async def _async_read_limited_body(response: aiohttp.ClientResponse) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    async for chunk in response.content.iter_chunked(65_536):
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


async def _async_fetch_uncached(url: str, *, accept: str, timeout_s: float) -> _RawFetchResult:
    current_url = _validate_public_url(url)
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": accept}
    timeout = aiohttp.ClientTimeout(connect=timeout_s, sock_connect=timeout_s, sock_read=timeout_s)
    connector = aiohttp.TCPConnector(
        resolver=_ValidatingResolver(),
        use_dns_cache=False,  # force the validating resolver on every connect
        family=socket.AF_UNSPEC,  # allow IPv4 + IPv6
        limit=8,
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        for _redirect_index in range(MAX_REDIRECTS + 1):
            # aiohttp bypasses the resolver for a bare-IP host, so validate a
            # literal-IP target here (mirrors urllib3's _new_conn). Hostnames
            # are validated by _ValidatingResolver at connect time. Re-checked
            # every hop so a redirect to a private IP is caught too.
            literal_host = urlparse(current_url).hostname or ""
            if _is_ip_address(literal_host):
                _assert_fetchable_ip(literal_host)
            try:
                async with session.get(
                    current_url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=False,
                ) as response:
                    status = int(response.status)
                    location = response.headers.get("location")
                    if status in _REDIRECT_STATUSES and location:
                        current_url = _validate_public_url(urljoin(current_url, location))
                        continue
                    if status in _REDIRECT_STATUSES:
                        raise ValueError(f"web_fetch failed: HTTP {status} redirect without Location")
                    body, truncated_body = await _async_read_limited_body(response)
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
            except aiohttp.ClientError as exc:
                # Surface an SSRF block / resolve failure (ValueError raised by the
                # resolver) as itself; wrap genuine transport errors.
                cause = exc.__cause__ or exc.__context__
                if isinstance(cause, ValueError):
                    raise cause from None
                raise RuntimeError(f"web_fetch failed: {exc}") from exc
    raise ValueError("web_fetch failed: too many redirects")


async def _async_fetch_with_cache(url: str, *, accept: str, timeout_s: float) -> _RawFetchResult:
    cache_key = (url, accept)
    now = time.monotonic()
    with _FETCH_CACHE_LOCK:
        cached = _FETCH_CACHE.get(cache_key)
        if cached is not None and cached.expires_at > now:
            _FETCH_CACHE.move_to_end(cache_key)
            return cached.value
        if cached is not None:
            _FETCH_CACHE.pop(cache_key, None)

    result = await _async_fetch_uncached(url, accept=accept, timeout_s=timeout_s)
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE[cache_key] = _FetchCacheEntry(expires_at=now + FETCH_CACHE_TTL_S, value=result)
        _FETCH_CACHE.move_to_end(cache_key)
        while len(_FETCH_CACHE) > FETCH_CACHE_MAX_ITEMS:
            _FETCH_CACHE.popitem(last=False)
    return result


async def async_fetch_url(
    url: str,
    *,
    output_format: OutputFormat = "auto",
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    include_meta: bool = False,
) -> dict[str, Any]:
    """Async twin of :func:`fetch_url` — identical SSRF guard and output shape.

    Network I/O runs on the caller's event loop; the CPU-heavy HTML->Markdown
    render is offloaded to the default executor so it never blocks the loop.
    """
    requested_format = _normalize_output_format(output_format)
    char_limit = _clamp_int(max_chars, 1_000, MAX_MAX_CHARS)
    timeout = float(min(max(float(timeout_s), 1.0), 60.0))
    accept = _accept_header(requested_format)
    raw = await _async_fetch_with_cache(url.strip(), accept=accept, timeout_s=timeout)
    loop = asyncio.get_running_loop()
    rendered = await loop.run_in_executor(
        None, functools.partial(_render_content, raw, requested_format=requested_format)
    )
    return _finish_fetch(raw, rendered=rendered, char_limit=char_limit, include_meta=include_meta)


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
        except (urllib3.exceptions.HTTPError, ValueError) as exc:
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


def _read_limited_body(response: BaseHTTPResponse) -> tuple[bytes, bool]:
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
    """Basic URL format validation — DNS + IP check happens at connect time."""
    if not url or _CONTROL_CHARS_RE.search(url):
        raise ValueError("web_fetch URL is empty or contains control characters")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("web_fetch only supports http and https URLs")
    if not parsed.hostname:
        raise ValueError("web_fetch URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("web_fetch does not allow embedded credentials")
    try:
        _ = parsed.port
    except ValueError:
        raise ValueError("web_fetch URL has a malformed port") from None
    return url


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _decode_body(body: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([^;]+)", content_type, flags=re.IGNORECASE)
    encoding = charset_match.group(1).strip().strip('"') if charset_match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _render_content(raw: _RawFetchResult, *, requested_format: OutputFormat) -> dict[str, str]:
    media_type = _media_type(raw.content_type)
    decoded = _decode_body(raw.body, raw.content_type)
    if media_type in _MARKDOWN_TYPES:
        markdown = clean_markdown_for_agent(decoded)
        return _format_markdown(markdown, requested_format=requested_format)
    if media_type in _HTML_TYPES:
        if requested_format == "html":
            return {"content": _sanitize_html(decoded, base_url=raw.final_url), "format": "html"}
        markdown = _trafilatura_markdown(decoded, base_url=raw.final_url)
        if _markdown_looks_weak(markdown, decoded):
            markdown = html_to_markdown_for_agent(decoded, base_url=raw.final_url)
        return _format_markdown(markdown, requested_format=requested_format)
    if media_type == "application/json":
        return {"content": _format_json(decoded), "format": "text" if requested_format == "text" else "markdown"}
    text = _normalize_plain_text(decoded)
    return {"content": text, "format": "text"}


def _format_markdown(markdown: str, *, requested_format: OutputFormat) -> dict[str, str]:
    if requested_format == "text":
        return {"content": _markdown_to_plain_text(markdown), "format": "text"}
    if requested_format == "html":
        return {"content": markdown, "format": "markdown"}
    return {"content": markdown, "format": "markdown"}


def html_to_markdown_for_agent(html: str, *, base_url: str = "") -> str:
    """Convert HTML to Markdown while preserving coding-doc structure."""
    cache_key = _transform_cache_key("html_markdown", html + "\0" + base_url)
    cached = _get_transform_cache(cache_key)
    if cached is not None:
        return cached
    result = _html_to_markdown_uncached(html, base_url=base_url)
    _set_transform_cache(cache_key, result)
    return result


def _html_to_markdown_uncached(html: str, *, base_url: str) -> str:
    sanitized_html = strip_non_content_html(html) or html
    soup = _soup(sanitized_html)
    _remove_noise(soup)
    _normalize_links_and_images(soup, base_url=base_url)
    root = _select_content_root(soup)
    source = str(root) if root is not None else str(soup)
    markdown = _markdownify_html(source)
    prefix = _small_metadata_prefix(soup, markdown)
    return clean_markdown_for_agent(prefix + markdown)


def _soup(html: str) -> Any:
    from bs4 import BeautifulSoup, FeatureNotFound

    try:
        return BeautifulSoup(html, "lxml")
    except (AttributeError, TypeError, ValueError, FeatureNotFound):
        return BeautifulSoup(html, "html.parser")


def _remove_noise(soup: Any) -> None:
    for tag in soup.find_all(
        [
            "script",
            "style",
            "noscript",
            "template",
            "svg",
            "canvas",
            "iframe",
            "form",
            "input",
            "button",
            "select",
            "textarea",
        ]
    ):
        tag.decompose()
    for tag in soup.find_all(True):
        # decompose() below also tears down a tag's descendants (setting their
        # .attrs to None), but find_all(True) already materialized those
        # descendants into this list. Skip any a prior iteration decomposed --
        # Tag.get() on a None .attrs raises AttributeError.
        if tag.attrs is None:
            continue
        style = str(tag.get("style") or "").lower()
        if (
            tag.has_attr("hidden")
            or tag.get("aria-hidden") == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            tag.decompose()
            continue
        marker = " ".join([str(tag.get("id") or ""), " ".join(str(c) for c in tag.get("class") or [])])
        if _NOISE_CLASS_ID_RE.search(marker):
            tag.decompose()


def _normalize_links_and_images(soup: Any, *, base_url: str) -> None:
    from bs4.element import NavigableString

    for tag in soup.find_all("a"):
        href = str(tag.get("href") or "").strip()
        if href and not href.startswith(("#", "mailto:", "tel:")):
            tag["href"] = urljoin(base_url, href)
    for tag in soup.find_all("img"):
        alt = str(tag.get("alt") or "").strip()
        if alt:
            tag.replace_with(NavigableString(alt))
        else:
            tag.decompose()


def _select_content_root(soup: Any) -> Any:
    selectors = [
        "article",
        "main",
        "[role=main]",
        ".markdown-body",
        ".theme-doc-markdown",
        ".docs-content",
        ".documentation",
        "#content",
        "#main-content",
        "body",
    ]
    candidates: list[Any] = []
    for selector in selectors:
        candidates.extend(soup.select(selector))
    if not candidates:
        return soup.body or soup
    return max(candidates, key=_content_score)


def _content_score(node: Any) -> int:
    text = node.get_text(" ", strip=True)
    score = len(text)
    score += 400 * len(node.find_all(["pre", "code"]))
    score += 150 * len(node.find_all(["h1", "h2", "h3"]))
    score += 80 * len(node.find_all("table"))
    return score


def _markdownify_html(html: str) -> str:
    import markdownify

    try:
        return str(
            markdownify.markdownify(
                html,
                heading_style="ATX",
                bullets="-",
                strip=[
                    "script",
                    "style",
                    "noscript",
                    "template",
                    "svg",
                    "canvas",
                    "iframe",
                    "form",
                    "input",
                    "button",
                    "select",
                    "textarea",
                ],
                code_language_callback=_code_language_callback,
                table_infer_header=True,
                wrap=False,
                autolinks=False,
                default_title=False,
            )
        )
    except TypeError:
        return str(markdownify.markdownify(html, heading_style="ATX", bullets="-", strip=["script", "style"]))


def _code_language_callback(el: Any) -> str | None:
    attrs = [str(el.get("class") or ""), str(el.get("data-lang") or ""), str(el.get("data-language") or "")]
    parent = getattr(el, "parent", None)
    if parent is not None:
        attrs.append(str(parent.get("class") or ""))
    joined = " ".join(attrs)
    match = _CODE_LANG_RE.search(joined)
    return match.group(1).lower() if match else None


def _small_metadata_prefix(soup: Any, markdown: str) -> str:
    parts: list[str] = []
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title and not markdown.lstrip().startswith("#"):
        parts.append(f"# {title}")
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    description = str(meta.get("content") or "").strip() if meta else ""
    if description and description not in markdown and len(description) <= 300:
        parts.append(description)
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def _sanitize_html(html: str, *, base_url: str) -> str:
    soup = _soup(strip_non_content_html(html) or html)
    _remove_noise(soup)
    _normalize_links_and_images(soup, base_url=base_url)
    root = _select_content_root(soup)
    return str(root or soup).strip()


def _trafilatura_markdown(html: str, *, base_url: str) -> str:
    import trafilatura

    try:
        extracted = trafilatura.extract(
            html,
            url=base_url or None,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_links=True,
            deduplicate=True,
            favor_precision=False,
            favor_recall=True,
        )
    except (AttributeError, TypeError, ValueError, OSError, RuntimeError):
        return ""
    return clean_markdown_for_agent(extracted or "")


def _markdown_looks_weak(markdown: str, html: str) -> bool:
    if len(html) < 5_000:
        return False
    if len(markdown.strip()) < 300:
        return True
    code_or_table = markdown.count("```") + markdown.count("|")
    return code_or_table == 0 and len(markdown) < len(html) * 0.03


def _format_json(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _normalize_plain_text(text)
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _normalize_plain_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _markdown_to_plain_text(markdown: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", markdown)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[`*_~>]", "", text)
    return _normalize_plain_text(text)


def _estimate_tokens_saved(raw: _RawFetchResult, content: str) -> int:
    media_type = _media_type(raw.content_type)
    if media_type not in _HTML_TYPES:
        return 0
    raw_tokens = max(0, len(raw.body.decode("utf-8", errors="ignore")) // 4)
    rendered_tokens = max(0, len(content) // 4)
    return max(0, raw_tokens - rendered_tokens)


def _transform_cache_key(name: str, content: str) -> tuple[str, str]:
    digest = hashlib.blake2b(content.encode("utf-8", errors="ignore"), digest_size=16).hexdigest()
    return name, digest


def _get_transform_cache(cache_key: tuple[str, str]) -> str | None:
    with _TRANSFORM_CACHE_LOCK:
        cached = _TRANSFORM_CACHE.get(cache_key)
        if cached is not None:
            _TRANSFORM_CACHE.move_to_end(cache_key)
        return cached


def _set_transform_cache(cache_key: tuple[str, str], value: str) -> None:
    with _TRANSFORM_CACHE_LOCK:
        _TRANSFORM_CACHE[cache_key] = value
        _TRANSFORM_CACHE.move_to_end(cache_key)
        while len(_TRANSFORM_CACHE) > TRANSFORM_CACHE_MAX_ITEMS:
            _TRANSFORM_CACHE.popitem(last=False)
