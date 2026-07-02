"""Scratch: reproduce the ANN unit-test round trip (local embedder) to see whether
index_repo builds vectors and semantic search returns hits under the refactor."""

import os
import sqlite3
import tempfile
from pathlib import Path

os.environ["ATELIER_EMBEDDER"] = "local"
os.environ.pop("ATELIER_ANN_RETRIEVAL", None)
import sys

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

root = Path(tempfile.mkdtemp())
(root / "src").mkdir(parents=True, exist_ok=True)
(root / "src" / "__init__.py").write_text("", encoding="utf-8")
(root / "src" / "auth.py").write_text(
    "def issue_access_token(user_id: str) -> str:\n"
    '    """Create a login session token for an authenticated user."""\n'
    "    session_token = f'session:{user_id}'\n"
    "    return session_token\n",
    encoding="utf-8",
)
(root / "src" / "audit.py").write_text(
    "def create_login_history_for_authenticated_user(user_id: str) -> dict[str, str]:\n"
    '    """Record login history entries for audit review."""\n'
    "    return {'user_id': user_id}\n",
    encoding="utf-8",
)

db = root / "code.sqlite"
eng = CodeContextEngine(root, db_path=db)
print(
    "available:",
    eng._semantic_ranker.available,
    "name:",
    eng._semantic_ranker.embedder.name,
    "dim:",
    eng._semantic_ranker.embedder.dim,
)
stats = eng.index_repo()
print("indexed:", getattr(stats, "symbol_count", "?"))

c = sqlite3.connect(db)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("has symbol_vectors:", "symbol_vectors" in tabs)
if "symbol_vectors" in tabs:
    print("vector count:", c.execute("SELECT COUNT(*) FROM symbol_vectors").fetchone()[0])
print("symbols count:", c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0])
c.close()

hits = eng.search_symbols("create login token for authenticated user", limit=5, mode="semantic")
print("hits (post-index):", [(h.symbol_name, round(h.score or 0, 3)) for h in hits])

print("--- direct _build_symbol_embeddings ---")
with eng._connect() as conn:
    eng._init_schema(conn)
    iv = eng._current_index_version()
    print("index_version:", iv, "repo_id symbols:", conn.execute("SELECT COUNT(*) FROM symbols WHERE repo_id=?", (eng.repo_id,)).fetchone()[0])
    eng._build_symbol_embeddings(conn, iv)
    conn.commit()

c = sqlite3.connect(db)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("has symbol_vectors now:", "symbol_vectors" in tabs)
if "symbol_vectors" in tabs:
    print("vector count:", c.execute("SELECT COUNT(*) FROM symbol_vectors").fetchone()[0])
c.close()
eng._ann_vectors_cache = None
hits = eng.search_symbols("create login token for authenticated user", limit=5, mode="semantic")
print("hits (after direct build):", [(h.symbol_name, round(h.score or 0, 3)) for h in hits])
