"""Detached entrypoint: run a review out-of-band and append the verdict.

Spawned by the ``live_review`` PostToolUse hook via ``python -m``. Must never
raise — a detached reviewer that crashes would be invisible and useless.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    os.environ["ATELIER_IN_REVIEW"] = "1"
    parser = argparse.ArgumentParser(prog="atelier-live-reviewer")
    parser.add_argument("--session", required=True)
    parser.add_argument("--mode", default="live", choices=["live", "deep"])
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--root", default="")
    args = parser.parse_args(argv)

    try:
        from atelier.core.capabilities.live_reviewer.runner import run_review
        from atelier.core.capabilities.live_reviewer.settings import load_reviewer_settings
        from atelier.core.capabilities.live_reviewer.sink import append_verdict

        root = (
            args.root
            or os.environ.get("ATELIER_ROOT")
            or os.environ.get("ATELIER_STORE_ROOT")
            or os.path.expanduser("~/.atelier")
        )
        settings = load_reviewer_settings(root)
        verdict = run_review(args.session, args.mode, args.path, settings, root)
        append_verdict(root, args.session, verdict)
    except Exception:  # noqa: BLE001 - detached child must never surface a crash
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
