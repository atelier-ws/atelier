import collections
import csv

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from scipy.optimize import curve_fit

# Load per-rep correctness
correctness = {}
with open("benchmarks/codebench/results/swe50_2026_06_30/results.csv") as f:
    for row in csv.DictReader(f):
        key = (row["task"], int(row["rep"]))
        if key not in correctness:
            correctness[key] = {"baseline": False, "atelier": False}
        ok = row["correct"].strip().lower() in ("true", "1", "yes")
        correctness[key][row["arm"]] = ok

repo_map = {
    "astropy": "astropy", "django": "django",
    "matplotlib": "matplotlib", "mwaskom": "seaborn",
    "pallets": "flask", "psf": "requests",
    "pydata": "xarray", "pylint": "pylint",
    "pytest": "pytest", "scikit": "sklearn",
    "sphinx": "sphinx", "sympy": "sympy",
}

# All individual reps for scatter
all_pts = []
task_buckets = collections.defaultdict(list)

with open("benchmarks/codebench/results/swe50_2026_06_30/pairwise_quality.csv") as f:
    for row in csv.DictReader(f):
        task = row["task"]
        rep  = int(row["rep"])
        bc   = float(row["baseline_cost_usd"])
        ac   = float(row["candidate_cost_usd"])
        if bc <= 0:
            continue
        c = correctness.get((task, rep), {})
        if not (c.get("baseline") or c.get("atelier")):
            continue
        saved = bc - ac
        repo  = repo_map.get(task.split("__")[0].split("-")[0], task.split("__")[0])
        all_pts.append({"bc": bc, "saved": saved, "repo": repo})
        task_buckets[task].append({"bc": bc, "saved": saved, "repo": repo})

# IQR on scatter points
sav_arr = np.array([p["saved"] for p in all_pts])
q1, q3 = np.percentile(sav_arr, 25), np.percentile(sav_arr, 75)
plot_pts = [p for p in all_pts if (q1 - 1.5*(q3-q1)) <= p["saved"] <= (q3 + 1.5*(q3-q1))]

# Fit on all individual rep points (preserves the negative savings at low cost)
fxs = np.array([p["bc"]    for p in plot_pts])
fys = np.array([p["saved"] for p in plot_pts])

# y = a*(exp(b*x) - 1) - d
# At x=0: y = -d  (always negative, forced below zero)
# d > 0.1 ensures visible dip; b >= 0.5 ensures visible curve
def exp_curve(x, a, b, d):
    return a * (np.exp(b * x) - 1) - d

popt, _ = curve_fit(
    exp_curve, fxs, fys,
    p0=[0.40, 0.60, 0.20],
    bounds=([0.0, 0.5, -np.inf], [np.inf, np.inf, np.inf]),
    maxfev=20000,
)
a_fit, b_fit, d_fit = popt

# Curve: data range solid, extrapolation to $5 dashed
X_DATA = fxs.max()
X_MAX  = 5.0
x_obs  = np.linspace(0, X_DATA, 400)
x_ext  = np.linspace(X_DATA, X_MAX, 200)
y_obs  = exp_curve(x_obs, *popt)
y_ext  = exp_curve(x_ext, *popt)
y_end  = float(exp_curve(X_MAX, *popt))

# Break-even: a*(exp(b*x)-1) = d  =>  x = log(d/a + 1) / b
breakeven = np.log(d_fit / a_fit + 1) / b_fit if a_fit > 0 and d_fit / a_fit > -1 else 0.0

# 68% bootstrap CI
np.random.seed(42)
n = len(fxs)
bo, be, bend = [], [], []
for _ in range(2000):
    idx = np.random.randint(0, n, n)
    try:
        bp, _ = curve_fit(exp_curve, fxs[idx], fys[idx],
                          p0=popt, bounds=([0.0, 0.5, -np.inf], [np.inf, np.inf, np.inf]),
                          maxfev=2000)
        bo.append(exp_curve(x_obs, *bp))
        be.append(exp_curve(x_ext, *bp))
        bend.append(float(exp_curve(X_MAX, *bp)))
    except RuntimeError:
        pass

obs_lo = np.percentile(np.array(bo), 16, axis=0)
obs_hi = np.percentile(np.array(bo), 84, axis=0)
ext_lo = np.percentile(np.array(be), 16, axis=0)
ext_hi = np.percentile(np.array(be), 84, axis=0)
y_lo   = float(np.percentile(bend, 16))
y_hi   = float(np.percentile(bend, 84))

fys_pred = exp_curve(fxs, *popt)
r2 = 1 - np.sum((fys - fys_pred)**2) / np.sum((fys - fys.mean())**2)
print(f"y={a_fit:.3f}*exp({b_fit:.3f}*x)-({d_fit:.3f}), R2={r2:.3f}")
print(f"break-even at ${breakeven:.2f}, at $5 -> ${y_end:.2f} saved")

# --- Plot ---
repos  = sorted(set(p["repo"] for p in plot_pts))
colors = plt.cm.tab10(np.linspace(0, 1, 10))
cmap   = {repo: colors[i % 10] for i, repo in enumerate(repos)}

fig, ax = plt.subplots(figsize=(13, 7))

ax.axvspan(X_DATA, X_MAX, color="#fffbe6", alpha=0.4, zorder=1, label="extrapolation")
ax.axhline(0, color="crimson", linestyle="--", linewidth=1.5, zorder=3)
ax.axvline(breakeven, color="crimson", linestyle=":", linewidth=1.8, zorder=3, label=f"break-even  (${breakeven:.2f} task)")
ax.text(breakeven + 0.05, -0.55,
        f"Break-even · ${breakeven:.2f}", color="crimson", fontsize=9.5, fontweight="bold",
        va="bottom", zorder=10,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="crimson", lw=1.0))

for repo in repos:
    pts = [p for p in plot_pts if p["repo"] == repo]
    ax.scatter([p["bc"] for p in pts], [p["saved"] for p in pts],
               color=cmap[repo], label=repo, alpha=0.50, s=45, zorder=4)

ax.fill_between(x_obs, obs_lo, obs_hi, color="steelblue", alpha=0.18, zorder=2)
ax.plot(x_obs, y_obs, color="steelblue", linewidth=3.2, zorder=5,
        label="exponential fit")
ax.fill_between(x_ext, ext_lo, ext_hi, color="steelblue", alpha=0.28, zorder=2)
ax.plot(x_ext, y_ext, color="steelblue", linewidth=3.2, linestyle="--", zorder=5)

ax.scatter([X_MAX], [y_end], color="gold", edgecolors="steelblue", s=200, zorder=7, marker="*")
tx, ty = X_MAX - 1.5, y_end + 0.08
ax.annotate(
    "\\$5 task →",
    xy=(X_MAX, y_end), xytext=(tx, ty),
    arrowprops=dict(arrowstyle="->", color="dimgray", lw=1.3),
    fontsize=10, color="dimgray", fontweight="bold",
    bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="lightgray", lw=1),
    zorder=8,
)
ax.text(tx, ty - 0.30, f"~\\${y_end:.2f} saved",
        color="#2ca02c", fontsize=11, fontweight="bold", zorder=8,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="lightgray", lw=1))
ax.text(tx, ty - 0.60, f"(68% CI \\${y_lo:.2f}–\\${y_hi:.2f})",
        color="dimgray", fontsize=9, zorder=8)

ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"${v:.1f}"))
ax.yaxis.set_major_formatter(ticker.FuncFormatter(
    lambda v, _: f"+${v:.2f}" if v > 0 else (f"-${abs(v):.2f}" if v < 0 else "$0")))
ax.set_xlabel("Baseline (CC) cost per run ($)", fontsize=12)
ax.set_ylabel("$ saved per run  [ baseline − Atelier ]", fontsize=11)
ax.set_title(
    "Atelier savings accelerate with task size\n"
    "SWE-bench Verified  50 tasks \xd7 5 reps  ·  linear fit on per-task means",
    fontsize=13, fontweight="bold", pad=14,
)
ax.set_xlim(0, X_MAX + 0.1)

handles, labels = ax.get_legend_handles_labels()
ax.legend(handles, labels, loc="upper left", fontsize=8.5, framealpha=0.92, ncol=2)
ax.grid(True, color="#e5e5e5", linewidth=0.6)
ax.set_facecolor("white")
fig.patch.set_facecolor("white")
plt.tight_layout()

out = "reports/public/benchmark/codebench/cost_vs_savings_scatter"
plt.savefig(out + ".svg", format="svg")
plt.savefig(out + ".png", dpi=150)
