"""Guard the lazy numpy import in code_search's semantic ANN path so a missing
numpy (atelier source mounted without deps in a container) degrades to lexical
instead of failing the whole code_search call with 'No module named numpy'."""

ENG = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/core/capabilities/code_context/engine.py"
t = open(ENG, encoding="utf-8").read()
old = "        import numpy as np\n\n        cache_key = (embedder.name, embedding_dim, index_version)\n"
new = (
    "        try:\n"
    "            import numpy as np\n"
    "        except ModuleNotFoundError:\n"
    "            # numpy absent (e.g. atelier source mounted into a container without its\n"
    "            # deps installed) -- skip the ANN matrix path and return no semantic hits\n"
    "            # so code_search degrades to lexical instead of failing the whole call.\n"
    "            return []\n"
    "\n"
    "        cache_key = (embedder.name, embedding_dim, index_version)\n"
)
if "except ModuleNotFoundError:" in t and "skip the ANN matrix path" in t:
    print("guard already present")
elif old in t:
    open(ENG, "w", encoding="utf-8").write(t.replace(old, new, 1))
    print("numpy guard added (semantic ANN -> lexical fallback)")
else:
    print("ANCHOR NOT FOUND")
    raise SystemExit
