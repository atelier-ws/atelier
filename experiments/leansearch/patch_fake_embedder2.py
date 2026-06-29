"""Repoint the test fake to patch factory.make_code_embedder (reaches direct
get_code_embedder callers); fix the recall_settings assertion."""

W = "/home/pankaj/Projects/leanchain/atelier-leansearch"


def edit(path, repls):
    p = f"{W}/{path}"
    t = open(p, encoding="utf-8").read()
    for old, new in repls:
        if old not in t:
            print(f"  MISS {path}: {old[:55]!r}")
            raise SystemExit
        t = t.replace(old, new, 1)
    open(p, "w", encoding="utf-8").write(t)
    print(f"  edited {path}")


old_body = "    import importlib\n\n    class _Fake:\n"
new_body = "    import atelier.infra.embeddings.factory as _factory\n\n    class _Fake:\n"
old_loop = (
    "    fake = _Fake()\n"
    "    for _mod_name in (\n"
    '        "atelier.core.capabilities.code_context.embedding",\n'
    '        "atelier.infra.code_intel.git_history.embedder",\n'
    '        "atelier.infra.embeddings.factory",\n'
    "    ):\n"
    "        try:\n"
    "            _mod = importlib.import_module(_mod_name)\n"
    "        except Exception:  # noqa: BLE001\n"
    "            continue\n"
    '        if hasattr(_mod, "get_code_embedder"):\n'
    '            monkeypatch.setattr(_mod, "get_code_embedder", lambda: fake)\n'
)
new_loop = (
    "    fake = _Fake()\n"
    "\n"
    "    def _fake_make(pin: str | None = None, model: str | None = None) -> object:\n"
    "        return fake\n"
    "\n"
    "    _fake_make.cache_clear = lambda: None  # type: ignore[attr-defined]\n"
    "    # get_code_embedder() looks up factory.make_code_embedder at call time, so\n"
    "    # patching it here reaches every import site, including direct callers.\n"
    '    monkeypatch.setattr(_factory, "make_code_embedder", _fake_make)\n'
)
for f in ("tests/core/test_ann_symbol_index.py", "tests/infra/code_intel/git_history/test_embedder.py"):
    edit(f, [(old_body, new_body), (old_loop, new_loop)])

edit(
    "tests/core/test_recall_settings.py",
    [
        ('assert updated["recallEmbedder"] == "local"', 'assert updated["recallEmbedder"] == "ollama"'),
    ],
)
print("done")
