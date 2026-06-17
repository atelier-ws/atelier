#!/usr/bin/env python3
"""Print code context index stats (language & symbol breakdown)."""
import sqlite3, sys, hashlib
from pathlib import Path

# determine db path
if len(sys.argv) > 1:
    db_path = sys.argv[1]
else:
    repo = Path.cwd()
    h = hashlib.sha256(repo.resolve().as_posix().encode()).hexdigest()[:12]
    candidate = Path.home() / ".atelier" / "workspaces" / h / "code_context.sqlite"
    if candidate.exists():
        db_path = str(candidate)
    else:
        dbs = sorted(Path.home().glob(".atelier/workspaces/*/code_context.sqlite"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
        db_path = str(dbs[0]) if dbs else None

if not db_path or not Path(db_path).exists():
    print("No index found", file=sys.stderr)
    sys.exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

total_syms = c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]

# --- Language breakdown ---
print(f"  Index: {Path(db_path).parent.name}\n")
print("  ── Language breakdown ──")
print(f"  {'Language':<16s}  {'Files':>6s}  {'Symbols':>8s}")
print("  " + "-" * 38)

# Use a CTE to avoid column-name conflict with the symbols table
c.execute("""
    SELECT f.language, COUNT(DISTINCT f.file_path) as file_cnt,
           COUNT(s.symbol_id) as sym_cnt
    FROM files f
    LEFT JOIN symbols s ON s.repo_id = f.repo_id AND s.file_path = f.file_path
    GROUP BY f.language
    ORDER BY file_cnt DESC
""")
total_f = total_s = 0
for lang, fls, syms in c.fetchall():
    total_f += fls
    total_s += syms
    print(f"  {lang:<16s}  {fls:>6d}  {syms:>8d}")
print("  " + "-" * 38)
print(f"  {'TOTAL':<16s}  {total_f:>6d}  {total_s:>8d}")

# --- Symbol kinds ---
print()
c.execute("SELECT kind, COUNT(*) FROM symbols GROUP BY kind ORDER BY COUNT(*) DESC")
print("  ── Symbol kinds ──")
print(f"  {'Kind':<22s}  {'Count':>8s}")
print("  " + "-" * 32)
kinds = dict(c.fetchall())
for kind, cnt in kinds.items():
    print(f"  {kind:<22s}  {cnt:>8d}")
print(f"  {'─'*30:>30s}")
print(f"  {'Total symbols':<22s}  {sum(kinds.values()):>8d}")

# --- Markdown ---
md_files = c.execute("SELECT COUNT(*) FROM files WHERE language=?", ("markdown",)).fetchone()[0]
heading_kinds = kinds.get("heading", 0)
print()
print(f"  Markdown: {md_files} files, {heading_kinds} heading symbols"
      + (f" ({heading_kinds//max(md_files,1)}/file)" if md_files else ""))

# --- Row counts ---
print()
for tbl in ["symbols", "symbol_fts", "file_line_fts", "references", "call_edges", "imports", "files"]:
    cnt = c.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
    print(f"  {tbl:<20s}  {cnt:>6d} rows")

print(f"\n  DB size: {Path(db_path).stat().st_size / 1048576:.1f} MB")
conn.close()
