"""Unit tests for usage extraction across all three response encodings."""

from __future__ import annotations

import base64
import json

from benchmarks.flowlib.usage_parser import extract_usage


def _es_frame(payload: bytes, headers: bytes = b"") -> bytes:
    """Build one AWS event-stream frame around ``payload`` (CRCs zeroed)."""
    total_len = 12 + len(headers) + len(payload) + 4
    prelude = total_len.to_bytes(4, "big") + len(headers).to_bytes(4, "big") + b"\x00\x00\x00\x00"
    return prelude + headers + payload + b"\x00\x00\x00\x00"


def _bedrock_event(obj: dict) -> bytes:
    """Wrap an Anthropic event as Bedrock does: base64 in a ``bytes`` field."""
    inner = json.dumps(obj).encode()
    return json.dumps({"bytes": base64.b64encode(inner).decode()}).encode()


def test_eventstream_bedrock_message_start_and_delta() -> None:
    body = _es_frame(
        _bedrock_event(
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 100,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 50,
                        "output_tokens": 1,
                    }
                },
            }
        ),
        headers=b"\x0b:event-type",  # non-empty headers: parser must skip them
    ) + _es_frame(_bedrock_event({"type": "message_delta", "usage": {"output_tokens": 200}}))
    u = extract_usage("application/vnd.amazon.eventstream", body)
    assert u.input_tokens == 100
    assert u.cache_read_input_tokens == 900
    assert u.cache_creation_input_tokens == 50
    assert u.output_tokens == 200  # final delta wins over message_start's initial
    assert u.total_input == 1050
    assert u.total == 1250


def test_sse_anthropic_direct() -> None:
    body = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":10,'
        b'"cache_read_input_tokens":40,"cache_creation_input_tokens":0,'
        b'"output_tokens":1}}}\n\n'
        b"event: message_delta\n"
        b'data: {"type":"message_delta","usage":{"output_tokens":25}}\n\n'
        b"data: [DONE]\n\n"
    )
    u = extract_usage("text/event-stream", body)
    assert u.input_tokens == 10
    assert u.cache_read_input_tokens == 40
    assert u.output_tokens == 25
    assert u.total_input == 50


def test_json_non_streaming_snake_case() -> None:
    body = (
        b'{"usage":{"input_tokens":12,"output_tokens":8,"cache_read_input_tokens":3,"cache_creation_input_tokens":1}}'
    )
    u = extract_usage("application/json", body)
    assert (u.input_tokens, u.output_tokens) == (12, 8)
    assert (u.cache_read_input_tokens, u.cache_creation_input_tokens) == (3, 1)


def test_json_camel_case_bedrock_converse() -> None:
    body = b'{"usage":{"inputTokens":12,"outputTokens":8,"cacheReadInputTokenCount":3,"cacheWriteInputTokenCount":1}}'
    u = extract_usage("application/json", body)
    assert u.input_tokens == 12
    assert u.output_tokens == 8
    assert u.cache_read_input_tokens == 3
    assert u.cache_creation_input_tokens == 1


def test_unparseable_or_non_model_is_empty() -> None:
    assert extract_usage("application/json", b"not json").is_empty()
    assert extract_usage("text/html", b"<html></html>").is_empty()


def test_content_type_sniff_when_missing() -> None:
    body = b'{"usage":{"input_tokens":5,"output_tokens":2}}'
    assert extract_usage("", body).total == 7
