"""Generate the manuscript tables from results/ (no hand-copied numbers).

    .venv\\Scripts\\python paper\\tools\\make_tables.py
Writes paper/tables/table3.md, table4.md, table5.md (pandoc pipe tables with captions).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "paper" / "tables"
CASES = {"Snowdon_Towers_Sample_Structural": "Snowdon Towers",
         "BIM_Projekt_Golden_Nugget-Architektur_und_Ingenieurbau": "Golden Nugget"}
ORDER = {"Negligible": 0, "Minor": 1, "Major": 2, "Critical": 3}
METHODS = {"sev_proposed": "Proposed (load path-aware)", "sev_local_only": "Local impact only (ablation)",
           "sev_geometry": "Geometry only", "sev_category": "Category rules"}


def available():
    return [(k, v) for k, v in CASES.items() if (ROOT / "results" / k / "summary.json").exists()]


def short(tag):
    return tag.replace("BIM_Projekt_Golden_Nugget-", "").replace("Snowdon_Towers_Sample_", "").replace("_", " ")


def table3():
    rows = []
    for key, name in available():
        meta = json.loads((ROOT / "data" / "raw" / key / "meta.json").read_text())
        s = json.loads((ROOT / "results" / key / "summary.json").read_text())
        sk = s["struct_kinds"]
        links = "; ".join(f"{short(x['tag'])} ({x['n_mep']:,})" for x in meta["sources"] if x["n_mep"])
        rows.append(f"| {name} | {s['n_structural']:,} | {sk.get('beam', 0)} / {sk.get('column', 0)} / "
                    f"{sk.get('wall', 0)} / {sk.get('slab', 0)} / {sk.get('foundation', 0)} | {s['n_mep']:,} | {links} |")
    head = ("Table: Case-study models (Revit 2027 sample files). Structural members are taken from the host "
            "(structural) model; MEP elements from the host and its links. {#tbl:models}\n\n"
            "| Model | Structural members | Beams / columns / walls / slabs / foundations | MEP elements | MEP by source model |\n"
            "|---|---:|---|---:|---|\n")
    return head + "\n".join(rows) + "\n"


def table4():
    rows = []
    for key, name in available():
        d = ROOT / "results" / key
        s = json.loads((d / "summary.json").read_text())
        det = json.loads((d / "detection.json").read_text())
        meta = json.loads((ROOT / "data" / "raw" / key / "meta.json").read_text())
        ck = Counter(s["clash_kinds"])
        t = s["timing_s"]
        rows.append(f"| {name} | {t['n_candidates']:,} | {ck['hard']:,} | {ck['touch']:,} | {ck['clearance']:,} | "
                    f"{det['reference_pairs']:,} | {det['tp']:,} / {det['fp']:,} / {det['fn']:,} | "
                    f"{det['precision']:.3f} | {det['recall']:.3f} | {det['f1']:.3f} | "
                    f"{t['broadphase_rtree'] + t['narrowphase_s']:.1f} | {meta.get('t_reference_s', float('nan')):.0f} |")
    head = ("Table: Clash detection compared with Revit's ElementIntersectsSolidFilter. Physical clashes = hard + "
            "touch; TP/FP/FN are pairs agreed / found only by the framework / found only by Revit; times in seconds "
            "(framework: broad + narrow phase; Revit: reference filter). {#tbl:detection}\n\n"
            "| Model | Candidates | Hard | Touch | Clearance | Revit pairs | TP / FP / FN | Precision | Recall | F1 | "
            "Time, framework (s) | Time, Revit (s) |\n"
            "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|\n")
    return head + "\n".join(rows) + "\n"


def table5():
    rows = []
    for key, name in available():
        h = pd.read_csv(ROOT / "results" / key / "clashes.csv")
        h = h[h.kind == "hard"]
        ref = h.sev_proposed.map(ORDER)
        cm_ref = set(h.index[h.sev_proposed.isin(["Critical", "Major"])])
        for col, lab in METHODS.items():
            c = h[col].value_counts()
            cm = set(h.index[h[col].isin(["Critical", "Major"])])
            jac = len(cm & cm_ref) / len(cm | cm_ref) if cm | cm_ref else 1.0
            kap = cohen_kappa_score(ref, h[col].map(ORDER), weights="quadratic", labels=[0, 1, 2, 3])
            rows.append(f"| {name} | {lab} | {c.get('Critical', 0)} | {c.get('Major', 0)} | {c.get('Minor', 0)} | "
                        f"{c.get('Negligible', 0)} | {len(cm)} ({100 * len(cm) / len(h):.1f} %) | "
                        f"{'—' if col == 'sev_proposed' else f'{kap:.2f}'} | {'—' if col == 'sev_proposed' else f'{jac:.2f}'} |")
    head = ("Table: Severity of the hard clashes under the four classification methods. κ_w: quadratic-weighted "
            "Cohen's kappa with the proposed classes; Jaccard: overlap of the Critical+Major sets with the proposed "
            "one. {#tbl:severity}\n\n"
            "| Model | Method | Critical | Major | Minor | Negligible | Critical + Major | κ_w | Jaccard |\n"
            "|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
    return head + "\n".join(rows) + "\n"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, f in (("table3", table3), ("table4", table4), ("table5", table5)):
        (OUT / f"{name}.md").write_text(f(), encoding="utf-8")
        print("->", OUT / f"{name}.md")


if __name__ == "__main__":
    main()
