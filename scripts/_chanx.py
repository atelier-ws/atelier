"""Offline channel experiment: ripgrep vs zoekt vs symbol-index vs fused,
on the real django-13449 flail queries. No API calls."""

import subprocess
import sys
from pathlib import Path

DJ = Path(open("/tmp/djroot.txt").read().strip())
sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine  # noqa: E402

TARGET_FILE = "db/models/expressions.py"
TARGET_SYMS = {"as_sqlite", "select_format", "SQLiteNumericMixin"}


def is_true(file_path: str, sym: str = "") -> bool:
    f = (file_path or "").replace("\\", "/")
    if not f.endswith(TARGET_FILE):
        return False
    return (not sym) or any(s in (sym or "") for s in TARGET_SYMS)


def rank_of(items, get_file, get_sym):
    for i, it in enumerate(items, 1):
        if is_true(get_file(it), get_sym(it)):
            return i
    return None


def ripgrep(query):
    # count flood: files + total lines matching (regex)
    try:
        out = subprocess.run(["rg", "-c", "-e", query, str(DJ / "django")], capture_output=True, text=True, timeout=30)
        lines = [line for line in out.stdout.splitlines() if line.strip()]
        files = len(lines)
        total = sum(int(line.rsplit(":", 1)[1]) for line in lines if ":" in line)
        # rank: position of expressions.py in file-sorted output (ripgrep = no relevance rank)
        hit = any(TARGET_FILE in line for line in lines)
        return files, total, hit
    except Exception as e:  # noqa: BLE001 - best-effort script
        return 0, 0, f"err:{e}"


print(f"indexing django at {DJ} ...", flush=True)
DB = Path("/tmp/chanx_django.db")
if DB.exists():
    DB.unlink()
eng = CodeContextEngine(DJ, db_path=DB, autosync_enabled=False)
eng.index_repo()
print("indexed. semantic available:", eng._semantic_ranker.available, flush=True)

QUERIES = [
    ("select_format", "symbol-name (flail target)"),
    ("as_sqlite", "symbol-name (flail target)"),
    ("SQLiteNumericMixin", "symbol-name (the answer class)"),
    ("NUMERIC", "broad flail regex"),
    ("select_format|CAST", "flail regex (real)"),
    ("NUMERIC|cast_data_types|CAST", "flail regex (real)"),
    ("sqlite cast decimal to numeric", "natural-language concept"),
    ("cast value as numeric for sqlite", "natural-language concept"),
]

print(f"\n{'query':36} {'ripgrep(files/lines,hit)':26} {'symbol rank/n':14} {'zoekt rank/n':13} {'fused rank/n':13}")
print("-" * 108)
for q, label in QUERIES:
    rf, rl, rhit = ripgrep(q)
    rg_s = f"{rf}f/{rl}L {'HIT' if rhit is True else 'miss'}"
    # symbol lexical
    try:
        syms = eng.search_symbols(q, limit=10, mode="lexical", auto_index=False)
        sr = rank_of(
            syms, lambda s: s.file_path, lambda s: getattr(s, "symbol_name", "") or getattr(s, "qualified_name", "")
        )
        sym_s = f"{sr if sr else 'MISS'}/{len(syms)}"
    except Exception:  # noqa: BLE001 - best-effort script
        sym_s = "err"
    # zoekt text
    try:
        zt = eng._zoekt_text_matches(q, limit=30)
        zr = rank_of(zt, lambda m: m.file_path, lambda m: "")
        zk_s = f"{zr if zr else 'MISS'}/{len(zt)}"
    except Exception as e:  # noqa: BLE001 - best-effort script
        zk_s = f"err:{str(e)[:8]}"
    # fused
    try:
        fused = eng.tool_search(q, limit=10, mode="auto", intent="auto", auto_index=False)
        items = fused.get("items") or fused.get("matches") or []
        fr = rank_of(
            items,
            lambda it: it.get("file_path", "") or it.get("path", ""),
            lambda it: it.get("symbol_name", "") or it.get("name", ""),
        )
        fu_s = f"{fr if fr else 'MISS'}/{len(items)}"
    except Exception as e:  # noqa: BLE001 - best-effort script
        fu_s = f"err:{str(e)[:10]}"
    print(f"{q[:36]:36} {rg_s:26} {sym_s:14} {zk_s:13} {fu_s:13}  [{label}]")
