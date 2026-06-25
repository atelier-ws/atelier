import os
import re
import subprocess
import sys
from pathlib import Path

os.environ["PATH"] = os.path.expanduser("~/go/bin") + os.pathsep + os.environ.get("PATH", "")
sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

DJ = Path(open("/tmp/djroot.txt").read().strip())
DB = Path("/tmp/chanx_django.db")
CGBIN = Path("/tmp/" + open("/tmp/cgdir.txt").read().strip()) / "dist/bin/codegraph.js"
eng = CodeContextEngine(DJ, db_path=DB, autosync_enabled=False)


def explore_files(q):
    try:
        r = eng.tool_explore(q, max_files=10, auto_index=False)
        return [f.get("path", "") for f in r.get("files", [])]
    except Exception as e:
        return [f"ERR:{e}"]


def cg_explore_files(q):
    out = subprocess.run(
        ["node", str(CGBIN), "explore", q, "-p", str(DJ), "--max-files", "10"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return re.findall(r"([A-Za-z0-9_./-]+\.py)", out.stdout)[:6]


# representative real queries seen in the corpus + their true file
SAMPLES = [
    ("change_aliases", "django/db/models/sql/query.py"),
    ("select_format|CAST", "django/db/models/expressions.py"),
    ("as_sqlite", "django/db/models/expressions.py"),
    ("SQLiteNumericMixin", "django/db/models/expressions.py"),
    ("index_together", "django/db/backends/base/schema.py"),
    ("process_response", "django/middleware/cache.py"),
]
for q, true in SAMPLES:
    ef = explore_files(q)
    cf = cg_explore_files(q)
    er = next((i + 1 for i, f in enumerate(ef) if f.endswith(true)), None)
    cr = next((i + 1 for i, f in enumerate(cf) if f.endswith(true)), None)
    print(f"q={q!r:32} true={true.split('/')[-1]}")
    print(f"  explore  rank={er} files={[f.split('/')[-1] for f in ef[:5]]}")
    print(f"  cg_explore rank={cr} files={[f.split('/')[-1] for f in cf[:5]]}")
