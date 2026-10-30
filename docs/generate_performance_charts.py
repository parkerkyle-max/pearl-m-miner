"""Regenerate charts from the checked-in sanitized evidence; no network input."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "docs/data/performance.json").read_text())
RUNS = {item["id"]: item for item in DATA["records"]}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12,
                    "svg.fonttype": "none", "savefig.facecolor": "#0b1020"})
fig, axes = plt.subplots(1, 2, figsize=(14, 6.9), gridspec_kw={"wspace": 0.22})
fig.patch.set_facecolor("#0b1020")
panels = [
    (axes[0], ["historical-upstream", "historical-pearly", "s10-s-final-pool180"],
     ["Upstream + cert-v3 patch", "Pearly 1.0.3", "Pearl M-Miner S"],
     "HISTORICAL CONTEXT", "600 s earlier windows vs 180 s latest\nNot a fresh matched cross-miner A/B"),
    (axes[1], ["s5-baseline-pool180", "s7-baseline-after-pool180", "s10-s-final-pool180"],
     ["Our optimized baseline (before)", "Our optimized baseline (after)", "Pearl M-Miner S"],
     "LATEST OPTIMIZATION", "Same Mac and pool; sequential 180 s trials\n+30.4–31.9% vs our optimized baseline"),
]
for ax, ids, labels, title, subtitle in panels:
    ax.set_facecolor("#0b1020")
    colors = ["#526986", "#a78bfa", "#40d7e3"]
    for i, (run_id, label, color) in enumerate(zip(ids, labels, colors)):
        y = 2 - i
        value = RUNS[run_id]["rate_ths"]
        ax.barh(y, value, height=0.39, color=color, zorder=3)
        ax.text(0, y + 0.27, label, color="#ecf2ff", fontsize=12, va="bottom")
        ax.text(value + 0.07, y, f"{value:.3f}", color="#ecf2ff", fontsize=12, va="center", weight="bold")
    ax.set_xlim(0, 4.45)
    ax.set_ylim(-0.35, 2.75)
    ax.set_yticks([])
    ax.xaxis.set_major_locator(MultipleLocator(1))
    ax.tick_params(axis="x", colors="#9baccc", labelsize=11, length=0)
    ax.grid(axis="x", color="#24324a", linewidth=0.8, zorder=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlabel("Logged protocol-equivalent rate (TH/s)", color="#9baccc", labelpad=12)
    ax.text(0, 1.23, title, transform=ax.transAxes, color="#e5bc64", fontsize=11, weight="bold")
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, color="#a8b6cf", fontsize=11, va="bottom", linespacing=1.5)
fig.text(0.065, 0.94, "One M1 Max. The baseline matters.", color="#f2f6ff", fontsize=25, weight="bold")
fig.text(0.065, 0.895, "32-core GPU · 64 GiB · macOS 26.6.1 · research backend measurements", color="#a8b6cf", fontsize=12)
fig.text(0.065, 0.12, "3.58× historical upstream-based logged rate  ≠  30–32% latest-stage improvement", color="#e5bc64", fontsize=13, weight="bold")
fig.text(0.065, 0.084, "Printed scan rates are not pool payouts. Historical sampling differs; short trials do not prove long-run income.\nLatest 180 s: 7 accepted / 0 rejected, independently matched by the pool API. Release fee schedule was not active.", color="#9baccc", fontsize=10.5, linespacing=1.7, va="top")
fig.subplots_adjust(left=0.065, right=0.96, top=0.71, bottom=0.24)
for ext in ("svg", "png"):
    fig.savefig(ROOT / f"assets/performance.{ext}", dpi=160, metadata={"Creator": "Pearl M-Miner evidence chart"})
plt.close(fig)
print("Regenerated assets/performance.svg and assets/performance.png from 6 evidence records.")
