"""Enable the comprehensive retrieval experiment when explicitly requested."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

if os.environ.get("ATELIER_EXPERIMENT_SYMBOL_VOTE") == "1":
    root = Path(__file__).resolve().parent
    part_dir = root / "v8_parts"
    parts = sorted(part_dir.glob("v8_*.part"))
    if not parts:
        raise RuntimeError(f"missing V8 retrieval source parts in {part_dir}")

    source = "".join(part.read_text(encoding="utf-8") for part in parts)
    module_name = "_atelier_retrieval_v8"
    module = types.ModuleType(module_name)
    module.__file__ = str(part_dir / "combined_v8_hybrid.py")
    module.__package__ = ""
    sys.modules[module_name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    module.install()
