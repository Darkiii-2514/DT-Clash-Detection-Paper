"""Publication figures from results/<case>/ (run after run_case, sensitivity, twin_bench).

    .venv\\Scripts\\python experiments\\figures.py

Writes paper/figures/fig2..fig7 (PNG, 600 dpi) sized for Elsevier columns (90 / 190 mm).
Colour use follows one rule per job: severity classes are ORDINAL (one blue ramp, light -> dark,
Coordination in neutral grey); methods / cases are CATEGORICAL in a fixed slot order.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "figures"
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]

MM = 1 / 25.4
W1, W2 = 90 * MM, 190 * MM
INK, INK2, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#ffffff"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SEV = ["Negligible", "Minor", "Major", "Critical"]
SEV_C = {"Negligible": "#86b6ef", "Minor": "#3987e5", "Major": "#1c5cab", "Critical": "#0d366b",
         "Coordination": "#c3c2b7"}
METHOD_LABEL = {"sev_proposed": "Proposed (load-path aware)", "sev_local_only": "Local impact only",
                "sev_geometry": "Geometry only", "sev_category": "Category rules"}
CASE_LABEL = {"Snowdon_Towers_Sample_Structural": "Snowdon Towers",
              "BIM_Projekt_Golden_Nugget-Architektur_und_Ingenieurbau": "Golden Nugget"}

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "Arial", "DejaVu Sans"],
    "font.size": 7, "axes.titlesize": 7.5, "axes.labelsize": 7, "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5, "legend.fontsize": 6.5, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.dpi": 600,
    "legend.frameon": False,
})


def cases():
    out = []
    for name in CASE_LABEL:
        d = ROOT / "results" / name
        if (d / "clashes.csv").exists():
            out.append((name, d))
    return out


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("->", OUT / name)


# ------------------------------------------------------------------ Fig. 2 scalability & run time
def fig_detection():
    cs = cases()
    fig, axes = plt.subplots(1, 2, figsize=(W2, 62 * MM))
    ax = axes[0]
    sc = ROOT / "results" / cs[0][0] / "scalability.csv"
    if sc.exists():
        scl = pd.read_csv(sc)
        for j, (col, lab) in enumerate((("bruteforce_s", "Brute-force AABB test"), ("rtree_s", "R-tree (proposed)"))):
            ax.plot(scl.pairs, scl[col], color=CAT[j], lw=1.5, marker="o", ms=4, label=lab)
            ax.annotate(f"{scl[col].iloc[-1]:.2f} s" if scl[col].iloc[-1] < 10 else f"{scl[col].iloc[-1]:.0f} s",
                        (scl.pairs.iloc[-1], scl[col].iloc[-1]), xytext=(4, 0), textcoords="offset points",
                        fontsize=6, color=INK2, va="center")
        top = ax.secondary_xaxis("top", functions=(lambda x: x / scl.pairs.iloc[0], lambda x: x * scl.pairs.iloc[0]))
        top.set_xlabel("Model tiled k times (pairs grow with k²)", fontsize=6, color=MUTED)
        top.tick_params(labelsize=5.5)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Structural × MEP element pairs (log)")
        ax.set_ylabel("Broad-phase time (s, log)")
        ax.legend(loc="upper left")
    ax.set_title("(a) Broad-phase scalability", loc="left", pad=18)

    ax = axes[1]
    labels, vals, cols = [], [], []
    for name, d in cs:
        s = json.loads((d / "summary.json").read_text())
        meta = json.loads((ROOT / "data" / "raw" / name / "meta.json").read_text())
        t = s["timing_s"]
        ours = t["broadphase_rtree"] + t["narrowphase_s"] + t["loadpath"] + t["severity"]
        labels += [CASE_LABEL[name] + "\nproposed: detection +\nload path + severity",
                   CASE_LABEL[name] + "\nRevit solid filter:\ndetection only"]
        vals += [ours, meta.get("t_reference_s", np.nan)]
        cols += [CAT[0], AXIS]
    y = np.arange(len(vals))
    ax.barh(y, vals, color=cols, height=0.55, edgecolor=SURF, linewidth=1)
    for yi, v in zip(y, vals):
        ax.text(v + max(vals) * 0.02, yi, f"{v:.0f} s", va="center", fontsize=6.5, color=INK2)
    ax.set_yticks(y, labels, fontsize=6)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.18)
    ax.set_xlabel("Wall-clock time (s)")
    ax.set_title("(b) End-to-end time per model", loc="left", pad=18)
    ax.grid(axis="y", visible=False)
    fig.subplots_adjust(wspace=0.55)
    save(fig, "fig2_detection.png")


# ------------------------------------------------------------------ Fig. 3 load path
def fig_loadpath():
    from dtclash.loadpath import GROUND, LoadPathGraph
    from dtclash.model import Model
    name, d = cases()[0]
    model = Model(ROOT / "data" / "raw" / name)
    lp = LoadPathGraph(model)
    met = lp.run()
    mem = pd.DataFrame.from_dict(met, orient="index")
    fig = plt.figure(figsize=(W2, 72 * MM))
    ax = fig.add_subplot(1, 2, 1, projection="3d")
    vals = np.log10(np.maximum(mem.carried_kN, 1.0))
    norm = plt.Normalize(vals.min(), vals.max())
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#3987e5", "#0d366b"])
    for u, v in lp.G.edges():
        if v == GROUND:
            continue
        a, b = lp.elems[u].centroid, lp.elems[v].centroid
        ax.plot([a[0], b[0]], [a[1], b[1]], [a[2], b[2]], color=GRID, lw=0.25, zorder=1)
    cents = np.stack([lp.elems[u].centroid for u in mem.index])
    sc = ax.scatter(cents[:, 0], cents[:, 1], cents[:, 2], c=vals, cmap=cmap, norm=norm, s=2.5, linewidths=0)
    uns = [lp.elems[u].centroid for u in lp.notes["unsupported"]]
    if uns:
        uns = np.stack(uns)
        ax.scatter(uns[:, 0], uns[:, 1], uns[:, 2], s=9, facecolors="none", edgecolors=CAT[1], linewidths=0.6,
                   label=f"unsupported ({len(uns)})")
        ax.legend(loc="upper left", fontsize=6)
    ax.view_init(elev=18, azim=-60)
    ax.set_title(f"(a) Load-path graph, {CASE_LABEL[name]}", loc="left", fontsize=7)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.fill = False
        axis.pane.set_edgecolor(GRID)
    ax.tick_params(labelsize=5, pad=0)
    cb = fig.colorbar(sc, ax=ax, shrink=0.55, pad=0.12)
    cb.set_label("log$_{10}$ carried load (kN)", fontsize=6)
    cb.ax.tick_params(labelsize=5.5)
    ax2 = fig.add_subplot(1, 2, 2)
    kinds = [k for k in ["slab", "beam", "wall", "column", "foundation"] if k in set(mem.kind)]
    data = [mem.loc[mem.kind == k, "carried_kN"].clip(lower=1) for k in kinds]
    pos = np.arange(len(kinds))
    for i, dd in enumerate(data):
        jitter = (np.random.default_rng(0).random(len(dd)) - 0.5) * 0.5
        ax2.scatter(pos[i] + jitter, dd, s=2.2, color=CAT[0], alpha=0.35, linewidths=0)
        q = np.percentile(dd, [25, 50, 75])
        ax2.plot([pos[i] - 0.3, pos[i] + 0.3], [q[1]] * 2, color=INK, lw=1.2)
        ax2.plot([pos[i]] * 2, [q[0], q[2]], color=INK, lw=0.8)
    ax2.axhline(lp.D_ref, color=CAT[1], lw=0.8, ls="--")
    ax2.text(len(kinds) - 0.5, lp.D_ref * 1.25, f"D_ref = {lp.D_ref:.0f} kN (median beam)", ha="right",
             color=INK2, fontsize=6)
    ax2.set_yscale("log")
    ax2.set_xticks(pos, [f"{k}\n(n={len(dd)})" for k, dd in zip(kinds, data)])
    ax2.set_ylabel("Factored load carried, D (kN)")
    ax2.set_title(f"(b) Load carried by member type (ground/total = "
                  f"{sum(lp.carried[u] * lp.G.edges[u, GROUND].get('share', 1.0) for u in lp.G.predecessors(GROUND)) / lp.total_load:.4f})",
                  loc="left")
    ax2.grid(axis="x", visible=False)
    fig.subplots_adjust(wspace=0.25)
    save(fig, "fig3_loadpath.png")


# ------------------------------------------------------------------ Fig. 4 severity distribution
def fig_severity():
    cs = cases()
    fig, axes = plt.subplots(1, len(cs), figsize=(W2, 58 * MM), sharey=False, squeeze=False)
    for ax, (name, d) in zip(axes[0], cs):
        h = pd.read_csv(d / "clashes.csv")
        h = h[h.kind == "hard"]
        methods = list(METHOD_LABEL)
        y = np.arange(len(methods))
        for i, mth in enumerate(methods):
            cnt = h[mth].value_counts()
            left = 0
            for c in SEV:
                v = int(cnt.get(c, 0))
                if v:
                    ax.barh(i, v, left=left, color=SEV_C[c], height=0.55, edgecolor=SURF, linewidth=1)
                    if v / len(h) > 0.06:
                        ax.text(left + v / 2, i, str(v), ha="center", va="center", fontsize=5.8,
                                color="white" if c in ("Major", "Critical", "Minor") else INK)
                left += v
            cm = int(cnt.get("Critical", 0) + cnt.get("Major", 0))
            ax.text(left + len(h) * 0.02, i, f"C+M = {cm}", va="center", fontsize=6, color=INK2)
        ax.set_yticks(y, [METHOD_LABEL[m] for m in methods])
        ax.invert_yaxis()
        ax.set_xlim(0, len(h) * 1.22)
        ax.set_xlabel(f"Hard clashes (n = {len(h)})")
        ax.set_title(CASE_LABEL[name], loc="left")
        ax.grid(axis="y", visible=False)
    fig.legend([plt.Rectangle((0, 0), 1, 1, color=SEV_C[c]) for c in SEV], SEV, loc="lower center", ncol=4,
               bbox_to_anchor=(0.55, -0.06))
    fig.subplots_adjust(wspace=0.75, bottom=0.25)
    save(fig, "fig4_severity.png")


# ------------------------------------------------------------------ Fig. 5 cross-tabulation
def fig_crosstab():
    cs = cases()
    fig, axes = plt.subplots(1, len(cs), figsize=(W2 * (0.5 * len(cs)), 62 * MM), squeeze=False)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("b", ["#ffffff", "#cde2fb", "#3987e5", "#0d366b"])
    for ax, (name, d) in zip(axes[0], cs):
        h = pd.read_csv(d / "clashes.csv")
        h = h[h.kind == "hard"]
        ct = pd.crosstab(h.sev_geometry, h.sev_proposed).reindex(index=SEV, columns=SEV, fill_value=0)
        im = ax.imshow(np.log1p(ct.values), cmap=cmap, vmin=0)
        for i in range(4):
            for j in range(4):
                v = ct.values[i, j]
                ax.text(j, i, str(v), ha="center", va="center", fontsize=6.5,
                        color="white" if np.log1p(v) > np.log1p(ct.values.max()) * 0.6 else INK)
        ax.set_xticks(range(4), SEV, rotation=0)
        ax.set_yticks(range(4), SEV)
        ax.set_xlabel("Proposed (load-path aware)")
        ax.set_ylabel("Geometry only")
        ax.set_title(CASE_LABEL[name], loc="left")
        ax.grid(False)
        for s in ax.spines.values():
            s.set_visible(False)
    fig.subplots_adjust(wspace=0.45)
    save(fig, "fig5_crosstab.png")


# ------------------------------------------------------------------ Fig. 6 sensitivity
def fig_sensitivity():
    name, d = cases()[0]
    f = d / "sensitivity.csv"
    if not f.exists():
        print("no sensitivity.csv; skipped")
        return
    s = pd.read_csv(f)
    s = s[s.param != "reference"].copy()
    nice = {"eta_scale": "Impact thresholds ×", "bays_scale": "Consequence thresholds ×", "alpha": "α (orphan weight)",
            "beta": "β (score weight)", "ll": "Live load (kPa)", "sdl": "Superimposed dead load (kPa)",
            "tol": "Contact tolerance (m)", "end_tol": "End tolerance (m)"}
    s["label"] = [(f"{nice[p]} {v:g}" if p.endswith("scale") else f"{nice[p]} = {v:g}") for p, v in zip(s.param, s.value)]
    fig, axes = plt.subplots(1, 3, figsize=(W2, 80 * MM), sharey=True)
    y = np.arange(len(s))
    for ax, col, title in ((axes[0], "jaccard", "(a) Jaccard, Critical+Major set"),
                           (axes[1], "kappa_w", "(b) Weighted κ, 4 classes"),
                           (axes[2], "tau_top50", "(c) Kendall τ, top-50 ranking")):
        ax.hlines(y, 0, s[col], color=GRID, lw=0.8)
        ax.scatter(s[col], y, s=14, color=CAT[0], zorder=3, linewidths=0)
        for yi, v in zip(y, s[col]):
            ax.text(min(v, 1.0) + 0.02, yi, f"{v:.2f}", va="center", fontsize=5.8, color=INK2)
        ax.set_xlim(0, 1.15)
        ax.set_title(title, loc="left")
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(y, s.label)
    axes[0].invert_yaxis()
    fig.subplots_adjust(wspace=0.08)
    save(fig, "fig7_sensitivity.png")


# ------------------------------------------------------------------ Fig. 7 twin latency
def fig_twin():
    cs = [(n, d) for n, d in cases() if (d / "twin_bench.csv").exists()]
    if not cs:
        print("no twin_bench.csv; skipped")
        return
    order = ["mep_move", "mep_resize", "mep_add", "mep_delete", "struct_move", "struct_delete"]
    nice = {"mep_move": "MEP move", "mep_resize": "MEP resize", "mep_add": "MEP add", "mep_delete": "MEP delete",
            "struct_move": "Beam move", "struct_delete": "Beam delete"}
    fig, ax = plt.subplots(figsize=(W2 * 0.62, 62 * MM))
    width = 0.8 / len(cs)
    for ci, (name, d) in enumerate(cs):
        b = pd.read_csv(d / "twin_bench.csv")
        summ = json.loads((d / "twin_bench_summary.json").read_text())
        for i, t in enumerate(order):
            v = b.loc[b.type == t, "total_ms"].to_numpy()
            if not len(v):
                continue
            x = i + (ci - (len(cs) - 1) / 2) * width
            jit = (np.random.default_rng(i).random(len(v)) - 0.5) * width * 0.6
            ax.scatter(x + jit, v, s=4, color=CAT[ci], alpha=0.5, linewidths=0)
            ax.plot([x - width * 0.35, x + width * 0.35], [np.median(v)] * 2, color=INK, lw=1.2)
        full = summ.get("full_recompute_ms_mean")
        if full:
            ax.axhline(full, color=CAT[ci], lw=0.8, ls="--")
            ax.text(len(order) - 0.45, full * 1.15, f"full recompute, {CASE_LABEL[name]} ({full / 1000:.0f} s)",
                    ha="right", fontsize=6, color=INK2)
    ax.set_yscale("log")
    ax.set_xticks(range(len(order)), [nice[t] for t in order])
    ax.set_ylabel("Incremental update latency (ms, log scale)")
    ax.grid(axis="x", visible=False)
    if len(cs) > 1:
        ax.legend([plt.Line2D([], [], marker="o", ls="", color=CAT[i]) for i in range(len(cs))],
                  [CASE_LABEL[n] for n, _ in cs], loc="upper left")
    save(fig, "fig8_twin_latency.png")


# ------------------------------------------------------------------ Fig. 8 example clashes
def fig_examples():
    from dtclash.model import Model
    from render import render_clash
    name, d = cases()[0]
    model = Model(ROOT / "data" / "raw" / name)
    h = pd.read_csv(d / "clashes.csv")
    h = h[h.kind == "hard"]
    picks = []

    def take(df, title):
        if len(df):
            picks.append((df.iloc[0], title))

    take(h[h.sev_proposed == "Critical"].sort_values("score", ascending=False), "Proposed Critical")
    take(h[(h.sev_proposed == "Major") & h["flags"].fillna("").str.contains("flange_cut")]
         .sort_values("score", ascending=False), "Proposed Major / geometry Minor")
    take(h[(h.sev_proposed == "Major") & h["flags"].fillna("").str.contains("chord_cut")]
         .sort_values("score", ascending=False), "Proposed Major (open-web joist)")
    take(h[(h.sev_geometry == "Critical") & (h.sev_proposed == "Negligible")]
         .sort_values("overlap_volume", ascending=False), "Geometry Critical / proposed Negligible")
    tmp = OUT / "src"
    tmp.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(W2, 118 * MM))
    for ax, (k, (r, title)) in zip(axes.flat, enumerate(picks)):
        p = tmp / f"example_{k}.png"
        render_clash(model, r.s, r.m, json.loads(r.point) if isinstance(r.point, str) else r.point, p, dpi=300)
        ax.imshow(plt.imread(p))
        ax.axis("off")
        ax.set_title(f"({'abcd'[k]}) {title}: {r.s_kind} × {r.m_kind} ({r.m_size * 1000:.0f} mm)\n"
                     f"η = {r.eta:.2f} ({r.action}), D = {r.D_kN:.0f} kN · geometry: {r.sev_geometry}, "
                     f"proposed: {r.sev_proposed}", loc="left", fontsize=6.5)
    for ax in list(axes.flat)[len(picks):]:
        ax.axis("off")
    fig.subplots_adjust(wspace=0.02, hspace=0.18)
    save(fig, "fig6_examples.png")


if __name__ == "__main__":
    which = sys.argv[1:] or ["detection", "loadpath", "severity", "crosstab", "sensitivity", "twin"]
    for w in which:
        globals()[f"fig_{w}"]()
