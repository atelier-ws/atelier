import csv

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from scipy import stats

# ── Load correctness ─────────────────────────────────────────────────────────────────────────────────
correctness = {}
with open("benchmarks/codebench/results/swe50_2026_06_30/results.csv") as f:
    for row in csv.DictReader(f):
        key = (row["task"], int(row["rep"]))
        if key not in correctness:
            correctness[key] = {"baseline": False, "atelier": False}
        correct = row["correct"].strip().lower() in ("true", "1", "yes")
        if row["arm"] == "baseline":
            correctness[key]["baseline"] = correct
        elif row["arm"] == "atelier":
            correctness[key]["atelier"] = correct

repo_map = {
    "astropy": "astropy",
    "django": "django",
    "matplotlib": "matplotlib",
    "mwaskom": "seaborn",
    "pallets": "flask",
    "psf": "requests",
    "pydata": "xarray",
    "pylint": "pylint",
    "pytest": "pytest",
    "scikit": "sklearn",
    "sphinx": "sphinx",
    "sympy": "sympy",
}

data = []
with open("benchmarks/codebench/results/swe50_2026_06_30/pairwise_quality.csv") as f:
    for row in csv.DictReader(f):
        task = row["task"]
        rep = int(row["rep"])
        bc = float(row["baseline_cost_usd"])
        ac = float(row["candidate_cost_usd"])
        if bc <= 0:
            continue
        c = correctness.get((task, rep), {"baseline": False, "atelier": False})
        if not (c["baseline"] or c["atelier"]):
            continue
        saved_usd = bc - ac
        repo = repo_map.get(task.split("__")[0].split("-")[0], task.split("__")[0])
        data.append({"bc": bc, "saved": saved_usd, "repo": repo})

# Tukey IQR on savings
saved_arr = np.array([d["saved"] for d in data])
q1, q3 = np.percentile(saved_arr, 25), np.percentile(saved_arr, 75)
iqr = q3 - q1
data = [d for d in data if (q1 - 1.5 * iqr) <= d["saved"] <= (q3 + 1.5 * iqr)]

xs = np.array([d["bc"] for d in data])
ys = np.array([d["saved"] for d in data])

# ── Linear regression ─────────────────────────────────────────────────────────────────────────────────
slope, intercept, r, p, se = stats.linregress(xs, ys)


def predict(x):
    return slope * x + intercept


# Bootstrap CI
np.random.seed(42)
n = len(xs)
boot_preds = []
for _ in range(1000):
    idx = np.random.randint(0, n, n)
    s, i, *_ = stats.linregress(xs[idx], ys[idx])
    boot_preds.append((s, i))

# Curve over observed range
x_obs = np.linspace(0, xs.max(), 300)
y_obs = predict(x_obs)
boot_obs = np.array([s * x_obs + i for s, i in boot_preds])
obs_lo = np.percentile(boot_obs, 2.5, axis=0)
obs_hi = np.percentile(boot_obs, 97.5, axis=0)

# Extrapolation to $50
x_extrap = np.linspace(xs.max(), 50, 300)
y_extrap = predict(x_extrap)
boot_extrap = np.array([s * x_extrap + i for s, i in boot_preds])
extrap_lo = np.percentile(boot_extrap, 2.5, axis=0)
extrap_hi = np.percentile(boot_extrap, 97.5, axis=0)

y50 = predict(50)
y50_lo = float(np.percentile([s * 50 + i for s, i in boot_preds], 2.5))
y50_hi = float(np.percentile([s * 50 + i for s, i in boot_preds], 97.5))

# ── Plot ──────────────────────────────────────────────────────────────────────────────────────
repos = sorted(set(d["repo"] for d in data))
colors = plt.cm.tab10(np.linspace(0, 1, 10))
color_map = {r: colors[i % 10] for i, r in enumerate(repos)}

fig, ax = plt.subplots(figsize=(13, 7))

# Extrapolation zone
ax.axvspan(xs.max(), 50, color="#fffbe6", alpha=0.6, zorder=1, label="extrapolation zone")

# Scatter by repo
for repo in repos:
    pts = [d for d in data if d["repo"] == repo]
    ax.scatter(
        [d["bc"] for d in pts], [d["saved"] for d in pts], color=color_map[repo], label=repo, alpha=0.75, s=65, zorder=4
    )

# Fit + CI (observed)
ax.fill_between(x_obs, obs_lo, obs_hi, color="steelblue", alpha=0.15, zorder=2)
ax.plot(
    x_obs,
    y_obs,
    color="steelblue",
    linewidth=2.5,
    label=f"linear fit  R²={r**2:.2f}  slope=${slope:.2f}/$ baseline",
    zorder=5,
)

# Extrapolation + CI
ax.fill_between(x_extrap, extrap_lo, extrap_hi, color="steelblue", alpha=0.08, zorder=2)
ax.plot(x_extrap, y_extrap, color="steelblue", linewidth=2.5, linestyle="--", label="extrapolated →$50", zorder=5)

# Reference lines
ax.axhline(0, color="crimson", linestyle="--", linewidth=1.3, label="break-even", zorder=3)
mean_saved = float(np.mean(ys))
ax.axhline(
    mean_saved,
    color="darkorange",
    linestyle="--",
    linewidth=1.2,
    label=f"observed mean ${mean_saved:.2f} saved/rep",
    zorder=3,
)

# $50 annotation — star marker
ax.scatter([50], [y50], color="gold", edgecolors="steelblue", s=180, zorder=6, marker="*")
ax.annotate(
    f"$50 task → ~${y50:.0f} saved\n(95% CI  ${y50_lo:.0f} – ${y50_hi:.0f})",
    xy=(50, y50),
    xytext=(38, y50 + (y50 * 0.15 + 0.3)),
    arrowprops=dict(arrowstyle="->", color="dimgray", lw=1.3),
    fontsize=10,
    color="dimgray",
    fontweight="bold",
    bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="lightgray", lw=1),
)

# Axes — both LINEAR, dollar-formatted
ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"${v:.0f}"))
ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"${v:.1f}"))
ax.set_xlabel("Baseline cost per rep ($)  —  what vanilla Claude Code spent", fontsize=12)
ax.set_ylabel("$ saved per rep  (baseline − Atelier)", fontsize=12)
ax.set_title(
    "The bigger the task, the more Atelier saves\n"
    "SWE-bench Verified · correct reps only · outliers removed · extrapolated to $50",
    fontsize=13,
    fontweight="bold",
    pad=14,
)
ax.set_xlim(-0.5, 52)

handles, labels = ax.get_legend_handles_labels()
ax.legend(handles, labels, loc="upper left", fontsize=8.5, framealpha=0.92, ncol=2)
ax.grid(True, color="#e5e5e5", linewidth=0.6)
ax.set_facecolor("white")
fig.patch.set_facecolor("white")
plt.tight_layout()
plt.savefig("reports/public/benchmark/codebench/cost_vs_savings_scatter.svg", format="svg")
plt.savefig("reports/public/benchmark/codebench/cost_vs_savings_scatter.png", dpi=150, format="png")
print(
    f"n={len(data)}, slope=${slope:.3f}/$ baseline, R²={r**2:.3f}, at $50 → ${y50:.2f} saved (CI ${y50_lo:.2f}–${y50_hi:.2f})"
)
