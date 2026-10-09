"""One-at-a-time sensitivity of the severity classification to its judgement-based parameters.

    .venv\\Scripts\\python experiments\\sensitivity.py data\\raw\\<model>

Detection runs once (geometry does not depend on these parameters). For every variant the
load path / severity is recomputed and compared with the reference configuration:
  n_CM      number of Critical+Major hard clashes
  jaccard   overlap of the Critical+Major set with the reference set
  agree     fraction of hard clashes keeping the same class
  kappa_w   quadratic-weighted Cohen's kappa of the 4-level classes
  tau_top50 Kendall tau of the scores of the reference top-50
Output: results/<case>/sensitivity.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kendalltau
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import dtclash.severity as sev  # noqa: E402
from dtclash.clash import ClashDetector  # noqa: E402
from dtclash.loadpath import LoadCase, LoadPathGraph  # noqa: E402
from dtclash.model import Model  # noqa: E402

ORDER = {"Negligible": 0, "Minor": 1, "Major": 2, "Critical": 3}
REF = dict(eta_scale=1.0, bays_scale=1.0, alpha=0.3, beta=2.0, ll=2.4, sdl=1.5, tol=0.05, end_tol=0.15)
VARIANTS = {
    "eta_scale": [0.67, 0.8, 1.25, 1.5],
    "bays_scale": [0.5, 0.75, 1.5, 2.0],
    "alpha": [0.0, 0.15, 0.5, 0.7],
    "beta": [1.0, 4.0],
    "ll": [1.9, 4.8],          # ASCE 7-22: residential 1.9 kPa ... assembly/storage 4.8 kPa
    "sdl": [1.0, 2.5],
    "tol": [0.025, 0.10],
    "end_tol": [0.10, 0.30],
}


def evaluate(model, clashes, p, lp_cache):
    key = (p["alpha"], p["ll"], p["sdl"], p["tol"], p["end_tol"])
    lp = lp_cache.get(key)
    if lp is None:
        lp = LoadPathGraph(model, contact_tol=p["tol"], end_tol=p["end_tol"], alpha=p["alpha"],
                           loads=LoadCase(sdl=p["sdl"], ll=p["ll"]))
        lp.run()
        lp_cache[key] = lp
    eta0, bd0, be0 = sev.ETA_LEVELS, sev.BAYS_D, sev.BAYS_E
    try:
        sev.ETA_LEVELS = tuple(x * p["eta_scale"] for x in eta0)
        sev.BAYS_D = tuple(x * p["bays_scale"] for x in bd0)
        sev.BAYS_E = tuple(x * p["bays_scale"] for x in be0)
        res = sev.assess(clashes, model, lp, beta=p["beta"])
    finally:
        sev.ETA_LEVELS, sev.BAYS_D, sev.BAYS_E = eta0, bd0, be0
    return res, lp


def main():
    model = Model(sys.argv[1])
    case = model.meta["host_tag"]
    clashes = [c for c in ClashDetector(model).run() if c.kind == "hard"]
    print(model, len(clashes), "hard clashes")
    cache = {}
    ref, _ = evaluate(model, clashes, REF, cache)
    ref_cls = np.array([ORDER[a.severity] for a in ref])
    ref_cm = {i for i, a in enumerate(ref) if a.severity in ("Critical", "Major")}
    ref_score = np.array([a.score for a in ref])
    top = np.argsort(-ref_score)[:50]
    rows = [{"param": "reference", "value": "", "n_CM": len(ref_cm), "jaccard": 1.0, "agree": 1.0,
             "kappa_w": 1.0, "tau_top50": 1.0}]
    for name, vals in VARIANTS.items():
        for v in vals:
            p = dict(REF, **{name: v})
            res, lp = evaluate(model, clashes, p, cache)
            cls = np.array([ORDER[a.severity] for a in res])
            cm = {i for i, a in enumerate(res) if a.severity in ("Critical", "Major")}
            score = np.array([a.score for a in res])
            union = ref_cm | cm
            rows.append({
                "param": name, "value": v, "n_CM": len(cm),
                "jaccard": len(ref_cm & cm) / len(union) if union else 1.0,
                "agree": float((cls == ref_cls).mean()),
                "kappa_w": float(cohen_kappa_score(ref_cls, cls, weights="quadratic", labels=[0, 1, 2, 3])),
                "tau_top50": float(kendalltau(ref_score[top], score[top]).statistic),
                "unsupported": len(lp.notes["unsupported"]),
            })
            print(rows[-1])
    out = ROOT / "results" / case / "sensitivity.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print("->", out)


if __name__ == "__main__":
    main()
