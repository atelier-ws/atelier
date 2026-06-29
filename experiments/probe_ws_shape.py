from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

sup = get_zoekt_supervisor("/tmp/idx_ws_astropy__astropy")
srv = sup.server
ok = srv.wait_until_searchable(30.0)
print("searchable:", ok)
url = srv._ensure_webserver()
print("url:", url)
for q in ["Unit", "def test_cds", "Quantity"]:
    raw = srv._run_webserver_search(url, {"Q": q})
    res = raw.get("Result") or {}
    files = res.get("Files")
    nfiles = len(files) if isinstance(files, list) else "N/A"
    print(f"\nQ={q!r}  top-keys={list(raw.keys())}  Result-keys={list(res.keys())[:14]}  nFiles={nfiles}")
    if isinstance(files, list) and files:
        f0 = files[0]
        print("  file0 keys:", list(f0.keys()))
        print("  has LineMatches:", "LineMatches" in f0, " has ChunkMatches:", "ChunkMatches" in f0)
        print("  FileName:", f0.get("FileName"))
