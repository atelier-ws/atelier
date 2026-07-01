# Retrieval channel comparison (11 channels x 5 golds)

`retrieval_channel_comparison.csv` — MRR/hit@1/hit@3/n/p100ms per (repo, gold_kind, channel).

Channels: 7 external (cg, ctags, ast-grep, code-index-mcp, jcodemunch, rg, cmm)
+ 4 atelier (lexical, zoekt, lexical+zoekt, lexical+zoekt+semantic).
Golds: definition, content, qwen_semantic (behavior->code), swebench, atelier_sessions.

Headline: atelier's fused (lexical+zoekt+semantic) wins every gold; on qwen_semantic
external lexical/symbol tools collapse to ~0 while fused holds 0.39.

Caveats:
- serena omitted: its LSP indexer is impractical here (~0.9 q/s, ETA ~2.4h) and it
  crashed mid-run indexing the live atelier repo. Absent in the original run too.
- qwen_semantic per-repo values for the 4 atelier channels are OVERALL-only (the CLI
  piped the per-repo JSON and an earlier _all_gks bug blanked qwen). OVERALL is exact.
- n differs slightly across harnesses (union-of-golds dedup): external counts are a
  touch lower than atelier; jcodemunch/serena drop some queries.
