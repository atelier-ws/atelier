# Swarm spec: LLM reranker for explore retrieval

## Goal
Implement an LLM reranking step that takes the top-N files from the existing
retrieval pipeline and reranks them using an LLM that reads query + file content.
Target: **MRR 0.55+, hit@1 0.50+** (up from current 0.386 MRR with BM25+zoekt).

## Baseline
- Current best (BM25 + zoekt + token_pin + boosts): **MRR 0.386**, hit@1 ~0.37
- CodeGraph cg_explore reference: 0.3415
- Target with LLM reranker: 0.55+ MRR

## How LLM reranking works
1. Existing retrieval (`_tool_explore_impl`) returns top-20 candidate files ranked by BM25/zoekt score
2. NEW: A second pass asks an LLM: "Given this query, rank these files by relevance"
3. The LLM reads: query text + for each file: its path, top symbols, first 40 lines
4. LLM returns a ranked list (or scores) — top-5 are returned as final answer

BM25 matches TOKENS. LLM understands INTENT. For SWE-bench issue text like
"Fix incorrect timezone handling when DateField has USE_TZ=True", BM25 finds
files containing 'timezone' and 'DateField', but the LLM understands that
`django/db/models/fields/__init__.py → DateField.clean()` is the answer even
if 'timezone' isn't in that function body.

## Where to implement
File: `src/atelier/core/capabilities/code_context/engine.py`

The pipeline in `_tool_explore_impl` (~line 3120) ends with:
```python
ranked_files: list[str] = [...]  # final file list, top max_files
return self._render_explore_result(query, ranked_files, ...)
```

Insert reranking BEFORE `_render_explore_result` when the result is used
in `tool_explore` (not in internal calls). Gate it with an env var so it can
be disabled:
```python
if os.environ.get("ATELIER_RERANK") == "1" and len(ranked_files) > 3:
    ranked_files = self._llm_rerank_files(query, ranked_files[:20])
```

## `_llm_rerank_files` implementation

Use **Ollama** running locally at `http://localhost:11434` with `qwen3.6:latest`.
No API key needed, no rate limits, parallel-safe (FITNESS_WORKERS=4 is fine).

```python
def _llm_rerank_files(self, query: str, files: list[str]) -> list[str]:
    """Rerank files using a local Ollama LLM pass. Returns reranked file list."""
    import json as _json
    import re as _re
    import urllib.request

    snippets = []
    for f in files:
        try:
            abs_path = self.repo_root / f
            content = abs_path.read_text(errors="replace")
            # Take first 30 lines for preview
            preview = "\n".join(content.splitlines()[:30])
        except Exception:
            preview = ""
        snippets.append(f"FILE {len(snippets)+1}: {f}\n{preview}")

    files_block = "\n\n---\n\n".join(snippets)
    prompt = (
        f"You are a code search ranker for a Python repository.\n"
        f"QUERY: {query}\n\n"
        f"Rank the following {len(files)} files from MOST to LEAST likely to contain "
        f"the fix for the bug described in the query. "
        f"Output ONLY a JSON array of file paths in ranked order, most relevant first. "
        f'Example: ["path/a.py", "path/b.py"]\n\n'
        f"{files_block}\n\nRespond with ONLY the JSON array, no explanation."
    )

    payload = _json.dumps({
        "model": "qwen3.6:latest",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 256},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = _json.loads(resp.read())
    text = data["choices"][0]["message"]["content"].strip()

    # Strip <think>...</think> blocks (qwen3 reasoning models emit these)
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()

    m = _re.search(r"\[.*?\]", text, _re.DOTALL)
    if not m:
        return files
    try:
        ranked = _json.loads(m.group())
        valid = [f for f in ranked if f in set(files)]
        tail = [f for f in files if f not in set(valid)]
        return (valid + tail)[:len(files)]
    except Exception:
        return files
```

## Fitness command
```bash
ATELIER_RERANK=1 FITNESS_WORKERS=4 uv run python benchmarks/codebench/fitness_explore_mrr.py
```

Ollama has no rate limits so use FITNESS_WORKERS=4 for speed.
With 405 unique queries this takes ~3-5 minutes.

## Quick smoke-test before full benchmark
Before running the full benchmark, verify ollama is responding:
```bash
curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print([m['name'] for m in json.load(sys.stdin)['models']])"
```
Should show `qwen3.6:latest` in the list.

## Alternative: path-alignment reranker (zero-cost fallback)
If ollama is unavailable, implement this simpler version first to verify the
plumbing works, then swap in the ollama version:

```python
def _simple_path_rerank(self, query: str, files: list[str]) -> list[str]:
    words = set(re.split(r'[\s_/.-]+', query.lower()))
    def path_score(f: str) -> float:
        parts = set(re.split(r'[/._-]+', f.lower()))
        return len(words & parts)
    return sorted(files, key=path_score, reverse=True)
```
This typically gives +2-4pp MRR from path alignment alone.

## Search space
Only edit: `src/atelier/core/capabilities/code_context/engine.py`

## Constraints
- Gate the reranker with `ATELIER_RERANK=1` env var (off by default so existing behavior unchanged)
- The fitness command sets this var; production calls don't
- Do NOT change the retrieval pipeline — only add the reranker after `ranked_files` is computed
- Use `FITNESS_WORKERS=1` for the fitness run (rate limits)
- If the LLM call fails, always fall back to original order (never raise)
