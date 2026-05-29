# DLS Outline Savings — 2026-W22

Dedicated tree-sitter outlines were measured against full-file reads and the generic outline fallback for the newly dedicated languages.

| Language | Full tokens | Generic tokens | Dedicated tokens | Dedicated vs full | Dedicated vs generic | Guard | Observed |
|----------|-------------|----------------|------------------|-------------------|----------------------|-------|----------|
| bash | 104 | 36 | 25 | 75.96% saved | 30.56% saved | pass | treesitter |
| yaml | 83 | 10 | 10 | 87.95% saved | 0.0% saved | pass | treesitter |
| toml | 72 | 72 | 14 | 80.56% saved | 80.56% saved | pass | treesitter |
| json | 142 | 2 | 26 | 81.69% saved | -1200.0% saved | pass | treesitter |
| sql | 83 | 40 | 24 | 71.08% saved | 40.0% saved | pass | treesitter |

The JSON row is intentionally honest: the generic fallback is tiny for this fixture, but the dedicated outline preserves useful top-level structure while still clearing the 25% guard against the full file.
