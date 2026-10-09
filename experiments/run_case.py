"""Run the full pipeline on one exported model and write result tables.

    .venv\\Scripts\\python experiments\\run_case.py data\\raw\\Snowdon_Towers_Sample_Structural

Outputs -> results/<case>/:
    clashes.csv          one row per clash: geometry, severity (proposed + baselines)
    members.csv          load-path metrics per structural member
    detection.json       agreement with Revit's ElementIntersectsSolidFilter reference
    summary.json         counts, timings, graph statistics
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dtclash.clash import ClashDetector, broadphase_bruteforce, broadphase_rtree  # noqa: E402
from dtclash.loadpath import LoadPathGraph  # noqa: E402
from dtclash.model import Model  # noqa: E402
from dtclash.severity import assess, baseline_category, baseline_geometry  # noqa: E402


def detection_agreement(clashes, reference):
    """Pair-level agreement of physical clashes (hard+touch) with Revit's reference."""
    ours = {(c.s, c.m) for c in clashes if c.kind in ("hard", "touch")}
    hard = {(c.s, c.m) for c in clashes if c.kind == "hard"}
    tp, fp, fn = len(ours & reference), len(ours - reference), len(reference - ours)
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    return {
        "reference_pairs": len(reference), "detected_physical": len(ours), "detected_hard": len(hard),
        "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r,
        "f1": 2 * p * r / (p + r) if p + r else float("nan"),
        "hard_only_recall": len(hard & reference) / len(reference) if reference else float("nan"),
        "fp_pairs": sorted(ours - reference)[:200], "fn_pairs": sorted(reference - ours)[:200],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("--clearance", type=float, default=0.025)
    ap.add_argument("--alpha", type=float, default=0.3)
    ap.add_argument("--beta", type=float, default=2.0)
    a = ap.parse_args()

    t0 = time.perf_counter()
    model = Model(a.export_dir)
    t_load = time.perf_counter() - t0
    case = model.meta["host_tag"]
    out = ROOT / "results" / case
    out.mkdir(parents=True, exist_ok=True)
    print(model, f"(loaded in {t_load:.1f} s)")

    # ---- broad-phase scalability (candidate sets must be identical)
    tb = time.perf_counter(); bf = set(broadphase_bruteforce(model.structural, model.mep, a.clearance))
    t_bf = time.perf_counter() - tb
    tr = time.perf_counter(); rt = set(broadphase_rtree(model.structural, model.mep, a.clearance))
    t_rt = time.perf_counter() - tr
    assert bf == rt, "broad phases disagree"

    # ---- clash detection
    det = ClashDetector(model, clearance=a.clearance)
    clashes = det.run()
    print("clashes:", Counter(c.kind for c in clashes), det.timing)
    agreement = detection_agreement(clashes, model.reference_pairs)
    print({k: v for k, v in agreement.items() if not k.endswith("pairs") or k == "reference_pairs"})

    # ---- load path
    tl = time.perf_counter()
    lp = LoadPathGraph(model, alpha=a.alpha)
    metrics = lp.run()
    t_lp = time.perf_counter() - tl
    print(f"load path: {lp.G.number_of_nodes()} nodes, {lp.G.number_of_edges()} edges, "
          f"{len(lp.notes['unsupported'])} unsupported, {lp.notes['removed_cycle_edges']} cycle edges removed "
          f"({t_lp:.1f} s)")

    # ---- severity
    ts = time.perf_counter()
    prop = assess(clashes, model, lp, beta=a.beta)
    local_only = assess(clashes, model, lp, beta=a.beta, use_loadpath=False)
    t_sev = time.perf_counter() - ts

    rows = []
    for c, p, lo in zip(clashes, prop, local_only):
        s, m = model.by_uid[c.s], model.by_uid[c.m]
        r = c.as_row()
        r.update({
            "s_kind": s.kind, "s_doc": s.doc, "s_id": s.id, "s_level": s.level, "s_material": s.props.get("material_type") or s.props.get("material"),
            "s_length": s.frame.length, "s_width": s.frame.width, "s_depth": s.frame.depth,
            "m_kind": m.kind, "m_doc": m.doc, "m_id": m.id, "m_system": m.props.get("system"), "m_size": m.mep_size,
            "eta": p.eta, "action": p.action, "loss": p.loss, "demand": p.demand, "flags": ";".join(p.flags),
            "LPCI": p.C, "D_kN": p.D, "E_kN": p.E, "lam": metrics[c.s]["lam"], "rho": metrics[c.s]["rho"],
            "score": p.score, "sev_proposed": p.severity, "sev_local_only": lo.severity,
            "sev_geometry": baseline_geometry(c), "sev_category": baseline_category(c, s, m),
            "in_revit_reference": (c.s, c.m) in model.reference_pairs,
        })
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(out / "clashes.csv", index=False)
    pd.DataFrame.from_dict(metrics, orient="index").rename_axis("uid").to_csv(out / "members.csv")
    (out / "detection.json").write_text(json.dumps(agreement, indent=1, default=str))

    summary = {
        "case": case, "n_structural": len(model.structural), "n_mep": len(model.mep),
        "struct_kinds": Counter(e.kind for e in model.structural),
        "mep_kinds": Counter(e.kind for e in model.mep),
        "clash_kinds": Counter(c.kind for c in clashes),
        "severity_proposed": Counter(df["sev_proposed"]) if len(df) else {},
        "severity_local_only": Counter(df["sev_local_only"]) if len(df) else {},
        "severity_geometry": Counter(df["sev_geometry"]) if len(df) else {},
        "severity_category": Counter(df["sev_category"]) if len(df) else {},
        "timing_s": {"load": t_load, "broadphase_bruteforce": t_bf, "broadphase_rtree": t_rt,
                     **det.timing, "loadpath": t_lp, "severity": t_sev},
        "graph": {"nodes": lp.G.number_of_nodes(), "edges": lp.G.number_of_edges(),
                  "unsupported": len(lp.notes["unsupported"]),
                  "removed_cycle_edges": lp.notes["removed_cycle_edges"],
                  "total_factored_load_kN": lp.total_load},
        "params": vars(a),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: summary[k] for k in ("clash_kinds", "severity_proposed", "severity_geometry",
                                               "severity_category", "graph")}, indent=1, default=str))


if __name__ == "__main__":
    main()
