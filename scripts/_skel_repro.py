"""Scratch: reproduce the skeletonization test to find where 7 files come from."""

import os

os.environ["ATELIER_CODE_EMBEDDER"] = "null"
os.environ["ATELIER_ZOEKT_MODE"] = "off"
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, ".")
from atelier.core.capabilities.code_context.engine import CodeContextEngine, _exact_symbol_hits
from tests.core.test_explore_skeletonization import _build_sibling_repo

tmp = Path(tempfile.mkdtemp())
eng = CodeContextEngine(tmp, db_path=tmp / "code.sqlite")
records = _build_sibling_repo(tmp, eng)
eng.index_repo()
eng.search_symbols = lambda *a, **k: [records[0]]  # type: ignore[method-assign]

print("records[0]:", records[0].symbol_name, "|", records[0].qualified_name, "| score", records[0].score)
print("exact_hits([r0], 'Embedder'):", len(_exact_symbol_hits([records[0]], "Embedder")))
print("_semantic_candidate_files:", eng._semantic_candidate_files("Embedder", max_files=16))
print("_zoekt_candidate_files:", eng._zoekt_candidate_files("Embedder", max_files=16))
print("semantic_ranker.available:", eng._semantic_ranker.available)

p = eng.tool_explore(
    query="Embedder", max_files=8, max_symbols=20, skeletonize=True, complete_families=False, budget_tokens=30000
)
print("files:", [f.get("file_path") or f.get("path") for f in p["files"]])
print("entry_points:", [(e.get("symbol_name"), e.get("score")) for e in p["entry_points"]])
