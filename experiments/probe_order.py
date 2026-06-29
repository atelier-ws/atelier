"""Check whether webserver /api/search returns files score-sorted, and what the
zoekt channel top-10 actually contains."""

from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

WS = "/tmp/idx_ws_astropy__astropy"
DB = Path("/tmp/idx_astropy__astropy.db")

eng = CodeContextEngine(Path(WS), db_path=DB, autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._schema_ready = True

srv = get_zoekt_supervisor(Path(WS)).server
srv.wait_until_searchable(30.0)
url = srv._ensure_webserver()

for q in ["Quantity", "def test_cds"]:
    raw = srv._run_webserver_search(url, {"Q": q})
    files = (raw.get("Result") or {}).get("Files") or []
    print(f"\n=== Q={q!r}  nFiles={len(files)} ===")
    print("  RAW webserver order (FileName, Score):")
    for f in files[:8]:
        print(f"    {f.get('Score'):>8}  {f.get('FileName')}")
    chan = eng._zoekt_candidate_files(q, max_files=10)
    print("  _zoekt_candidate_files top-10 (what the bench scores):")
    for fp in chan[:10]:
        print(f"    {fp}")
