"""Test-only deterministic embedder replacing the removed 'local' pin for the
ANN/vector-store + git-history-embed tests. Patches get_code_embedder at its
import sites. Also deletes the test of the removed 'local' recall option."""

W = "/home/pankaj/Projects/leanchain/atelier-leansearch"


def edit(path, repls, all_=False):
    p = f"{W}/{path}"
    t = open(p, encoding="utf-8").read()
    for old, new in repls:
        if old not in t:
            print(f"  MISS {path}: {old[:55]!r}")
            raise SystemExit
        t = t.replace(old, new) if all_ else t.replace(old, new, 1)
    open(p, "w", encoding="utf-8").write(t)
    print(f"  edited {path}")


HELPER = '''\
def _use_fake_code_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic test embedder (the removed 'local' pin's role): turns the
    semantic/ANN path on so the vector store + retrieval is exercised. Test-only."""
    import importlib

    class _Fake:
        dim = 384
        name = "test:hashing"

        def embed(self, texts: list[str]) -> list[list[float]]:
            from atelier.infra.storage.vector import generate_embedding

            return [generate_embedding(t, dim=self.dim) for t in texts]

    fake = _Fake()
    for _mod_name in (
        "atelier.core.capabilities.code_context.embedding",
        "atelier.infra.code_intel.git_history.embedder",
        "atelier.infra.embeddings.factory",
    ):
        try:
            _mod = importlib.import_module(_mod_name)
        except Exception:  # noqa: BLE001
            continue
        if hasattr(_mod, "get_code_embedder"):
            monkeypatch.setattr(_mod, "get_code_embedder", lambda: fake)


'''

# 1) test_ann_symbol_index.py: add helper after the vector import; swap the 5 setenvs
edit(
    "tests/core/test_ann_symbol_index.py",
    [
        (
            "from atelier.infra.storage.vector import cosine_similarity\n",
            "from atelier.infra.storage.vector import cosine_similarity\n\n\n" + HELPER.rstrip("\n") + "\n",
        ),
        ('monkeypatch.setenv("ATELIER_CODE_EMBEDDER", "local")', "_use_fake_code_embedder(monkeypatch)"),
    ],
    all_=True,
)

# 2) git_history test: add helper, swap the autouse fixture's setenv
edit(
    "tests/infra/code_intel/git_history/test_embedder.py",
    [
        (
            '@pytest.fixture(autouse=True)\ndef _pin_local_code_embedder(monkeypatch: pytest.MonkeyPatch) -> None:\n    monkeypatch.setenv("ATELIER_CODE_EMBEDDER", "local")',
            HELPER
            + "@pytest.fixture(autouse=True)\ndef _pin_fake_code_embedder(monkeypatch: pytest.MonkeyPatch) -> None:\n    _use_fake_code_embedder(monkeypatch)",
        ),
    ],
)

# 3) delete the test of the removed 'local' recall option
edit(
    "tests/core/test_recall_embedder.py",
    [
        (
            "def test_env_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:\n"
            '    monkeypatch.setenv("ATELIER_RECALL_EMBEDDER", "local")\n'
            "    session_recall._make_recall_embedder(tmp_path)\n"
            '    assert captured["make_embedder"] == ["local"]\n\n\n',
            "",
        ),
    ],
)

# 4) recall settings: stale 'local' string -> a valid embedder
edit(
    "tests/core/test_recall_settings.py",
    [
        ('embedder="local"', 'embedder="ollama"'),
    ],
)
print("done")
