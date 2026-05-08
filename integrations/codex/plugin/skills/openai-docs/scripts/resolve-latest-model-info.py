#!/usr/bin/env python3
"""Resolve the current OpenAI latest-model metadata from a doc page or file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

DEFAULT_URL = "https://developers.openai.com/api/docs/guides/latest-model.md"
DEFAULT_BASE_URL = "https://developers.openai.com"
USER_AGENT = "atelier-openai-docs-skill/1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve model, migration guide, and prompting guide URLs from latest-model docs."
    )
    parser.add_argument("--source", default=DEFAULT_URL, help="URL or local file path to read.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL used to expand relative links.",
    )
    return parser.parse_args()


def read_source(source: str) -> str:
    if source.startswith(("http://", "https://")):
        request = Request(source, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=20) as response:
            raw = response.read()
            if isinstance(raw, bytes):
                return raw.decode("utf-8")
            return str(raw)
    return Path(source).read_text("utf-8")


def extract_latest_model_info(markdown: str) -> dict[str, str]:
    marker = "latestModelInfo:"
    start = markdown.find(marker)
    if start == -1:
        raise ValueError("latestModelInfo block not found")

    info: dict[str, str] = {}
    for line in markdown[start + len(marker) :].splitlines():
        if not line.strip():
            continue
        if not line.startswith("  "):
            break
        stripped = line.strip()
        if ":" not in stripped:
            break
        key, value = stripped.split(":", 1)
        info[key.strip()] = value.strip().strip('"\'')

    required = {"model", "migrationGuide", "promptingGuide"}
    missing = sorted(required.difference(info))
    if missing:
        raise ValueError(f"latestModelInfo missing keys: {', '.join(missing)}")
    return info


def with_model_query(url: str, model: str) -> str:
    parsed = urlparse(url)
    if "prompt-guidance" not in parsed.path:
        return url
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("model", model)
    return urlunparse(parsed._replace(query=urlencode(query)))


def main() -> int:
    args = parse_args()
    info = extract_latest_model_info(read_source(args.source))
    model = info["model"].strip()
    payload = {
        "model": model,
        "modelSlug": model.lower(),
        "migrationGuideUrl": urljoin(args.base_url, info["migrationGuide"]),
        "promptingGuideUrl": with_model_query(
            urljoin(args.base_url, info["promptingGuide"]),
            model,
        ),
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())