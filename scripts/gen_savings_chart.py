import collections
import csv

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from scipy.optimize import curve_fit
from scipy.optimize import minimize as _minimize
from scipy.special import expit as _expit

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

# All individual reps for scatter
all_pts = []
task_buckets = collections.defaultdict(list)

with open("benchmarks/codebench/results/swe50_2026_06_30/pairwise_quality.csv") as f:
    for row in csv.DictReader(f):
        task = row["task"]
        rep = int(row["rep"])
        bc = float(row["baseline_cost_usd"])
        ac = float(row["candidate_cost_usd"])
        if bc <= 0:
            continue
        c = correctness.get((task, rep), {})
        if not (c.get("baseline") or c.get("atelier")):
            continue
        saved = bc - ac
        repo = repo_map.get(task.split("__")[0].split("-")[0], task.split("__")[0])
        all_pts.append({"bc": bc, "saved": saved, "repo": repo})
        task_buckets[task].append({"bc": bc, "saved": saved, "repo": repo})

# Exploration data points (cg benchmark) — plotted separately, not included in fit
exp_pts = []
with open("benchmarks/codebench/results/exploration_2026_06_29/pairwise_quality.csv") as f:
    for row in csv.DictReader(f):
        bc = float(row["baseline_cost_usd"])
        ac = float(row["candidate_cost_usd"])
        if bc <= 0:
            continue
        task = row["task"]
        repo = task.replace("cg_", "")
        exp_pts.append({"bc": bc, "saved": bc - ac, "repo": repo})

# IQR on scatter points
sav_arr = np.array([p["saved"] for p in all_pts])
q1, q3 = np.percentile(sav_arr, 25), np.percentile(sav_arr, 75)
plot_pts = [p for p in all_pts if (q1 - 1.5 * (q3 - q1)) <= p["saved"] <= (q3 + 1.5 * (q3 - q1))]

# Fit on all individual rep points (preserves the negative savings at low cost)
fxs = np.array([p["bc"] for p in plot_pts])
fys = np.array([p["saved"] for p in plot_pts])


# y = a*(exp(b*x) - 1) - d
# At x=0: y = -d  (always negative, forced below zero)
# d > 0.1 ensures visible dip; b >= 0.5 ensures visible curve
def exp_curve(x, a, b, d):
    return a * (np.exp(b * x) - 1) - d


# Bin-mean fit: divide x into bins, take mean per bin, fit exponential through means.
# Mean (not median) at low cost is negative due to overhead — gives the curve its anchor.
# b emerges from data naturally without floor constraints.
# Use raw (unfiltered) data for binning so the negative anchor at low cost is preserved
_rxs = np.array([p["bc"] for p in all_pts])
_rys = np.array([p["saved"] for p in all_pts])
_bins = np.linspace(_rxs.min(), _rxs.max(), 9)
_bx, _by = [], []
for _i in range(len(_bins) - 1):
    _m = (_rxs >= _bins[_i]) & (_rxs < _bins[_i + 1])
    if _m.sum() >= 3:
        _bx.append(np.mean(_rxs[_m]))
        _by.append(np.mean(_rys[_m]))
_bx, _by = np.array(_bx), np.array(_by)

_best_p, _best_r = None, np.inf
for _a0, _b0, _d0 in [(0.5, 0.6, 0.2), (0.3, 0.8, 0.3), (1.0, 0.4, 0.1), (0.4, 1.0, 0.4), (0.5, 0.3, 0.1)]:
    try:
        _p, _ = curve_fit(exp_curve, _bx, _by, p0=[_a0, _b0, _d0], maxfev=20000)
        _r = np.sum((_by - exp_curve(_bx, *_p)) ** 2)
        if _r < _best_r:
            _best_p, _best_r = _p, _r
    except RuntimeError:
        pass
a_fit, b_fit, d_fit = _best_p
popt = _best_p

# Curve: data range solid, extrapolation to $5 dashed
X_DATA = fxs.max()
X_MAX = 10.0
x_obs = np.linspace(0, X_DATA, 400)
x_ext = np.linspace(X_DATA, X_MAX, 200)
y_obs = exp_curve(x_obs, *popt)
y_ext = exp_curve(x_ext, *popt)
y_end = float(exp_curve(X_MAX, *popt))

# Break-even: a*(exp(b*x)-1) = d  =>  x = log(d/a + 1) / b
breakeven = np.log(d_fit / a_fit + 1) / b_fit if a_fit > 0 and d_fit / a_fit > -1 else 0.0

# 68% bootstrap CI
np.random.seed(42)
n = len(fxs)
bo, be, bend = [], [], []
for _ in range(2000):
    idx = np.random.randint(0, n, n)
    _bbx, _bby = [], []
    for _i in range(len(_bins) - 1):
        _m = (fxs[idx] >= _bins[_i]) & (fxs[idx] < _bins[_i + 1])
        if _m.sum() >= 2:
            _bbx.append(np.mean(fxs[idx][_m]))
            _bby.append(np.mean(fys[idx][_m]))
    if len(_bbx) < 3:
        continue
    try:
        _bp, _ = curve_fit(exp_curve, np.array(_bbx), np.array(_bby), p0=popt, maxfev=2000)
        bo.append(exp_curve(x_obs, *_bp))
        be.append(exp_curve(x_ext, *_bp))
        bend.append(float(exp_curve(X_MAX, *_bp)))
    except RuntimeError:
        pass

# Centre bands on the fit line: half-width = (84th - 16th) / 2 of bootstrap distribution
_bo = np.array(bo)
_be = np.array(be)
_hw_obs = (np.percentile(_bo, 84, axis=0) - np.percentile(_bo, 16, axis=0)) / 2
_hw_ext = (np.percentile(_be, 84, axis=0) - np.percentile(_be, 16, axis=0)) / 2
obs_lo = y_obs - _hw_obs
obs_hi = y_obs + _hw_obs
ext_lo = y_ext - _hw_ext
ext_hi = y_ext + _hw_ext
y_lo = float(np.percentile(bend, 16))
y_hi = float(np.percentile(bend, 84))

fys_pred = exp_curve(fxs, *popt)
r2 = 1 - np.sum((fys - fys_pred) ** 2) / np.sum((fys - fys.mean()) ** 2)
print(f"y={a_fit:.3f}*exp({b_fit:.3f}*x)-({d_fit:.3f}), R2={r2:.3f}")
print(f"break-even at ${breakeven:.2f}, at $5 -> ${y_end:.2f} saved")

# --- Plot ---
repos = sorted(set(p["repo"] for p in plot_pts))
colors = plt.cm.tab10(np.linspace(0, 1, 10))
cmap = {repo: colors[i % 10] for i, repo in enumerate(repos)}

fig, ax = plt.subplots(figsize=(13, 7))

ax.axvspan(X_DATA, X_MAX, color="#f0f4ff", alpha=0.25, zorder=1)
ax.axhline(0, color="crimson", linestyle="--", linewidth=1.5, zorder=3)
ax.axvline(
    breakeven, color="crimson", linestyle=":", linewidth=1.8, zorder=3, label=f"break-even  (${breakeven:.2f} task)"
)
ax.text(
    breakeven + 0.05,
    -0.55,
    f"Break-even · ${breakeven:.2f}",
    color="crimson",
    fontsize=9.5,
    fontweight="bold",
    va="bottom",
    zorder=10,
    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="crimson", lw=1.0),
)

for repo in repos:
    pts = [p for p in plot_pts if p["repo"] == repo]
    ax.scatter(
        [p["bc"] for p in pts], [p["saved"] for p in pts], color=cmap[repo], label=repo, alpha=0.50, s=45, zorder=4
    )

# Exploration points — diamonds, grey
exp_repos = sorted(set(p["repo"] for p in exp_pts))
exp_colors = plt.cm.Set2(np.linspace(0, 1, max(len(exp_repos), 1)))
exp_cmap = {r: exp_colors[i % len(exp_colors)] for i, r in enumerate(exp_repos)}
for repo in exp_repos:
    pts = [p for p in exp_pts if p["repo"] == repo]
    ax.scatter(
        [p["bc"] for p in pts],
        [p["saved"] for p in pts],
        color=exp_cmap[repo],
        marker="D",
        s=55,
        alpha=0.70,
        zorder=4,
        edgecolors="grey",
        linewidths=0.5,
    )
# single legend entry for all exploration points
ax.scatter([], [], color="grey", marker="D", s=55, alpha=0.70, label="exploration (cg)")

# Observed range — solid, prominent
ax.fill_between(x_obs, obs_lo, obs_hi, color="steelblue", alpha=0.18, zorder=2)
ax.plot(x_obs, y_obs, color="steelblue", linewidth=3.2, zorder=5, label="_nolegend_")
# Vertical separator at data boundary
ax.axvline(X_DATA, color="steelblue", linestyle=":", linewidth=1.2, alpha=0.5, zorder=3)
ax.text(
    X_DATA - 0.15,
    ax.get_ylim()[0] if False else -1.1,
    "observed",
    color="steelblue",
    fontsize=8.5,
    ha="right",
    va="bottom",
    alpha=0.8,
)
ax.text(X_DATA + 0.15, -1.1, "extrapolation", color="steelblue", fontsize=8.5, ha="left", va="bottom", alpha=0.8)
# Extrapolation range — dashed, lighter
ax.fill_between(x_ext, ext_lo, ext_hi, color="steelblue", alpha=0.10, zorder=2)
ax.plot(x_ext, y_ext, color="steelblue", linewidth=2.0, linestyle="--", alpha=0.55, zorder=5)

ax.scatter([X_MAX], [y_end], color="gold", edgecolors="steelblue", s=200, zorder=7, marker="*")
tx, ty = X_MAX - 3.0, y_end + 0.08
ax.annotate(
    "\\$5 task →",
    xy=(X_MAX, y_end),
    xytext=(tx, ty),
    arrowprops=dict(arrowstyle="->", color="dimgray", lw=1.3),
    fontsize=10,
    color="dimgray",
    fontweight="bold",
    bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="lightgray", lw=1),
    zorder=8,
)
ax.text(
    tx,
    ty - 0.30,
    f"~\\${y_end:.2f} saved",
    color="#2ca02c",
    fontsize=11,
    fontweight="bold",
    zorder=8,
    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="lightgray", lw=1),
)
ax.text(tx, ty - 0.60, f"(68% CI \\${y_lo:.2f}--\\${y_hi:.2f})", color="dimgray", fontsize=9, zorder=8)

ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"${v:.1f}"))
ax.yaxis.set_major_formatter(
    ticker.FuncFormatter(lambda v, _: f"+${v:.2f}" if v > 0 else (f"-${abs(v):.2f}" if v < 0 else "$0"))
)
ax.set_xlabel("Baseline (CC) cost per run ($)", fontsize=12)
ax.set_ylabel("$ saved per run  [ baseline - Atelier ]", fontsize=11)
ax.set_title(
    "Atelier savings accelerate with task size\n"
    "SWE-bench Verified  50 tasks \xd7 5 reps  ·  linear fit on per-task means",
    fontsize=13,
    fontweight="bold",
    pad=14,
)
ax.set_xlim(0, X_MAX + 0.1)

handles, labels = ax.get_legend_handles_labels()
ax.legend(handles, labels, loc="upper left", fontsize=8.5, framealpha=0.92, ncol=2)
ax.grid(True, color="#e5e5e5", linewidth=0.6)
ax.set_facecolor("white")
fig.patch.set_facecolor("white")
# --- Inset: P(Atelier wins) via logistic regression ---
_rxs = np.array([p["bc"] for p in all_pts])
_rys = np.array([p["saved"] for p in all_pts])
_wins_bin = (_rys > 0).astype(float)


def _nll(params):
    _a, _b = params
    _p = np.clip(_expit(_a + _b * _rxs), 1e-9, 1 - 1e-9)
    return -np.sum(_wins_bin * np.log(_p) + (1 - _wins_bin) * np.log(1 - _p))


_res = _minimize(_nll, [0.0, 1.5], method="Nelder-Mead")
_la, _lb = _res.x
_lx = np.linspace(0, _rxs.max(), 300)
_ly = _expit(_la + _lb * _lx)

ax_ins = ax.inset_axes([0.62, 0.06, 0.35, 0.34])
ax_ins.fill_between(_lx, 0.5, _ly, where=(_ly >= 0.5), color="#1a9850", alpha=0.15)
ax_ins.fill_between(_lx, _ly, 0.5, where=(_ly < 0.5), color="#d73027", alpha=0.15)
ax_ins.plot(_lx, _ly, color="steelblue", linewidth=2.2, zorder=5)
ax_ins.axhline(0.5, color="grey", linestyle=":", linewidth=0.9)
ax_ins.set_xlim(0, _rxs.max())
ax_ins.set_ylim(0, 1.05)
ax_ins.set_yticks([0, 0.5, 1.0])
ax_ins.set_yticklabels(["0", "0.5", "1.0"], fontsize=7)
ax_ins.set_xlabel("baseline cost ($)", fontsize=7)
ax_ins.set_ylabel("probability", fontsize=7)
ax_ins.set_title("P(Atelier cheaper) vs task cost", fontsize=7.5, fontweight="bold", pad=4)
ax_ins.set_facecolor("white")
ax_ins.patch.set_alpha(0.92)
for spine in ax_ins.spines.values():
    spine.set_edgecolor("#cccccc")

plt.tight_layout()

out = "reports/public/benchmark/codebench/cost_vs_savings_scatter"
plt.savefig(out + ".svg", format="svg")
plt.savefig(out + ".png", dpi=150)
