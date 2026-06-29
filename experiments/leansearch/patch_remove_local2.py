"""Cleanup after LocalEmbedder removal: fix the factory test (was asserting Local
as default/fallback) + two stale comments."""

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


edit(
    "tests/core/test_embedder_factory.py",
    [
        ("from atelier.infra.embeddings.local import LocalEmbedder\n", ""),
        ("test_make_embedder_returns_local_in_stripped_env", "test_make_embedder_returns_null_in_stripped_env"),
        (
            "defaults to LocalEmbedder (deterministic feature hashing, zero deps)",
            "defaults to NullEmbedder (FTS-only; the local feature-hashing embedder was removed)",
        ),
        ("assert isinstance(e, LocalEmbedder)", "assert isinstance(e, NullEmbedder)"),
        (
            "test_make_code_embedder_falls_back_to_local_when_pinned_ollama_unavailable",
            "test_make_code_embedder_falls_back_to_null_when_pinned_ollama_unavailable",
        ),
        ("assert isinstance(embedder, LocalEmbedder)", "assert isinstance(embedder, NullEmbedder)"),
        ("assert isinstance(second, LocalEmbedder)", "assert isinstance(second, NullEmbedder)"),
    ],
)
edit(
    "src/atelier/core/capabilities/session_recall.py",
    [
        ("to the offline LocalEmbedder.", "to FTS-only (the null embedder)."),
    ],
)
edit(
    "src/atelier/core/capabilities/archival_recall/capability.py",
    [
        (
            "# LocalEmbedder returns in-process and well under this ceiling, so the guard is a",
            "# NullEmbedder returns empty in-process and well under this ceiling, so the guard is a",
        ),
    ],
)
print("done")
