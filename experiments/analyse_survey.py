"""Analyse returned expert rating forms against the methods.

    .venv\\Scripts\\python experiments\\analyse_survey.py survey/returned/*.xlsx

Reports inter-rater reliability (Krippendorff's alpha, ordinal; mean pairwise quadratic-weighted
kappa), the consensus (median) rating per item, and for each method its quadratic-weighted
kappa, exact agreement and Spearman rho against the consensus, plus Critical/Major recall.
Output: survey/agreement.csv, survey/consensus.csv
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parents[1]
ORDER = {"Negligible": 0, "Minor": 1, "Major": 2, "Critical": 3}
METHODS = ["sev_proposed", "sev_local_only", "sev_geometry", "sev_category"]


def read_form(path):
    wb = load_workbook(path, data_only=True)
    ins = wb["Instructions"]
    rid = next((ins.cell(r, 2).value for r in range(1, ins.max_row + 1)
                if str(ins.cell(r, 1).value or "").startswith("Rater ID")), None) or Path(path).stem
    rows = []
    for r in wb["Ratings"].iter_rows(min_row=2, values_only=True):
        if r[0] and r[6] in ORDER:
            rows.append({"item": r[0], "rater": str(rid), "rating": ORDER[r[6]], "confidence": r[7]})
    return rows


def krippendorff_alpha_ordinal(mat):
    """mat: items x raters with NaN for missing; ordinal distance metric."""
    vals = sorted({v for v in mat.flatten() if not np.isnan(v)})
    idx = {v: i for i, v in enumerate(vals)}
    k = len(vals)
    o = np.zeros((k, k))
    for row in mat:
        r = row[~np.isnan(row)]
        m = len(r)
        if m < 2:
            continue
        for a, b in itertools.permutations(range(m), 2):
            o[idx[r[a]], idx[r[b]]] += 1 / (m - 1)
    n_c = o.sum(1)
    n = n_c.sum()
    d = np.zeros((k, k))
    for c in range(k):
        for e in range(k):
            lo, hi = min(c, e), max(c, e)
            d[c, e] = (n_c[lo:hi + 1].sum() - (n_c[lo] + n_c[hi]) / 2) ** 2
    do = (o * d).sum() / n
    de = (np.outer(n_c, n_c) * d).sum() / (n * (n - 1))
    return 1 - do / de if de > 0 else float("nan")


def main(paths):
    rows = [r for p in paths for r in read_form(p)]
    df = pd.DataFrame(rows)
    piv = df.pivot_table(index="item", columns="rater", values="rating")
    alpha = krippendorff_alpha_ordinal(piv.to_numpy(dtype=float))
    raters = list(piv.columns)
    pair_k = [cohen_kappa_score(piv[a].dropna().loc[piv[b].dropna().index.intersection(piv[a].dropna().index)],
                                piv[b].loc[piv[b].dropna().index.intersection(piv[a].dropna().index)],
                                weights="quadratic") for a, b in itertools.combinations(raters, 2)]
    cons = piv.median(axis=1).round().astype(int).rename("consensus")
    key = pd.read_csv(ROOT / "survey" / "answer_key.csv").set_index("item")
    j = key.join(cons, how="inner")
    out = []
    for mth in METHODS:
        pred = j[mth].map(ORDER)
        out.append({"method": mth, "n_items": len(j),
                    "kappa_w": cohen_kappa_score(j.consensus, pred, weights="quadratic", labels=[0, 1, 2, 3]),
                    "exact_agreement": float((pred == j.consensus).mean()),
                    "spearman": spearmanr(pred, j.consensus).statistic,
                    "CM_recall": float(((pred >= 2) & (j.consensus >= 2)).sum() / max(1, (j.consensus >= 2).sum())),
                    "CM_precision": float(((pred >= 2) & (j.consensus >= 2)).sum() / max(1, (pred >= 2).sum()))})
    res = pd.DataFrame(out)
    res.to_csv(ROOT / "survey" / "agreement.csv", index=False)
    j.to_csv(ROOT / "survey" / "consensus.csv")
    print(f"raters={len(raters)} items={len(piv)}  Krippendorff alpha (ordinal)={alpha:.3f}  "
          f"mean pairwise kappa_w={np.mean(pair_k) if pair_k else float('nan'):.3f}")
    print(res.round(3).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1:])
