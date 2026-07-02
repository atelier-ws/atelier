# Retrieval channel comparison (11 channels x 5 golds x 15 repos)

`retrieval_channel_comparison.csv` — MRR / hit@1 / hit@2 / hit@3 / n / p95ms / p100ms per (repo, gold_kind, channel).

**Channels** — atelier (`lexical`, `+zoekt` = lexical+zoekt, `+semantic` = lexical+zoekt+semantic, fused) + 8 external (`cg`, `ctags`, `ast-grep`, `rg`, `code-index-mcp`, `jcodemunch`, `cmm`, `serena`).

**Golds** — definition, content, qwen_semantic (behavior->code), swebench, atelier_sessions.

**Indexing time** — `p100ms` (max single-query latency for a repo+channel) is dominated by a one-time index/model warm-up cost paid by the first query against a freshly started channel process; steady-state queries land near `p95ms` instead (often 10-100x lower). We report this warm-up as *index time* = mean(`p100ms`) across repos, in seconds — a derived proxy for cold-start cost, not a directly instrumented build step.

## Headline

- **definition**: `lexical+zoekt+semantic` leads (MRR 0.878); next: `lexical` (0.875), `lexical+zoekt` (0.872).
- **content**: `lexical+zoekt` leads (MRR 0.876); next: `lexical+zoekt+semantic` (0.875), `rg` (0.864).
- **qwen_semantic**: `lexical+zoekt+semantic` leads (MRR 0.395); next: `cmm` (0.253), `lexical+zoekt` (0.248).
- **swebench**: `lexical+zoekt` leads (MRR 0.519); next: `lexical+zoekt+semantic` (0.505), `lexical` (0.490).
- **atelier_sessions**: `lexical+zoekt+semantic` leads (MRR 0.602); next: `lexical` (0.596), `lexical+zoekt` (0.595).

serena (LSP-based) is newly included this run: strong MRR on `definition`/`content`/`atelier_sessions`, but by far the slowest to become queryable — mean index/warm-up time **67.6s** across the corpus (peaking at 480s on `linux`) vs **0.5s** for the fastest atelier channel. On `qwen_semantic` it collapses like the other external tools (MRR 0.0049).

## Caveats

- qwen_semantic per-repo values for the 3 atelier channels are OVERALL-only (the CLI piped the per-repo JSON and an earlier `_all_gks` bug blanked qwen). OVERALL is exact.
- `n` differs slightly across harnesses (union-of-golds dedup): external counts are a touch lower than atelier; jcodemunch/serena drop some queries.
- index time is a derived proxy from `p100ms` (see above), not a directly instrumented build phase; treat it as an upper bound on cold-start cost.
- not every repo has every gold (e.g. `atelier_sessions` only applies to the `atelier` repo itself; `atelier-dev` only has `swebench`). Per-gold tables below only include repos with data for that gold.

## definition

| Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (mean, s) |
|---|---|---|---|---|---|---|
| atelier · lexical | 0.875 | 0.847 | 0.886 | 0.893 | 1586 | 0.5 |
| atelier · +zoekt | 0.872 | 0.839 | 0.884 | 0.895 | 1586 | 0.5 |
| atelier · +semantic | 0.878 | 0.851 | 0.889 | 0.898 | 1586 | 2.8 |
| cg | 0.767 | 0.737 | 0.778 | 0.789 | 1570 | 0.1 |
| ctags | 0.754 | 0.727 | 0.767 | 0.776 | 1570 | 0.0 |
| ast-grep | 0.556 | 0.471 | 0.574 | 0.622 | 1570 | 1.0 |
| rg | 0.568 | 0.454 | 0.571 | 0.639 | 1570 | 0.1 |
| code-index-mcp | 0.424 | 0.281 | 0.412 | 0.482 | 1570 | 0.8 |
| jcodemunch | 0.384 | 0.253 | 0.386 | 0.481 | 1284 | 1.0 |
| cmm | 0.720 | 0.667 | 0.741 | 0.766 | 1570 | 0.2 |
| serena | 0.632 | 0.565 | 0.659 | 0.681 | 1570 | 67.6 |

<details>
<summary>Per-repo breakdown — 14 repos</summary>

| Repo | Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (s) |
|---|---|---|---|---|---|---|---|
| astropy | atelier · lexical | 0.980 | 0.980 | 0.980 | 0.980 | 100 | 0.2 |
| astropy | atelier · +zoekt | 0.972 | 0.970 | 0.970 | 0.970 | 100 | 0.5 |
| astropy | atelier · +semantic | 0.972 | 0.970 | 0.970 | 0.970 | 100 | 0.8 |
| astropy | cg | 0.940 | 0.940 | 0.940 | 0.940 | 100 | 0.0 |
| astropy | ctags | 0.940 | 0.940 | 0.940 | 0.940 | 100 | 0.0 |
| astropy | ast-grep | 0.813 | 0.750 | 0.840 | 0.850 | 100 | 1.4 |
| astropy | rg | 0.762 | 0.640 | 0.820 | 0.870 | 100 | 0.1 |
| astropy | code-index-mcp | 0.264 | 0.000 | 0.090 | 0.430 | 100 | 1.3 |
| astropy | jcodemunch | 0.528 | 0.350 | 0.540 | 0.670 | 100 | 1.3 |
| astropy | cmm | 0.792 | 0.790 | 0.790 | 0.790 | 100 | 0.2 |
| astropy | serena | 0.858 | 0.790 | 0.910 | 0.930 | 100 | 2.5 |
| atelier | atelier · lexical | 0.810 | 0.800 | 0.820 | 0.820 | 100 | 0.7 |
| atelier | atelier · +zoekt | 0.810 | 0.800 | 0.820 | 0.820 | 100 | 0.9 |
| atelier | atelier · +semantic | 0.796 | 0.780 | 0.800 | 0.810 | 100 | 17.8 |
| atelier | cg | 0.723 | 0.720 | 0.720 | 0.720 | 100 | 0.0 |
| atelier | ctags | 0.707 | 0.700 | 0.710 | 0.710 | 100 | 0.0 |
| atelier | ast-grep | 0.557 | 0.480 | 0.570 | 0.610 | 100 | 0.7 |
| atelier | rg | 0.164 | 0.050 | 0.090 | 0.120 | 100 | 0.2 |
| atelier | code-index-mcp | 0.170 | 0.010 | 0.020 | 0.020 | 100 | 0.7 |
| atelier | jcodemunch | 0.170 | 0.110 | 0.170 | 0.230 | 100 | 1.3 |
| atelier | cmm | 0.362 | 0.310 | 0.360 | 0.420 | 100 | 0.2 |
| atelier | serena | 0.683 | 0.650 | 0.690 | 0.710 | 100 | 246.6 |
| django | atelier · lexical | 0.867 | 0.832 | 0.881 | 0.895 | 286 | 0.3 |
| django | atelier · +zoekt | 0.857 | 0.815 | 0.871 | 0.888 | 286 | 0.5 |
| django | atelier · +semantic | 0.863 | 0.829 | 0.871 | 0.888 | 286 | 0.8 |
| django | cg | 0.587 | 0.545 | 0.608 | 0.626 | 286 | 0.1 |
| django | ctags | 0.527 | 0.510 | 0.535 | 0.542 | 286 | 0.0 |
| django | ast-grep | 0.360 | 0.259 | 0.381 | 0.441 | 286 | 0.6 |
| django | rg | 0.356 | 0.245 | 0.339 | 0.402 | 286 | 0.1 |
| django | code-index-mcp | 0.382 | 0.301 | 0.395 | 0.430 | 286 | 1.3 |
| django | cmm | 0.685 | 0.615 | 0.703 | 0.759 | 286 | 0.4 |
| django | serena | 0.518 | 0.479 | 0.538 | 0.542 | 286 | 4.0 |
| matplotlib | atelier · lexical | 0.990 | 0.990 | 0.990 | 0.990 | 100 | 0.2 |
| matplotlib | atelier · +zoekt | 0.990 | 0.990 | 0.990 | 0.990 | 100 | 0.2 |
| matplotlib | atelier · +semantic | 0.990 | 0.990 | 0.990 | 0.990 | 100 | 1.0 |
| matplotlib | cg | 0.835 | 0.830 | 0.840 | 0.840 | 100 | 0.0 |
| matplotlib | ctags | 0.810 | 0.790 | 0.830 | 0.830 | 100 | 0.0 |
| matplotlib | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.3 |
| matplotlib | rg | 0.591 | 0.390 | 0.610 | 0.810 | 100 | 0.1 |
| matplotlib | code-index-mcp | 0.335 | 0.130 | 0.300 | 0.410 | 100 | 0.6 |
| matplotlib | jcodemunch | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 1.7 |
| matplotlib | cmm | 0.811 | 0.790 | 0.820 | 0.830 | 100 | 0.1 |
| matplotlib | serena | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 4.7 |
| seaborn | atelier · lexical | 0.966 | 0.960 | 0.970 | 0.970 | 100 | 0.2 |
| seaborn | atelier · +zoekt | 0.955 | 0.940 | 0.950 | 0.970 | 100 | 0.3 |
| seaborn | atelier · +semantic | 0.966 | 0.960 | 0.970 | 0.970 | 100 | 0.6 |
| seaborn | cg | 0.870 | 0.860 | 0.870 | 0.880 | 100 | 0.0 |
| seaborn | ctags | 0.815 | 0.810 | 0.820 | 0.820 | 100 | 0.0 |
| seaborn | ast-grep | 0.743 | 0.670 | 0.730 | 0.810 | 100 | 0.2 |
| seaborn | rg | 0.627 | 0.490 | 0.680 | 0.710 | 100 | 0.1 |
| seaborn | code-index-mcp | 0.665 | 0.580 | 0.710 | 0.740 | 100 | 0.1 |
| seaborn | jcodemunch | 0.474 | 0.300 | 0.530 | 0.580 | 100 | 0.1 |
| seaborn | cmm | 0.858 | 0.800 | 0.880 | 0.900 | 100 | 0.1 |
| seaborn | serena | 0.682 | 0.600 | 0.740 | 0.740 | 100 | 2.8 |
| flask | atelier · lexical | 0.673 | 0.630 | 0.710 | 0.720 | 100 | 0.2 |
| flask | atelier · +zoekt | 0.634 | 0.540 | 0.680 | 0.710 | 100 | 0.2 |
| flask | atelier · +semantic | 0.683 | 0.640 | 0.720 | 0.730 | 100 | 0.4 |
| flask | cg | 0.675 | 0.628 | 0.681 | 0.713 | 94 | 0.0 |
| flask | ctags | 0.660 | 0.606 | 0.702 | 0.713 | 94 | 0.0 |
| flask | ast-grep | 0.592 | 0.479 | 0.628 | 0.649 | 94 | 0.2 |
| flask | rg | 0.605 | 0.532 | 0.628 | 0.670 | 94 | 0.1 |
| flask | code-index-mcp | 0.509 | 0.447 | 0.489 | 0.553 | 94 | 0.2 |
| flask | jcodemunch | 0.393 | 0.277 | 0.404 | 0.479 | 94 | 0.1 |
| flask | cmm | 0.669 | 0.617 | 0.681 | 0.723 | 94 | 0.1 |
| flask | serena | 0.591 | 0.468 | 0.628 | 0.670 | 94 | 0.5 |
| requests | atelier · lexical | 0.934 | 0.910 | 0.940 | 0.940 | 100 | 0.2 |
| requests | atelier · +zoekt | 0.952 | 0.920 | 0.960 | 0.980 | 100 | 0.2 |
| requests | atelier · +semantic | 0.934 | 0.910 | 0.940 | 0.940 | 100 | 0.5 |
| requests | cg | 0.943 | 0.920 | 0.960 | 0.960 | 100 | 0.0 |
| requests | ctags | 0.910 | 0.890 | 0.910 | 0.920 | 100 | 0.0 |
| requests | ast-grep | 0.881 | 0.850 | 0.870 | 0.910 | 100 | 0.2 |
| requests | rg | 0.863 | 0.810 | 0.870 | 0.910 | 100 | 0.0 |
| requests | code-index-mcp | 0.810 | 0.750 | 0.810 | 0.850 | 100 | 0.1 |
| requests | jcodemunch | 0.659 | 0.490 | 0.710 | 0.830 | 100 | 0.1 |
| requests | cmm | 0.812 | 0.790 | 0.820 | 0.820 | 100 | 0.1 |
| requests | serena | 0.860 | 0.800 | 0.890 | 0.910 | 100 | 0.4 |
| xarray | atelier · lexical | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.3 |
| xarray | atelier · +zoekt | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.3 |
| xarray | atelier · +semantic | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.7 |
| xarray | cg | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.0 |
| xarray | ctags | 0.983 | 0.980 | 0.980 | 0.990 | 100 | 0.0 |
| xarray | ast-grep | 0.715 | 0.580 | 0.750 | 0.830 | 100 | 0.4 |
| xarray | rg | 0.666 | 0.540 | 0.660 | 0.740 | 100 | 0.0 |
| xarray | code-index-mcp | 0.152 | 0.000 | 0.000 | 0.000 | 100 | 0.3 |
| xarray | jcodemunch | 0.444 | 0.180 | 0.410 | 0.660 | 100 | 0.2 |
| xarray | cmm | 0.920 | 0.880 | 0.960 | 0.960 | 100 | 0.1 |
| xarray | serena | 0.711 | 0.560 | 0.760 | 0.840 | 100 | 0.8 |
| pylint | atelier · lexical | 0.973 | 0.970 | 0.970 | 0.970 | 100 | 0.2 |
| pylint | atelier · +zoekt | 0.970 | 0.970 | 0.970 | 0.970 | 100 | 0.4 |
| pylint | atelier · +semantic | 0.973 | 0.970 | 0.970 | 0.970 | 100 | 0.8 |
| pylint | cg | 0.915 | 0.910 | 0.910 | 0.910 | 100 | 0.0 |
| pylint | ctags | 0.903 | 0.900 | 0.900 | 0.910 | 100 | 0.0 |
| pylint | ast-grep | 0.675 | 0.530 | 0.750 | 0.790 | 100 | 0.2 |
| pylint | rg | 0.606 | 0.480 | 0.600 | 0.670 | 100 | 0.1 |
| pylint | code-index-mcp | 0.679 | 0.600 | 0.640 | 0.710 | 100 | 0.7 |
| pylint | jcodemunch | 0.394 | 0.240 | 0.350 | 0.480 | 100 | 0.5 |
| pylint | cmm | 0.810 | 0.790 | 0.830 | 0.830 | 100 | 0.1 |
| pylint | serena | 0.834 | 0.780 | 0.860 | 0.890 | 100 | 2.2 |
| pytest | atelier · lexical | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.1 |
| pytest | atelier · +zoekt | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.3 |
| pytest | atelier · +semantic | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.6 |
| pytest | cg | 0.972 | 0.970 | 0.970 | 0.970 | 100 | 0.0 |
| pytest | ctags | 0.965 | 0.960 | 0.970 | 0.970 | 100 | 0.0 |
| pytest | ast-grep | 0.804 | 0.690 | 0.860 | 0.920 | 100 | 0.2 |
| pytest | rg | 0.698 | 0.530 | 0.760 | 0.860 | 100 | 0.1 |
| pytest | code-index-mcp | 0.395 | 0.000 | 0.630 | 0.770 | 100 | 0.2 |
| pytest | jcodemunch | 0.659 | 0.480 | 0.680 | 0.810 | 100 | 0.2 |
| pytest | cmm | 0.970 | 0.960 | 0.980 | 0.980 | 100 | 0.1 |
| pytest | serena | 0.966 | 0.960 | 0.960 | 0.970 | 100 | 0.6 |
| scikit-learn | atelier · lexical | 0.674 | 0.620 | 0.690 | 0.700 | 100 | 0.2 |
| scikit-learn | atelier · +zoekt | 0.705 | 0.650 | 0.730 | 0.730 | 100 | 0.2 |
| scikit-learn | atelier · +semantic | 0.740 | 0.690 | 0.760 | 0.770 | 100 | 0.7 |
| scikit-learn | cg | 0.663 | 0.600 | 0.680 | 0.690 | 100 | 0.0 |
| scikit-learn | ctags | 0.596 | 0.500 | 0.650 | 0.670 | 100 | 0.0 |
| scikit-learn | ast-grep | 0.562 | 0.460 | 0.550 | 0.660 | 100 | 0.4 |
| scikit-learn | rg | 0.532 | 0.460 | 0.520 | 0.550 | 100 | 0.1 |
| scikit-learn | code-index-mcp | 0.193 | 0.000 | 0.280 | 0.330 | 100 | 0.6 |
| scikit-learn | jcodemunch | 0.336 | 0.230 | 0.330 | 0.400 | 100 | 1.0 |
| scikit-learn | cmm | 0.515 | 0.400 | 0.600 | 0.630 | 100 | 0.1 |
| scikit-learn | serena | 0.572 | 0.480 | 0.600 | 0.620 | 100 | 1.3 |
| sphinx | atelier · lexical | 0.616 | 0.500 | 0.670 | 0.700 | 100 | 0.2 |
| sphinx | atelier · +zoekt | 0.611 | 0.490 | 0.670 | 0.700 | 100 | 0.5 |
| sphinx | atelier · +semantic | 0.616 | 0.500 | 0.670 | 0.700 | 100 | 0.4 |
| sphinx | cg | 0.583 | 0.500 | 0.620 | 0.663 | 92 | 0.0 |
| sphinx | ctags | 0.613 | 0.511 | 0.652 | 0.685 | 92 | 0.0 |
| sphinx | ast-grep | 0.550 | 0.467 | 0.533 | 0.587 | 92 | 0.3 |
| sphinx | rg | 0.550 | 0.435 | 0.533 | 0.630 | 92 | 0.1 |
| sphinx | code-index-mcp | 0.420 | 0.293 | 0.402 | 0.522 | 92 | 0.4 |
| sphinx | jcodemunch | 0.393 | 0.272 | 0.380 | 0.446 | 92 | 0.5 |
| sphinx | cmm | 0.478 | 0.380 | 0.522 | 0.554 | 92 | 0.2 |
| sphinx | serena | 0.513 | 0.413 | 0.511 | 0.576 | 92 | 1.5 |
| sympy | atelier · lexical | 0.774 | 0.700 | 0.790 | 0.820 | 100 | 0.2 |
| sympy | atelier · +zoekt | 0.774 | 0.700 | 0.790 | 0.820 | 100 | 0.3 |
| sympy | atelier · +semantic | 0.790 | 0.710 | 0.820 | 0.850 | 100 | 0.5 |
| sympy | cg | 0.744 | 0.643 | 0.765 | 0.796 | 98 | 0.1 |
| sympy | ctags | 0.750 | 0.663 | 0.775 | 0.796 | 98 | 0.0 |
| sympy | ast-grep | 0.675 | 0.561 | 0.704 | 0.735 | 98 | 0.8 |
| sympy | rg | 0.650 | 0.551 | 0.663 | 0.704 | 98 | 0.1 |
| sympy | code-index-mcp | 0.328 | 0.163 | 0.276 | 0.296 | 98 | 1.0 |
| sympy | jcodemunch | 0.512 | 0.347 | 0.480 | 0.643 | 98 | 1.0 |
| sympy | cmm | 0.641 | 0.551 | 0.643 | 0.673 | 98 | 0.1 |
| sympy | serena | 0.631 | 0.490 | 0.684 | 0.735 | 98 | 15.6 |
| linux | atelier · lexical | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 2.8 |
| linux | atelier · +zoekt | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 2.8 |
| linux | atelier · +semantic | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 2.7 |
| linux | cg | 0.608 | 0.580 | 0.630 | 0.630 | 100 | 0.4 |
| linux | ctags | 0.790 | 0.790 | 0.790 | 0.790 | 100 | 0.0 |
| linux | ast-grep | 0.231 | 0.210 | 0.230 | 0.250 | 100 | 7.5 |
| linux | rg | 0.680 | 0.590 | 0.660 | 0.740 | 100 | 0.1 |
| linux | code-index-mcp | 0.722 | 0.630 | 0.760 | 0.790 | 100 | 1.6 |
| linux | jcodemunch | 0.036 | 0.020 | 0.030 | 0.030 | 100 | 4.7 |
| linux | cmm | 0.791 | 0.740 | 0.830 | 0.840 | 100 | 1.0 |
| linux | serena | 0.626 | 0.580 | 0.660 | 0.660 | 100 | 480.0 |

</details>

## content

| Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (mean, s) |
|---|---|---|---|---|---|---|
| atelier · lexical | 0.848 | 0.819 | 0.856 | 0.868 | 1457 | 0.5 |
| atelier · +zoekt | 0.876 | 0.843 | 0.882 | 0.900 | 1457 | 0.5 |
| atelier · +semantic | 0.875 | 0.843 | 0.881 | 0.901 | 1457 | 2.8 |
| cg | 0.000 | 0.000 | 0.000 | 0.000 | 1444 | 0.1 |
| ctags | 0.000 | 0.000 | 0.000 | 0.000 | 1444 | 0.0 |
| ast-grep | 0.589 | 0.567 | 0.592 | 0.606 | 1444 | 1.0 |
| rg | 0.864 | 0.828 | 0.871 | 0.891 | 1444 | 0.1 |
| code-index-mcp | 0.542 | 0.414 | 0.564 | 0.640 | 1444 | 0.8 |
| jcodemunch | 0.689 | 0.652 | 0.700 | 0.717 | 1287 | 1.0 |
| cmm | 0.709 | 0.673 | 0.722 | 0.740 | 1444 | 0.2 |
| serena | 0.754 | 0.731 | 0.754 | 0.764 | 1444 | 67.6 |

<details>
<summary>Per-repo breakdown — 14 repos</summary>

| Repo | Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (s) |
|---|---|---|---|---|---|---|---|
| astropy | atelier · lexical | 0.850 | 0.850 | 0.850 | 0.850 | 100 | 0.2 |
| astropy | atelier · +zoekt | 0.995 | 0.990 | 1.000 | 1.000 | 100 | 0.5 |
| astropy | atelier · +semantic | 0.995 | 0.990 | 1.000 | 1.000 | 100 | 0.8 |
| astropy | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| astropy | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| astropy | ast-grep | 0.910 | 0.910 | 0.910 | 0.910 | 100 | 1.4 |
| astropy | rg | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.1 |
| astropy | code-index-mcp | 0.330 | 0.060 | 0.090 | 0.690 | 100 | 1.3 |
| astropy | jcodemunch | 0.910 | 0.910 | 0.910 | 0.910 | 100 | 1.3 |
| astropy | cmm | 0.910 | 0.910 | 0.910 | 0.910 | 100 | 0.2 |
| astropy | serena | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 2.5 |
| atelier | atelier · lexical | 0.530 | 0.510 | 0.510 | 0.510 | 100 | 0.7 |
| atelier | atelier · +zoekt | 0.530 | 0.510 | 0.510 | 0.510 | 100 | 0.9 |
| atelier | atelier · +semantic | 0.637 | 0.560 | 0.640 | 0.710 | 100 | 17.8 |
| atelier | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| atelier | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| atelier | ast-grep | 0.420 | 0.420 | 0.420 | 0.420 | 100 | 0.7 |
| atelier | rg | 0.883 | 0.780 | 0.980 | 0.990 | 100 | 0.2 |
| atelier | code-index-mcp | 0.550 | 0.150 | 0.950 | 0.950 | 100 | 0.7 |
| atelier | jcodemunch | 0.203 | 0.050 | 0.350 | 0.350 | 100 | 1.3 |
| atelier | cmm | 0.462 | 0.400 | 0.490 | 0.540 | 100 | 0.2 |
| atelier | serena | 0.495 | 0.490 | 0.500 | 0.500 | 100 | 246.6 |
| django | atelier · lexical | 0.942 | 0.917 | 0.949 | 0.968 | 157 | 0.3 |
| django | atelier · +zoekt | 0.964 | 0.955 | 0.968 | 0.968 | 157 | 0.5 |
| django | atelier · +semantic | 0.953 | 0.936 | 0.955 | 0.968 | 157 | 0.8 |
| django | cg | 0.000 | 0.000 | 0.000 | 0.000 | 157 | 0.1 |
| django | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 157 | 0.0 |
| django | ast-grep | 0.268 | 0.268 | 0.268 | 0.268 | 157 | 0.6 |
| django | rg | 1.000 | 1.000 | 1.000 | 1.000 | 157 | 0.1 |
| django | code-index-mcp | 0.280 | 0.280 | 0.280 | 0.280 | 157 | 1.3 |
| django | cmm | 0.268 | 0.261 | 0.268 | 0.268 | 157 | 0.4 |
| django | serena | 0.951 | 0.943 | 0.949 | 0.962 | 157 | 4.0 |
| matplotlib | atelier · lexical | 0.943 | 0.940 | 0.940 | 0.950 | 100 | 0.2 |
| matplotlib | atelier · +zoekt | 0.943 | 0.940 | 0.940 | 0.950 | 100 | 0.2 |
| matplotlib | atelier · +semantic | 0.987 | 0.980 | 0.990 | 0.990 | 100 | 1.0 |
| matplotlib | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| matplotlib | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| matplotlib | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.3 |
| matplotlib | rg | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.1 |
| matplotlib | code-index-mcp | 0.930 | 0.930 | 0.930 | 0.930 | 100 | 0.6 |
| matplotlib | jcodemunch | 0.923 | 0.920 | 0.920 | 0.930 | 100 | 1.7 |
| matplotlib | cmm | 0.930 | 0.930 | 0.930 | 0.930 | 100 | 0.1 |
| matplotlib | serena | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 4.7 |
| seaborn | atelier · lexical | 0.921 | 0.910 | 0.930 | 0.930 | 100 | 0.2 |
| seaborn | atelier · +zoekt | 0.980 | 0.970 | 0.980 | 0.990 | 100 | 0.3 |
| seaborn | atelier · +semantic | 0.921 | 0.910 | 0.930 | 0.930 | 100 | 0.6 |
| seaborn | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| seaborn | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| seaborn | ast-grep | 0.830 | 0.820 | 0.830 | 0.840 | 100 | 0.2 |
| seaborn | rg | 0.979 | 0.970 | 0.980 | 0.980 | 100 | 0.1 |
| seaborn | code-index-mcp | 0.825 | 0.810 | 0.830 | 0.840 | 100 | 0.1 |
| seaborn | jcodemunch | 0.830 | 0.810 | 0.840 | 0.850 | 100 | 0.1 |
| seaborn | cmm | 0.837 | 0.820 | 0.840 | 0.860 | 100 | 0.1 |
| seaborn | serena | 0.968 | 0.950 | 0.980 | 0.980 | 100 | 2.8 |
| flask | atelier · lexical | 0.615 | 0.560 | 0.650 | 0.660 | 100 | 0.2 |
| flask | atelier · +zoekt | 0.695 | 0.580 | 0.730 | 0.800 | 100 | 0.2 |
| flask | atelier · +semantic | 0.630 | 0.570 | 0.670 | 0.680 | 100 | 0.4 |
| flask | cg | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.0 |
| flask | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.0 |
| flask | ast-grep | 0.523 | 0.484 | 0.526 | 0.567 | 97 | 0.2 |
| flask | rg | 0.476 | 0.402 | 0.484 | 0.536 | 97 | 0.1 |
| flask | code-index-mcp | 0.485 | 0.402 | 0.515 | 0.536 | 97 | 0.2 |
| flask | jcodemunch | 0.550 | 0.495 | 0.546 | 0.577 | 97 | 0.1 |
| flask | cmm | 0.701 | 0.619 | 0.732 | 0.763 | 97 | 0.1 |
| flask | serena | 0.537 | 0.505 | 0.536 | 0.546 | 97 | 0.5 |
| requests | atelier · lexical | 0.906 | 0.870 | 0.910 | 0.940 | 100 | 0.2 |
| requests | atelier · +zoekt | 0.917 | 0.880 | 0.910 | 0.940 | 100 | 0.2 |
| requests | atelier · +semantic | 0.906 | 0.870 | 0.910 | 0.940 | 100 | 0.5 |
| requests | cg | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.0 |
| requests | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.0 |
| requests | ast-grep | 0.816 | 0.753 | 0.856 | 0.866 | 97 | 0.2 |
| requests | rg | 0.796 | 0.732 | 0.804 | 0.845 | 97 | 0.0 |
| requests | code-index-mcp | 0.812 | 0.763 | 0.804 | 0.845 | 97 | 0.1 |
| requests | jcodemunch | 0.803 | 0.763 | 0.804 | 0.825 | 97 | 0.1 |
| requests | cmm | 0.812 | 0.722 | 0.845 | 0.887 | 97 | 0.1 |
| requests | serena | 0.782 | 0.722 | 0.794 | 0.814 | 97 | 0.4 |
| xarray | atelier · lexical | 0.980 | 0.980 | 0.980 | 0.980 | 100 | 0.3 |
| xarray | atelier · +zoekt | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.3 |
| xarray | atelier · +semantic | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.7 |
| xarray | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| xarray | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| xarray | ast-grep | 0.980 | 0.980 | 0.980 | 0.980 | 100 | 0.4 |
| xarray | rg | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.0 |
| xarray | code-index-mcp | 0.212 | 0.020 | 0.020 | 0.020 | 100 | 0.3 |
| xarray | jcodemunch | 0.980 | 0.980 | 0.980 | 0.980 | 100 | 0.2 |
| xarray | cmm | 0.980 | 0.980 | 0.980 | 0.980 | 100 | 0.1 |
| xarray | serena | 0.990 | 0.990 | 0.990 | 0.990 | 100 | 0.8 |
| pylint | atelier · lexical | 0.950 | 0.950 | 0.950 | 0.950 | 100 | 0.2 |
| pylint | atelier · +zoekt | 0.970 | 0.970 | 0.970 | 0.970 | 100 | 0.4 |
| pylint | atelier · +semantic | 0.950 | 0.950 | 0.950 | 0.950 | 100 | 0.8 |
| pylint | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| pylint | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| pylint | ast-grep | 0.780 | 0.780 | 0.780 | 0.780 | 100 | 0.2 |
| pylint | rg | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.1 |
| pylint | code-index-mcp | 0.780 | 0.780 | 0.780 | 0.780 | 100 | 0.7 |
| pylint | jcodemunch | 0.780 | 0.780 | 0.780 | 0.780 | 100 | 0.5 |
| pylint | cmm | 0.780 | 0.780 | 0.780 | 0.780 | 100 | 0.1 |
| pylint | serena | 0.986 | 0.980 | 0.980 | 0.990 | 100 | 2.2 |
| pytest | atelier · lexical | 0.990 | 0.990 | 0.990 | 0.990 | 100 | 0.1 |
| pytest | atelier · +zoekt | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.3 |
| pytest | atelier · +semantic | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.6 |
| pytest | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| pytest | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| pytest | ast-grep | 0.970 | 0.970 | 0.970 | 0.970 | 100 | 0.2 |
| pytest | rg | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.1 |
| pytest | code-index-mcp | 0.461 | 0.050 | 0.680 | 0.960 | 100 | 0.2 |
| pytest | jcodemunch | 0.970 | 0.970 | 0.970 | 0.970 | 100 | 0.2 |
| pytest | cmm | 0.970 | 0.970 | 0.970 | 0.970 | 100 | 0.1 |
| pytest | serena | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.6 |
| scikit-learn | atelier · lexical | 0.758 | 0.710 | 0.780 | 0.780 | 100 | 0.2 |
| scikit-learn | atelier · +zoekt | 0.793 | 0.740 | 0.800 | 0.840 | 100 | 0.2 |
| scikit-learn | atelier · +semantic | 0.773 | 0.730 | 0.770 | 0.810 | 100 | 0.7 |
| scikit-learn | cg | 0.000 | 0.000 | 0.000 | 0.000 | 99 | 0.0 |
| scikit-learn | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 99 | 0.0 |
| scikit-learn | ast-grep | 0.567 | 0.525 | 0.566 | 0.586 | 99 | 0.4 |
| scikit-learn | rg | 0.620 | 0.566 | 0.606 | 0.646 | 99 | 0.1 |
| scikit-learn | code-index-mcp | 0.336 | 0.151 | 0.414 | 0.444 | 99 | 0.6 |
| scikit-learn | jcodemunch | 0.626 | 0.586 | 0.606 | 0.646 | 99 | 1.0 |
| scikit-learn | cmm | 0.661 | 0.616 | 0.687 | 0.697 | 99 | 0.1 |
| scikit-learn | serena | 0.618 | 0.596 | 0.606 | 0.606 | 99 | 1.3 |
| sphinx | atelier · lexical | 0.734 | 0.630 | 0.770 | 0.810 | 100 | 0.2 |
| sphinx | atelier · +zoekt | 0.724 | 0.610 | 0.770 | 0.810 | 100 | 0.5 |
| sphinx | atelier · +semantic | 0.737 | 0.640 | 0.760 | 0.810 | 100 | 0.4 |
| sphinx | cg | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.0 |
| sphinx | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.0 |
| sphinx | ast-grep | 0.532 | 0.443 | 0.526 | 0.598 | 97 | 0.3 |
| sphinx | rg | 0.607 | 0.495 | 0.608 | 0.670 | 97 | 0.1 |
| sphinx | code-index-mcp | 0.606 | 0.495 | 0.639 | 0.691 | 97 | 0.4 |
| sphinx | jcodemunch | 0.629 | 0.557 | 0.639 | 0.670 | 97 | 0.5 |
| sphinx | cmm | 0.581 | 0.484 | 0.619 | 0.649 | 97 | 0.2 |
| sphinx | serena | 0.480 | 0.392 | 0.474 | 0.526 | 97 | 1.5 |
| sympy | atelier · lexical | 0.698 | 0.590 | 0.720 | 0.780 | 100 | 0.2 |
| sympy | atelier · +zoekt | 0.698 | 0.590 | 0.720 | 0.780 | 100 | 0.3 |
| sympy | atelier · +semantic | 0.710 | 0.610 | 0.720 | 0.790 | 100 | 0.5 |
| sympy | cg | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.1 |
| sympy | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 97 | 0.0 |
| sympy | ast-grep | 0.671 | 0.577 | 0.680 | 0.732 | 97 | 0.8 |
| sympy | rg | 0.625 | 0.505 | 0.629 | 0.711 | 97 | 0.1 |
| sympy | code-index-mcp | 0.464 | 0.320 | 0.443 | 0.505 | 97 | 1.0 |
| sympy | jcodemunch | 0.644 | 0.546 | 0.649 | 0.732 | 97 | 1.0 |
| sympy | cmm | 0.590 | 0.464 | 0.629 | 0.701 | 97 | 0.1 |
| sympy | serena | 0.624 | 0.526 | 0.629 | 0.670 | 97 | 15.6 |
| linux | atelier · lexical | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 2.8 |
| linux | atelier · +zoekt | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 2.8 |
| linux | atelier · +semantic | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 2.7 |
| linux | cg | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.4 |
| linux | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 100 | 0.0 |
| linux | ast-grep | 0.170 | 0.170 | 0.170 | 0.170 | 100 | 7.5 |
| linux | rg | 1.000 | 1.000 | 1.000 | 1.000 | 100 | 0.1 |
| linux | code-index-mcp | 0.678 | 0.670 | 0.680 | 0.690 | 100 | 1.6 |
| linux | jcodemunch | 0.100 | 0.100 | 0.100 | 0.100 | 100 | 4.7 |
| linux | cmm | 0.690 | 0.690 | 0.690 | 0.690 | 100 | 1.0 |
| linux | serena | 0.990 | 0.990 | 0.990 | 0.990 | 100 | 480.0 |

</details>

## qwen_semantic

| Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (mean, s) |
|---|---|---|---|---|---|---|
| atelier · lexical | 0.193 | 0.164 | 0.199 | 0.210 | 1802 | 0.5 |
| atelier · +zoekt | 0.248 | 0.199 | 0.253 | 0.280 | 1802 | 0.5 |
| atelier · +semantic | 0.395 | 0.349 | 0.409 | 0.433 | 1802 | 2.8 |
| cg | 0.051 | 0.033 | 0.047 | 0.063 | 1800 | 0.1 |
| ctags | 0.000 | 0.000 | 0.000 | 0.000 | 1800 | 0.0 |
| ast-grep | 0.000 | 0.000 | 0.000 | 0.001 | 1800 | 1.0 |
| rg | 0.000 | 0.000 | 0.000 | 0.000 | 1800 | 0.1 |
| code-index-mcp | 0.003 | 0.000 | 0.001 | 0.002 | 1800 | 0.8 |
| jcodemunch | 0.019 | 0.010 | 0.018 | 0.022 | 1670 | 1.0 |
| cmm | 0.253 | 0.176 | 0.254 | 0.307 | 1800 | 0.2 |
| serena | 0.005 | 0.003 | 0.006 | 0.007 | 1800 | 67.6 |

<details>
<summary>Per-repo breakdown — 14 repos</summary>

| Repo | Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (s) |
|---|---|---|---|---|---|---|---|
| astropy | atelier · lexical | 0.139 | 0.139 | 0.139 | 0.139 | 130 | 0.2 |
| astropy | atelier · +zoekt | 0.229 | 0.200 | 0.223 | 0.254 | 130 | 0.5 |
| astropy | atelier · +semantic | 0.541 | 0.462 | 0.600 | 0.608 | 130 | 0.8 |
| astropy | cg | 0.021 | 0.008 | 0.015 | 0.038 | 130 | 0.0 |
| astropy | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| astropy | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 1.4 |
| astropy | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| astropy | code-index-mcp | 0.001 | 0.000 | 0.000 | 0.000 | 130 | 1.3 |
| astropy | jcodemunch | 0.015 | 0.008 | 0.023 | 0.023 | 130 | 1.3 |
| astropy | cmm | 0.250 | 0.192 | 0.231 | 0.277 | 130 | 0.2 |
| astropy | serena | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 2.5 |
| atelier | atelier · lexical | 0.421 | 0.268 | 0.438 | 0.518 | 112 | 0.7 |
| atelier | atelier · +zoekt | 0.423 | 0.277 | 0.429 | 0.518 | 112 | 0.9 |
| atelier | atelier · +semantic | 0.411 | 0.277 | 0.393 | 0.491 | 112 | 17.8 |
| atelier | cg | 0.031 | 0.027 | 0.027 | 0.027 | 112 | 0.0 |
| atelier | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 112 | 0.0 |
| atelier | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 112 | 0.7 |
| atelier | rg | 0.000 | 0.000 | 0.000 | 0.000 | 112 | 0.2 |
| atelier | code-index-mcp | 0.001 | 0.000 | 0.000 | 0.000 | 112 | 0.7 |
| atelier | jcodemunch | 0.013 | 0.009 | 0.009 | 0.009 | 112 | 1.3 |
| atelier | cmm | 0.222 | 0.152 | 0.205 | 0.250 | 112 | 0.2 |
| atelier | serena | 0.009 | 0.009 | 0.009 | 0.009 | 112 | 246.6 |
| django | atelier · lexical | 0.503 | 0.377 | 0.538 | 0.577 | 130 | 0.3 |
| django | atelier · +zoekt | 0.495 | 0.377 | 0.523 | 0.569 | 130 | 0.5 |
| django | atelier · +semantic | 0.587 | 0.477 | 0.615 | 0.661 | 130 | 0.8 |
| django | cg | 0.015 | 0.008 | 0.008 | 0.008 | 130 | 0.1 |
| django | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| django | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.6 |
| django | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| django | code-index-mcp | 0.001 | 0.000 | 0.000 | 0.000 | 130 | 1.3 |
| django | cmm | 0.162 | 0.108 | 0.162 | 0.208 | 130 | 0.4 |
| django | serena | 0.009 | 0.008 | 0.008 | 0.008 | 130 | 4.0 |
| matplotlib | atelier · lexical | 0.092 | 0.092 | 0.092 | 0.092 | 130 | 0.2 |
| matplotlib | atelier · +zoekt | 0.092 | 0.092 | 0.092 | 0.092 | 130 | 0.2 |
| matplotlib | atelier · +semantic | 0.234 | 0.185 | 0.238 | 0.285 | 130 | 1.0 |
| matplotlib | cg | 0.024 | 0.015 | 0.015 | 0.015 | 130 | 0.0 |
| matplotlib | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| matplotlib | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.3 |
| matplotlib | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| matplotlib | code-index-mcp | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.6 |
| matplotlib | jcodemunch | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 1.7 |
| matplotlib | cmm | 0.258 | 0.192 | 0.262 | 0.323 | 130 | 0.1 |
| matplotlib | serena | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 4.7 |
| seaborn | atelier · lexical | 0.123 | 0.123 | 0.123 | 0.123 | 130 | 0.2 |
| seaborn | atelier · +zoekt | 0.223 | 0.192 | 0.231 | 0.254 | 130 | 0.3 |
| seaborn | atelier · +semantic | 0.223 | 0.215 | 0.231 | 0.231 | 130 | 0.6 |
| seaborn | cg | 0.110 | 0.085 | 0.123 | 0.131 | 130 | 0.0 |
| seaborn | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| seaborn | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.2 |
| seaborn | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| seaborn | code-index-mcp | 0.005 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| seaborn | jcodemunch | 0.048 | 0.038 | 0.038 | 0.046 | 130 | 0.1 |
| seaborn | cmm | 0.266 | 0.169 | 0.262 | 0.315 | 130 | 0.1 |
| seaborn | serena | 0.008 | 0.008 | 0.008 | 0.008 | 130 | 2.8 |
| flask | atelier · lexical | 0.088 | 0.085 | 0.092 | 0.092 | 130 | 0.2 |
| flask | atelier · +zoekt | 0.253 | 0.177 | 0.262 | 0.323 | 130 | 0.2 |
| flask | atelier · +semantic | 0.292 | 0.285 | 0.300 | 0.300 | 130 | 0.4 |
| flask | cg | 0.109 | 0.100 | 0.108 | 0.115 | 130 | 0.0 |
| flask | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| flask | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.2 |
| flask | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| flask | code-index-mcp | 0.001 | 0.000 | 0.000 | 0.000 | 130 | 0.2 |
| flask | jcodemunch | 0.022 | 0.015 | 0.015 | 0.015 | 130 | 0.1 |
| flask | cmm | 0.306 | 0.208 | 0.323 | 0.392 | 130 | 0.1 |
| flask | serena | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.5 |
| requests | atelier · lexical | 0.238 | 0.238 | 0.238 | 0.238 | 130 | 0.2 |
| requests | atelier · +zoekt | 0.335 | 0.254 | 0.323 | 0.369 | 130 | 0.2 |
| requests | atelier · +semantic | 0.450 | 0.446 | 0.454 | 0.454 | 130 | 0.5 |
| requests | cg | 0.116 | 0.100 | 0.115 | 0.115 | 130 | 0.0 |
| requests | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| requests | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.2 |
| requests | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| requests | code-index-mcp | 0.026 | 0.000 | 0.000 | 0.015 | 130 | 0.1 |
| requests | jcodemunch | 0.064 | 0.038 | 0.069 | 0.085 | 130 | 0.1 |
| requests | cmm | 0.475 | 0.346 | 0.500 | 0.592 | 130 | 0.1 |
| requests | serena | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.4 |
| xarray | atelier · lexical | 0.123 | 0.123 | 0.123 | 0.123 | 130 | 0.3 |
| xarray | atelier · +zoekt | 0.211 | 0.169 | 0.223 | 0.246 | 130 | 0.3 |
| xarray | atelier · +semantic | 0.496 | 0.408 | 0.515 | 0.608 | 130 | 0.7 |
| xarray | cg | 0.085 | 0.023 | 0.069 | 0.162 | 130 | 0.0 |
| xarray | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| xarray | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.4 |
| xarray | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| xarray | code-index-mcp | 0.005 | 0.000 | 0.008 | 0.008 | 130 | 0.3 |
| xarray | jcodemunch | 0.011 | 0.000 | 0.008 | 0.008 | 130 | 0.2 |
| xarray | cmm | 0.258 | 0.162 | 0.254 | 0.300 | 130 | 0.1 |
| xarray | serena | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.8 |
| pylint | atelier · lexical | 0.048 | 0.046 | 0.046 | 0.046 | 130 | 0.2 |
| pylint | atelier · +zoekt | 0.108 | 0.100 | 0.108 | 0.108 | 130 | 0.4 |
| pylint | atelier · +semantic | 0.191 | 0.177 | 0.200 | 0.208 | 130 | 0.8 |
| pylint | cg | 0.020 | 0.008 | 0.008 | 0.015 | 130 | 0.0 |
| pylint | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| pylint | ast-grep | 0.001 | 0.000 | 0.000 | 0.000 | 130 | 0.2 |
| pylint | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| pylint | code-index-mcp | 0.001 | 0.000 | 0.000 | 0.000 | 130 | 0.7 |
| pylint | jcodemunch | 0.001 | 0.000 | 0.000 | 0.000 | 130 | 0.5 |
| pylint | cmm | 0.306 | 0.231 | 0.315 | 0.361 | 130 | 0.1 |
| pylint | serena | 0.002 | 0.000 | 0.000 | 0.000 | 130 | 2.2 |
| pytest | atelier · lexical | 0.131 | 0.131 | 0.131 | 0.131 | 130 | 0.1 |
| pytest | atelier · +zoekt | 0.167 | 0.162 | 0.169 | 0.169 | 130 | 0.3 |
| pytest | atelier · +semantic | 0.546 | 0.531 | 0.561 | 0.561 | 130 | 0.6 |
| pytest | cg | 0.100 | 0.046 | 0.085 | 0.147 | 129 | 0.0 |
| pytest | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 129 | 0.0 |
| pytest | ast-grep | 0.003 | 0.000 | 0.000 | 0.008 | 129 | 0.2 |
| pytest | rg | 0.000 | 0.000 | 0.000 | 0.000 | 129 | 0.1 |
| pytest | code-index-mcp | 0.001 | 0.000 | 0.000 | 0.000 | 129 | 0.2 |
| pytest | jcodemunch | 0.011 | 0.000 | 0.015 | 0.023 | 129 | 0.2 |
| pytest | cmm | 0.148 | 0.085 | 0.147 | 0.171 | 129 | 0.1 |
| pytest | serena | 0.018 | 0.008 | 0.023 | 0.031 | 129 | 0.6 |
| scikit-learn | atelier · lexical | 0.038 | 0.038 | 0.038 | 0.038 | 130 | 0.2 |
| scikit-learn | atelier · +zoekt | 0.148 | 0.131 | 0.154 | 0.162 | 130 | 0.2 |
| scikit-learn | atelier · +semantic | 0.630 | 0.608 | 0.646 | 0.646 | 130 | 0.7 |
| scikit-learn | cg | 0.034 | 0.023 | 0.031 | 0.038 | 130 | 0.0 |
| scikit-learn | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| scikit-learn | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.4 |
| scikit-learn | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| scikit-learn | code-index-mcp | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.6 |
| scikit-learn | jcodemunch | 0.014 | 0.000 | 0.008 | 0.023 | 130 | 1.0 |
| scikit-learn | cmm | 0.197 | 0.115 | 0.208 | 0.262 | 130 | 0.1 |
| scikit-learn | serena | 0.010 | 0.000 | 0.015 | 0.023 | 130 | 1.3 |
| sphinx | atelier · lexical | 0.108 | 0.108 | 0.108 | 0.108 | 130 | 0.2 |
| sphinx | atelier · +zoekt | 0.123 | 0.115 | 0.123 | 0.131 | 130 | 0.5 |
| sphinx | atelier · +semantic | 0.200 | 0.192 | 0.208 | 0.208 | 130 | 0.4 |
| sphinx | cg | 0.020 | 0.008 | 0.015 | 0.031 | 129 | 0.0 |
| sphinx | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 129 | 0.0 |
| sphinx | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 129 | 0.3 |
| sphinx | rg | 0.000 | 0.000 | 0.000 | 0.000 | 129 | 0.1 |
| sphinx | code-index-mcp | 0.002 | 0.000 | 0.000 | 0.000 | 129 | 0.4 |
| sphinx | jcodemunch | 0.031 | 0.023 | 0.031 | 0.031 | 129 | 0.5 |
| sphinx | cmm | 0.224 | 0.171 | 0.240 | 0.256 | 129 | 0.2 |
| sphinx | serena | 0.013 | 0.008 | 0.015 | 0.015 | 129 | 1.5 |
| sympy | atelier · lexical | 0.613 | 0.485 | 0.638 | 0.685 | 130 | 0.2 |
| sympy | atelier · +zoekt | 0.613 | 0.485 | 0.638 | 0.685 | 130 | 0.3 |
| sympy | atelier · +semantic | 0.665 | 0.554 | 0.692 | 0.739 | 130 | 0.5 |
| sympy | cg | 0.030 | 0.015 | 0.031 | 0.038 | 130 | 0.1 |
| sympy | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| sympy | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.8 |
| sympy | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| sympy | code-index-mcp | 0.001 | 0.000 | 0.000 | 0.000 | 130 | 1.0 |
| sympy | jcodemunch | 0.012 | 0.000 | 0.015 | 0.023 | 130 | 1.0 |
| sympy | cmm | 0.256 | 0.200 | 0.238 | 0.292 | 130 | 0.1 |
| sympy | serena | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 15.6 |
| linux | atelier · lexical | 0.069 | 0.061 | 0.069 | 0.069 | 130 | 2.8 |
| linux | atelier · +zoekt | 0.069 | 0.061 | 0.069 | 0.069 | 130 | 2.8 |
| linux | atelier · +semantic | 0.069 | 0.061 | 0.069 | 0.069 | 130 | 2.7 |
| linux | cg | 0.003 | 0.000 | 0.000 | 0.000 | 130 | 0.4 |
| linux | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.0 |
| linux | ast-grep | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 7.5 |
| linux | rg | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 0.1 |
| linux | code-index-mcp | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 1.6 |
| linux | jcodemunch | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 4.7 |
| linux | cmm | 0.203 | 0.123 | 0.200 | 0.292 | 130 | 1.0 |
| linux | serena | 0.000 | 0.000 | 0.000 | 0.000 | 130 | 480.0 |

</details>

## swebench

| Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (mean, s) |
|---|---|---|---|---|---|---|
| atelier · lexical | 0.490 | 0.428 | 0.503 | 0.535 | 3946 | 0.5 |
| atelier · +zoekt | 0.519 | 0.445 | 0.533 | 0.571 | 3946 | 0.5 |
| atelier · +semantic | 0.505 | 0.445 | 0.516 | 0.551 | 3946 | 2.8 |
| cg | 0.337 | 0.288 | 0.343 | 0.370 | 3759 | 0.1 |
| ctags | 0.225 | 0.214 | 0.229 | 0.234 | 3759 | 0.0 |
| ast-grep | 0.209 | 0.154 | 0.213 | 0.242 | 3759 | 1.0 |
| rg | 0.220 | 0.141 | 0.209 | 0.248 | 3759 | 0.1 |
| code-index-mcp | 0.208 | 0.148 | 0.205 | 0.233 | 3759 | 0.8 |
| jcodemunch | 0.182 | 0.108 | 0.169 | 0.227 | 3394 | 1.0 |
| cmm | 0.382 | 0.308 | 0.386 | 0.441 | 3759 | 0.2 |
| serena | 0.320 | 0.251 | 0.315 | 0.348 | 3759 | 67.6 |

<details>
<summary>Per-repo breakdown — 15 repos</summary>

| Repo | Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (s) |
|---|---|---|---|---|---|---|---|
| astropy | atelier · lexical | 0.382 | 0.330 | 0.420 | 0.440 | 100 | 0.2 |
| astropy | atelier · +zoekt | 0.440 | 0.340 | 0.470 | 0.500 | 100 | 0.5 |
| astropy | atelier · +semantic | 0.435 | 0.340 | 0.460 | 0.500 | 100 | 0.8 |
| astropy | cg | 0.367 | 0.290 | 0.360 | 0.450 | 100 | 0.0 |
| astropy | ctags | 0.189 | 0.180 | 0.180 | 0.180 | 100 | 0.0 |
| astropy | ast-grep | 0.203 | 0.130 | 0.200 | 0.240 | 100 | 1.4 |
| astropy | rg | 0.219 | 0.160 | 0.210 | 0.240 | 100 | 0.1 |
| astropy | code-index-mcp | 0.103 | 0.000 | 0.110 | 0.120 | 100 | 1.3 |
| astropy | jcodemunch | 0.156 | 0.070 | 0.140 | 0.180 | 100 | 1.3 |
| astropy | cmm | 0.304 | 0.220 | 0.320 | 0.380 | 100 | 0.2 |
| astropy | serena | 0.251 | 0.180 | 0.250 | 0.280 | 100 | 2.5 |
| atelier-dev | atelier · lexical | 0.538 | 0.465 | 0.551 | 0.588 | 2278 | 0.7 |
| atelier-dev | atelier · +zoekt | 0.539 | 0.465 | 0.552 | 0.590 | 2278 | 0.7 |
| atelier-dev | atelier · +semantic | 0.543 | 0.479 | 0.554 | 0.590 | 2278 | 14.4 |
| atelier-dev | cg | 0.308 | 0.270 | 0.315 | 0.333 | 2145 | 0.2 |
| atelier-dev | ctags | 0.227 | 0.222 | 0.229 | 0.232 | 2145 | 0.0 |
| atelier-dev | ast-grep | 0.189 | 0.136 | 0.196 | 0.223 | 2145 | 1.4 |
| atelier-dev | rg | 0.194 | 0.113 | 0.176 | 0.220 | 2145 | 1.0 |
| atelier-dev | code-index-mcp | 0.192 | 0.139 | 0.180 | 0.213 | 2145 | 2.1 |
| atelier-dev | jcodemunch | 0.162 | 0.097 | 0.151 | 0.202 | 2145 | 1.3 |
| atelier-dev | cmm | 0.346 | 0.276 | 0.348 | 0.400 | 2145 | 0.2 |
| atelier-dev | serena | 0.310 | 0.239 | 0.309 | 0.342 | 2145 | 250.6 |
| atelier | atelier · lexical | 0.485 | 0.440 | 0.490 | 0.490 | 100 | 0.7 |
| atelier | atelier · +zoekt | 0.486 | 0.440 | 0.490 | 0.490 | 100 | 0.9 |
| atelier | atelier · +semantic | 0.504 | 0.450 | 0.490 | 0.530 | 100 | 17.8 |
| atelier | cg | 0.446 | 0.390 | 0.450 | 0.480 | 100 | 0.0 |
| atelier | ctags | 0.238 | 0.230 | 0.240 | 0.240 | 100 | 0.0 |
| atelier | ast-grep | 0.234 | 0.190 | 0.230 | 0.270 | 100 | 0.7 |
| atelier | rg | 0.265 | 0.210 | 0.240 | 0.320 | 100 | 0.2 |
| atelier | code-index-mcp | 0.296 | 0.240 | 0.320 | 0.330 | 100 | 0.7 |
| atelier | jcodemunch | 0.281 | 0.160 | 0.260 | 0.340 | 100 | 1.3 |
| atelier | cmm | 0.510 | 0.450 | 0.500 | 0.550 | 100 | 0.2 |
| atelier | serena | 0.394 | 0.340 | 0.400 | 0.410 | 100 | 246.6 |
| django | atelier · lexical | 0.482 | 0.375 | 0.499 | 0.573 | 365 | 0.3 |
| django | atelier · +zoekt | 0.510 | 0.416 | 0.520 | 0.584 | 365 | 0.5 |
| django | atelier · +semantic | 0.496 | 0.386 | 0.520 | 0.595 | 365 | 0.8 |
| django | cg | 0.271 | 0.211 | 0.293 | 0.315 | 365 | 0.1 |
| django | ctags | 0.223 | 0.200 | 0.236 | 0.247 | 365 | 0.0 |
| django | ast-grep | 0.163 | 0.093 | 0.167 | 0.216 | 365 | 0.6 |
| django | rg | 0.188 | 0.090 | 0.186 | 0.238 | 365 | 0.1 |
| django | code-index-mcp | 0.209 | 0.148 | 0.219 | 0.233 | 365 | 1.3 |
| django | cmm | 0.335 | 0.260 | 0.351 | 0.395 | 365 | 0.4 |
| django | serena | 0.351 | 0.288 | 0.323 | 0.367 | 365 | 4.0 |
| matplotlib | atelier · lexical | 0.387 | 0.370 | 0.400 | 0.400 | 100 | 0.2 |
| matplotlib | atelier · +zoekt | 0.397 | 0.380 | 0.410 | 0.410 | 100 | 0.2 |
| matplotlib | atelier · +semantic | 0.533 | 0.480 | 0.510 | 0.580 | 100 | 1.0 |
| matplotlib | cg | 0.339 | 0.274 | 0.337 | 0.390 | 95 | 0.0 |
| matplotlib | ctags | 0.222 | 0.200 | 0.221 | 0.232 | 95 | 0.0 |
| matplotlib | ast-grep | 0.003 | 0.000 | 0.000 | 0.000 | 95 | 0.3 |
| matplotlib | rg | 0.329 | 0.263 | 0.337 | 0.379 | 95 | 0.1 |
| matplotlib | code-index-mcp | 0.266 | 0.232 | 0.242 | 0.295 | 95 | 0.6 |
| matplotlib | jcodemunch | 0.088 | 0.053 | 0.116 | 0.126 | 95 | 1.7 |
| matplotlib | cmm | 0.400 | 0.305 | 0.368 | 0.495 | 95 | 0.1 |
| matplotlib | serena | 0.002 | 0.000 | 0.000 | 0.000 | 95 | 4.7 |
| seaborn | atelier · lexical | 0.315 | 0.300 | 0.330 | 0.330 | 100 | 0.2 |
| seaborn | atelier · +zoekt | 0.553 | 0.430 | 0.580 | 0.650 | 100 | 0.3 |
| seaborn | atelier · +semantic | 0.315 | 0.300 | 0.330 | 0.330 | 100 | 0.6 |
| seaborn | cg | 0.411 | 0.343 | 0.384 | 0.465 | 99 | 0.0 |
| seaborn | ctags | 0.217 | 0.202 | 0.232 | 0.232 | 99 | 0.0 |
| seaborn | ast-grep | 0.341 | 0.273 | 0.343 | 0.384 | 99 | 0.2 |
| seaborn | rg | 0.277 | 0.151 | 0.293 | 0.313 | 99 | 0.1 |
| seaborn | code-index-mcp | 0.308 | 0.242 | 0.313 | 0.343 | 99 | 0.1 |
| seaborn | jcodemunch | 0.254 | 0.141 | 0.242 | 0.333 | 99 | 0.1 |
| seaborn | cmm | 0.391 | 0.313 | 0.353 | 0.424 | 99 | 0.1 |
| seaborn | serena | 0.300 | 0.212 | 0.242 | 0.313 | 99 | 2.8 |
| flask | atelier · lexical | 0.487 | 0.470 | 0.490 | 0.510 | 100 | 0.2 |
| flask | atelier · +zoekt | 0.576 | 0.500 | 0.600 | 0.610 | 100 | 0.2 |
| flask | atelier · +semantic | 0.495 | 0.480 | 0.490 | 0.520 | 100 | 0.4 |
| flask | cg | 0.504 | 0.414 | 0.495 | 0.566 | 99 | 0.0 |
| flask | ctags | 0.278 | 0.242 | 0.283 | 0.293 | 99 | 0.0 |
| flask | ast-grep | 0.310 | 0.242 | 0.303 | 0.333 | 99 | 0.2 |
| flask | rg | 0.349 | 0.263 | 0.353 | 0.384 | 99 | 0.1 |
| flask | code-index-mcp | 0.300 | 0.242 | 0.293 | 0.343 | 99 | 0.2 |
| flask | jcodemunch | 0.352 | 0.242 | 0.303 | 0.414 | 99 | 0.1 |
| flask | cmm | 0.596 | 0.535 | 0.606 | 0.657 | 99 | 0.1 |
| flask | serena | 0.451 | 0.364 | 0.404 | 0.475 | 99 | 0.5 |
| requests | atelier · lexical | 0.502 | 0.450 | 0.550 | 0.550 | 100 | 0.2 |
| requests | atelier · +zoekt | 0.631 | 0.520 | 0.670 | 0.750 | 100 | 0.2 |
| requests | atelier · +semantic | 0.497 | 0.450 | 0.540 | 0.540 | 100 | 0.5 |
| requests | cg | 0.502 | 0.444 | 0.505 | 0.545 | 99 | 0.0 |
| requests | ctags | 0.270 | 0.253 | 0.283 | 0.283 | 99 | 0.0 |
| requests | ast-grep | 0.380 | 0.353 | 0.374 | 0.394 | 99 | 0.2 |
| requests | rg | 0.336 | 0.263 | 0.343 | 0.364 | 99 | 0.0 |
| requests | code-index-mcp | 0.350 | 0.293 | 0.364 | 0.374 | 99 | 0.1 |
| requests | jcodemunch | 0.233 | 0.111 | 0.212 | 0.343 | 99 | 0.1 |
| requests | cmm | 0.504 | 0.444 | 0.535 | 0.556 | 99 | 0.1 |
| requests | serena | 0.440 | 0.323 | 0.465 | 0.535 | 99 | 0.4 |
| xarray | atelier · lexical | 0.396 | 0.370 | 0.390 | 0.410 | 100 | 0.3 |
| xarray | atelier · +zoekt | 0.491 | 0.410 | 0.500 | 0.530 | 100 | 0.3 |
| xarray | atelier · +semantic | 0.499 | 0.420 | 0.510 | 0.540 | 100 | 0.7 |
| xarray | cg | 0.411 | 0.343 | 0.414 | 0.434 | 99 | 0.0 |
| xarray | ctags | 0.231 | 0.202 | 0.232 | 0.263 | 99 | 0.0 |
| xarray | ast-grep | 0.244 | 0.202 | 0.212 | 0.253 | 99 | 0.4 |
| xarray | rg | 0.308 | 0.212 | 0.323 | 0.364 | 99 | 0.0 |
| xarray | code-index-mcp | 0.112 | 0.010 | 0.111 | 0.131 | 99 | 0.3 |
| xarray | jcodemunch | 0.251 | 0.131 | 0.232 | 0.313 | 99 | 0.2 |
| xarray | cmm | 0.497 | 0.394 | 0.505 | 0.576 | 99 | 0.1 |
| xarray | serena | 0.294 | 0.212 | 0.283 | 0.293 | 99 | 0.8 |
| pylint | atelier · lexical | 0.558 | 0.544 | 0.573 | 0.573 | 103 | 0.2 |
| pylint | atelier · +zoekt | 0.698 | 0.641 | 0.699 | 0.728 | 103 | 0.4 |
| pylint | atelier · +semantic | 0.558 | 0.544 | 0.573 | 0.573 | 103 | 0.8 |
| pylint | cg | 0.597 | 0.544 | 0.641 | 0.641 | 103 | 0.0 |
| pylint | ctags | 0.314 | 0.311 | 0.311 | 0.320 | 103 | 0.0 |
| pylint | ast-grep | 0.520 | 0.427 | 0.544 | 0.583 | 103 | 0.2 |
| pylint | rg | 0.335 | 0.233 | 0.301 | 0.320 | 103 | 0.1 |
| pylint | code-index-mcp | 0.483 | 0.408 | 0.515 | 0.524 | 103 | 0.7 |
| pylint | jcodemunch | 0.177 | 0.126 | 0.146 | 0.223 | 103 | 0.5 |
| pylint | cmm | 0.515 | 0.447 | 0.524 | 0.583 | 103 | 0.1 |
| pylint | serena | 0.504 | 0.427 | 0.505 | 0.534 | 103 | 2.2 |
| pytest | atelier · lexical | 0.386 | 0.350 | 0.410 | 0.420 | 100 | 0.1 |
| pytest | atelier · +zoekt | 0.545 | 0.430 | 0.610 | 0.640 | 100 | 0.3 |
| pytest | atelier · +semantic | 0.403 | 0.360 | 0.440 | 0.440 | 100 | 0.6 |
| pytest | cg | 0.279 | 0.212 | 0.293 | 0.333 | 99 | 0.0 |
| pytest | ctags | 0.165 | 0.131 | 0.182 | 0.182 | 99 | 0.0 |
| pytest | ast-grep | 0.178 | 0.101 | 0.202 | 0.202 | 99 | 0.2 |
| pytest | rg | 0.185 | 0.111 | 0.172 | 0.192 | 99 | 0.1 |
| pytest | code-index-mcp | 0.125 | 0.020 | 0.131 | 0.172 | 99 | 0.2 |
| pytest | jcodemunch | 0.227 | 0.162 | 0.232 | 0.242 | 99 | 0.2 |
| pytest | cmm | 0.368 | 0.263 | 0.364 | 0.495 | 99 | 0.1 |
| pytest | serena | 0.349 | 0.253 | 0.343 | 0.404 | 99 | 0.6 |
| scikit-learn | atelier · lexical | 0.443 | 0.440 | 0.440 | 0.440 | 100 | 0.2 |
| scikit-learn | atelier · +zoekt | 0.547 | 0.490 | 0.560 | 0.600 | 100 | 0.2 |
| scikit-learn | atelier · +semantic | 0.507 | 0.490 | 0.520 | 0.520 | 100 | 0.7 |
| scikit-learn | cg | 0.432 | 0.402 | 0.412 | 0.443 | 97 | 0.0 |
| scikit-learn | ctags | 0.245 | 0.206 | 0.278 | 0.278 | 97 | 0.0 |
| scikit-learn | ast-grep | 0.292 | 0.247 | 0.289 | 0.309 | 97 | 0.4 |
| scikit-learn | rg | 0.291 | 0.247 | 0.299 | 0.299 | 97 | 0.1 |
| scikit-learn | code-index-mcp | 0.112 | 0.000 | 0.144 | 0.175 | 97 | 0.6 |
| scikit-learn | jcodemunch | 0.247 | 0.155 | 0.216 | 0.299 | 97 | 1.0 |
| scikit-learn | cmm | 0.563 | 0.443 | 0.629 | 0.691 | 97 | 0.1 |
| scikit-learn | serena | 0.365 | 0.309 | 0.392 | 0.392 | 97 | 1.3 |
| sphinx | atelier · lexical | 0.374 | 0.350 | 0.370 | 0.400 | 100 | 0.2 |
| sphinx | atelier · +zoekt | 0.364 | 0.330 | 0.370 | 0.400 | 100 | 0.5 |
| sphinx | atelier · +semantic | 0.374 | 0.350 | 0.370 | 0.400 | 100 | 0.4 |
| sphinx | cg | 0.384 | 0.302 | 0.417 | 0.427 | 96 | 0.0 |
| sphinx | ctags | 0.152 | 0.135 | 0.146 | 0.146 | 96 | 0.0 |
| sphinx | ast-grep | 0.195 | 0.146 | 0.188 | 0.208 | 96 | 0.3 |
| sphinx | rg | 0.188 | 0.146 | 0.188 | 0.219 | 96 | 0.1 |
| sphinx | code-index-mcp | 0.228 | 0.167 | 0.240 | 0.260 | 96 | 0.4 |
| sphinx | jcodemunch | 0.233 | 0.125 | 0.219 | 0.281 | 96 | 0.5 |
| sphinx | cmm | 0.540 | 0.469 | 0.510 | 0.615 | 96 | 0.2 |
| sphinx | serena | 0.323 | 0.260 | 0.333 | 0.333 | 96 | 1.5 |
| sympy | atelier · lexical | 0.542 | 0.460 | 0.550 | 0.580 | 100 | 0.2 |
| sympy | atelier · +zoekt | 0.542 | 0.460 | 0.550 | 0.580 | 100 | 0.3 |
| sympy | atelier · +semantic | 0.576 | 0.520 | 0.570 | 0.580 | 100 | 0.5 |
| sympy | cg | 0.437 | 0.360 | 0.420 | 0.480 | 100 | 0.1 |
| sympy | ctags | 0.283 | 0.270 | 0.280 | 0.290 | 100 | 0.0 |
| sympy | ast-grep | 0.293 | 0.220 | 0.290 | 0.340 | 100 | 0.8 |
| sympy | rg | 0.354 | 0.300 | 0.350 | 0.370 | 100 | 0.1 |
| sympy | code-index-mcp | 0.280 | 0.210 | 0.270 | 0.300 | 100 | 1.0 |
| sympy | jcodemunch | 0.253 | 0.120 | 0.190 | 0.300 | 100 | 1.0 |
| sympy | cmm | 0.537 | 0.470 | 0.560 | 0.580 | 100 | 0.1 |
| sympy | serena | 0.442 | 0.380 | 0.450 | 0.470 | 100 | 15.6 |
| linux | atelier · lexical | 0.042 | 0.030 | 0.040 | 0.060 | 100 | 2.8 |
| linux | atelier · +zoekt | 0.042 | 0.030 | 0.040 | 0.060 | 100 | 2.8 |
| linux | atelier · +semantic | 0.042 | 0.030 | 0.040 | 0.060 | 100 | 2.7 |
| linux | cg | 0.018 | 0.000 | 0.016 | 0.032 | 63 | 0.4 |
| linux | ctags | 0.000 | 0.000 | 0.000 | 0.000 | 63 | 0.0 |
| linux | ast-grep | 0.032 | 0.032 | 0.032 | 0.032 | 63 | 7.5 |
| linux | rg | 0.032 | 0.032 | 0.032 | 0.032 | 63 | 0.1 |
| linux | code-index-mcp | 0.016 | 0.000 | 0.000 | 0.016 | 63 | 1.6 |
| linux | jcodemunch | 0.009 | 0.000 | 0.000 | 0.016 | 63 | 4.7 |
| linux | cmm | 0.074 | 0.032 | 0.064 | 0.079 | 63 | 1.0 |
| linux | serena | 0.022 | 0.016 | 0.016 | 0.032 | 63 | 480.0 |

</details>

## atelier_sessions

| Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (mean, s) |
|---|---|---|---|---|---|---|
| atelier · lexical | 0.596 | 0.510 | 0.618 | 0.660 | 500 | 0.5 |
| atelier · +zoekt | 0.595 | 0.508 | 0.618 | 0.660 | 500 | 0.5 |
| atelier · +semantic | 0.602 | 0.528 | 0.612 | 0.650 | 500 | 2.8 |
| cg | 0.297 | 0.257 | 0.297 | 0.318 | 491 | 0.1 |
| ctags | 0.204 | 0.198 | 0.206 | 0.208 | 491 | 0.0 |
| ast-grep | 0.183 | 0.141 | 0.187 | 0.210 | 491 | 1.0 |
| rg | 0.240 | 0.159 | 0.232 | 0.281 | 491 | 0.1 |
| code-index-mcp | 0.193 | 0.145 | 0.187 | 0.204 | 491 | 0.8 |
| jcodemunch | 0.184 | 0.098 | 0.157 | 0.244 | 491 | 1.0 |
| cmm | 0.424 | 0.330 | 0.417 | 0.483 | 491 | 0.2 |
| serena | 0.335 | 0.261 | 0.334 | 0.377 | 491 | 67.6 |

<details>
<summary>Per-repo breakdown — 1 repo</summary>

| Repo | Channel | MRR | hit@1 | hit@2 | hit@3 | n | Index time (s) |
|---|---|---|---|---|---|---|---|
| atelier | atelier · lexical | 0.596 | 0.510 | 0.618 | 0.660 | 500 | 0.7 |
| atelier | atelier · +zoekt | 0.595 | 0.508 | 0.618 | 0.660 | 500 | 0.9 |
| atelier | atelier · +semantic | 0.602 | 0.528 | 0.612 | 0.650 | 500 | 17.8 |
| atelier | cg | 0.297 | 0.257 | 0.297 | 0.318 | 491 | 0.0 |
| atelier | ctags | 0.204 | 0.198 | 0.206 | 0.208 | 491 | 0.0 |
| atelier | ast-grep | 0.183 | 0.141 | 0.187 | 0.210 | 491 | 0.7 |
| atelier | rg | 0.240 | 0.159 | 0.232 | 0.281 | 491 | 0.2 |
| atelier | code-index-mcp | 0.193 | 0.145 | 0.187 | 0.204 | 491 | 0.7 |
| atelier | jcodemunch | 0.184 | 0.098 | 0.157 | 0.244 | 491 | 1.3 |
| atelier | cmm | 0.424 | 0.330 | 0.417 | 0.483 | 491 | 0.2 |
| atelier | serena | 0.335 | 0.261 | 0.334 | 0.377 | 491 | 246.6 |

</details>
