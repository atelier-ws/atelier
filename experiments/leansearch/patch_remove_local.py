"""Hard-remove LocalEmbedder (feature-hashing). All call sites default to NullEmbedder
(FTS-only). memory/session/code recall fall back to BM25 lexical search."""

import os

W = "/home/pankaj/Projects/leanchain/atelier-leansearch"


def edit(path, repls, all_=False):
    p = f"{W}/{path}"
    t = open(p, encoding="utf-8").read()
    for old, new in repls:
        if old not in t:
            print(f"  MISS {path}: {old[:60]!r}")
            raise SystemExit
        t = t.replace(old, new) if all_ else t.replace(old, new, 1)
    open(p, "w", encoding="utf-8").write(t)
    print(f"  edited {path}")


lp = f"{W}/src/atelier/infra/embeddings/local.py"
if os.path.exists(lp):
    os.remove(lp)
    print("deleted local.py")
else:
    print("local.py already gone")

edit(
    "src/atelier/infra/embeddings/factory.py",
    [
        ("from .local import LocalEmbedder\n", ""),
        (
            '_PIN_CHOICES = frozenset({"local", "openai", "letta", "null"})',
            '_PIN_CHOICES = frozenset({"openai", "letta", "null"})',
        ),
        (
            '_CODE_PIN_CHOICES = frozenset({"local", "openai", "letta", "null", "ollama", "bge"})',
            '_CODE_PIN_CHOICES = frozenset({"openai", "letta", "null", "ollama", "bge"})',
        ),
        (
            '        if chosen == "local":\n            return LocalEmbedder()\n        if chosen == "null":',
            '        if chosen == "null":',
        ),
        (
            '    if backend == "sqlite":\n        return LocalEmbedder()',
            '    if backend == "sqlite":\n        return NullEmbedder()',
        ),
        (
            "        except ImportError:\n            return LocalEmbedder()",
            "        except ImportError:\n            return NullEmbedder()",
        ),
        (
            '; falling back to local embedder")\n        return LocalEmbedder()',
            '; falling back to FTS-only (null embedder)")\n        return NullEmbedder()',
        ),
        (
            "        return OpenAIEmbedder()\n    return LocalEmbedder()",
            "        return OpenAIEmbedder()\n    return NullEmbedder()",
        ),
        (
            '    if chosen == "local":\n        return LocalEmbedder()\n    if chosen == "openai":',
            '    if chosen == "openai":',
        ),
        (
            '        if os.getenv("ATELIER_OFFLINE"):\n            return LocalEmbedder()',
            '        if os.getenv("ATELIER_OFFLINE"):\n            return NullEmbedder()',
        ),
        (
            "        except RuntimeError:\n            return LocalEmbedder()",
            "        except RuntimeError:\n            return NullEmbedder()",
        ),
        ('    "LocalEmbedder",\n', ""),
    ],
)

edit(
    "src/atelier/infra/embeddings/__init__.py",
    [
        ("    LocalEmbedder,\n", ""),
        ('    "LocalEmbedder",\n', ""),
    ],
)

edit(
    "src/atelier/core/capabilities/session_recall.py",
    [
        ('    if choice == "local":\n        return make_embedder("local")\n', ""),
    ],
)

edit(
    "src/atelier/gateway/cli/commands/recall.py",
    [
        ('type=click.Choice(["local", "openai", "ollama"])', 'type=click.Choice(["openai", "ollama"])'),
        ('updated.get("recallEmbedder", "local")', 'updated.get("recallEmbedder", "null")'),
    ],
)

old_inc = (
    "        # Semantic code search ON via the offline local (feature-hashing) embedder.\n"
    "        # Default is NullEmbedder => `search` returns empty, which was the retrieval\n"
    "        # dead-end that pushed stuck agents into shell/git-archaeology/subagent\n"
    "        # spirals on hard tasks (search-empty was 100% on the runaway tasks). The\n"
    "        # hashing embedder is fully offline (no network, no model download) and\n"
    "        # microsecond-cheap; symbols are embedded on-demand at query time (no ANN\n"
    "        # lib / no prewarm needed -- the ANN path re-scores with exact cosine, so\n"
    "        # brute-force cosine is identical). Override with CODEBENCH_CODE_EMBEDDER\n"
    "        # (e.g. ollama) for a stronger neural backend.\n"
    '        env["ATELIER_CODE_EMBEDDER"] = os.environ.get("CODEBENCH_CODE_EMBEDDER", "local")\n'
)
new_inc = (
    "        # Code search runs lexical (symbol FTS + zoekt) by default -- the shipped\n"
    '        # default (NullEmbedder, FTS-only). The feature-hashing "local" embedder was\n'
    "        # removed: RETRIEVAL_EVAL measured it at -0.0004 MRR (net zero, flask -0.16)\n"
    "        # over 2306 pairs at ~3x latency, and it needed numpy. Opt into a real neural\n"
    "        # backend (ollama/bge) via CODEBENCH_CODE_EMBEDDER.\n"
    '        _code_embedder = os.environ.get("CODEBENCH_CODE_EMBEDDER", "")\n'
    "        if _code_embedder:\n"
    '            env["ATELIER_CODE_EMBEDDER"] = _code_embedder\n'
)
edit("benchmarks/codebench/incontainer.py", [(old_inc, new_inc)])

edit(
    "tests/gateway/test_recall_config_cli.py",
    [
        ('"--embedder", "local"', '"--embedder", "ollama"'),
        ('data["recallEmbedder"] == "local"', 'data["recallEmbedder"] == "ollama"'),
    ],
)

edit(
    "tests/benchmarks/context_quality/M4_scoped.py",
    [
        ('os.environ["ATELIER_CODE_EMBEDDER"] = "local"', 'os.environ["ATELIER_CODE_EMBEDDER"] = "null"'),
        ('monkeypatch.setenv("ATELIER_CODE_EMBEDDER", "local")', 'monkeypatch.setenv("ATELIER_CODE_EMBEDDER", "null")'),
    ],
    all_=True,
)
print("done")
