"""Build the blinded expert-rating kit for severity validation.

    .venv\\Scripts\\python experiments\\make_survey.py [--n 40] [--seed 11]

Samples hard clashes from every analysed case, stratified so that the sample contains all
clashes the proposed method calls Critical/Major, clashes where the geometry-only baseline
disagrees, and a random draw of the rest. Writes
    survey/Severity_Rating_Form.xlsx   one row per clash: snapshot + facts, rating dropdowns
    survey/answer_key.csv              method labels per item (NOT for raters)
    survey/images/*.png
Raters see facts and images only - never any method's classification.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]

from dtclash.model import Model  # noqa: E402
from render import render_clash  # noqa: E402

CLASSES = ["Negligible", "Minor", "Major", "Critical"]


def load_cases():
    cases = []
    for d in sorted((ROOT / "results").iterdir()):
        f = d / "clashes.csv"
        raw = ROOT / "data" / "raw" / d.name
        if f.exists() and raw.exists():
            df = pd.read_csv(f)
            df = df[df.kind == "hard"].copy()
            df["case"] = d.name
            cases.append((d.name, raw, df))
    return cases


def sample(df, n, rng):
    df = df.reset_index(drop=True)
    picked = list(df.index[df.sev_proposed.isin(["Critical", "Major"])])
    disagree = list(df.index[(~df.index.isin(picked)) & df.sev_geometry.isin(["Critical", "Major"])])
    rest = list(df.index[~df.index.isin(picked) & ~df.index.isin(disagree)])
    rng.shuffle(disagree)
    rng.shuffle(rest)
    k_dis = max(0, min(len(disagree), (n - len(picked)) // 2))
    picked += disagree[:k_dis]
    picked += rest[: max(0, n - len(picked))]
    picked = picked[:n] if len(picked) > n else picked
    out = df.loc[picked].copy()
    return out.sample(frac=1, random_state=rng.randint(0, 10**6)).reset_index(drop=True)


def fmt_point(p):
    return json.loads(p) if isinstance(p, str) else p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = ROOT / "survey"
    (out / "images").mkdir(parents=True, exist_ok=True)

    cases = load_cases()
    per_case = max(1, a.n // max(1, len(cases)))
    items = []
    for name, raw, df in cases:
        model = Model(raw)
        smp = sample(df, per_case, rng)
        for _, r in smp.iterrows():
            items.append((name, model, r))
    rng.shuffle(items)

    wb = Workbook()
    ins = wb.active
    ins.title = "Instructions"
    text = [
        "Structural clash severity - expert rating form",
        "",
        "Each row is a real interference between a structural member and an MEP element found in a federated",
        "Revit model. Please rate how serious each clash is FOR THE STRUCTURE if the MEP element were installed",
        "as modelled (i.e. the structural member would have to be cut/penetrated, or the MEP rerouted).",
        "",
        "Negligible - no structural concern; resolvable by a routine sleeve or minor reroute.",
        "Minor      - small effect on capacity; acceptable with standard detailing or a simple check.",
        "Major      - significant capacity or detailing concern; needs an engineer's check / redesign of the opening.",
        "Critical   - unacceptable without structural redesign or rerouting; affects a key load path.",
        "",
        "Use the facts and the two views in each row. Confidence: 1 = guess ... 5 = certain.",
        "Please work independently and do not discuss items with other raters until all forms are returned.",
        "Rater ID, profession and years of experience go in the cells below.",
    ]
    for i, t in enumerate(text, 1):
        ins.cell(i, 1, t).font = Font(bold=(i == 1), size=12 if i == 1 else 10)
    ins.cell(len(text) + 2, 1, "Rater ID:").font = Font(bold=True)
    ins.cell(len(text) + 3, 1, "Profession / role:").font = Font(bold=True)
    ins.cell(len(text) + 4, 1, "Years of structural experience:").font = Font(bold=True)
    ins.column_dimensions["A"].width = 110

    ws = wb.create_sheet("Ratings")
    head = ["Item", "Snapshot", "Structural member", "MEP element", "Clash geometry", "Load context",
            "Rating", "Confidence (1-5)", "Comment"]
    ws.append(head)
    for col, w in zip("ABCDEFGHI", (7, 62, 34, 26, 36, 30, 14, 12, 30)):
        ws.column_dimensions[col].width = w
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2A78D6")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    dv = DataValidation(type="list", formula1='"' + ",".join(CLASSES) + '"', allow_blank=True)
    dv2 = DataValidation(type="whole", operator="between", formula1="1", formula2="5", allow_blank=True)
    ws.add_data_validation(dv)
    ws.add_data_validation(dv2)

    key = []
    for i, (case, model, r) in enumerate(items, 1):
        iid = f"C{i:02d}"
        img = out / "images" / f"{iid}.png"
        render_clash(model, r.s, r.m, fmt_point(r.point), img, title=f"{iid}")
        s, m = model.by_uid[r.s], model.by_uid[r.m]
        member = (f"{s.kind} | {s.family} : {s.type}\nmaterial: {r.s_material}\n"
                  f"length {r.s_length:.2f} m, section {r.s_width*1000:.0f} x {r.s_depth*1000:.0f} mm\nlevel: {s.level}")
        mep = f"{m.kind} | {m.family} : {m.type}\noutside size {r.m_size*1000:.0f} mm\nsystem: {r.m_system}"
        geo = (f"position along member: {r.xi:.2f} of length\n"
               f"overlap: {r.du*1000:.0f} (along) x {r.dv*1000:.0f} (width) x {r.dw*1000:.0f} (depth) mm\n"
               f"overlap volume: {r.overlap_volume*1e6:.0f} cm3\ncrossing angle: {r.crossing_angle:.0f} deg")
        ctx = (f"gravity load carried: {r.D_kN:.0f} kN\n(~{r.D_kN / max(1e-9, model_dref(case)):.1f} typical bays)\n"
               f"supports of member: {int(r.get('n_supports', 0)) if 'n_supports' in r else 'n/a'}")
        ws.append([iid, "", member, mep, geo, ctx, "", "", ""])
        row = ws.max_row
        ws.row_dimensions[row].height = 190
        for c in ws[row]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
        x = XLImage(str(img))
        x.width, x.height = 440, 220
        ws.add_image(x, f"B{row}")
        dv.add(f"G{row}")
        dv2.add(f"H{row}")
        key.append({"item": iid, "case": case, "s": r.s, "m": r.m, "eta": r.eta, "LPCI": r.LPCI,
                    "D_kN": r.D_kN, "sev_proposed": r.sev_proposed, "sev_local_only": r.sev_local_only,
                    "sev_geometry": r.sev_geometry, "sev_category": r.sev_category})
    ws.freeze_panes = "C2"
    wb.save(out / "Severity_Rating_Form.xlsx")
    pd.DataFrame(key).to_csv(out / "answer_key.csv", index=False)
    print(f"{len(items)} items -> {out / 'Severity_Rating_Form.xlsx'}")
    print(pd.DataFrame(key).groupby(["case", "sev_proposed"]).size())


_DREF = {}


def model_dref(case):
    """D_ref (median beam load) of a case, from its members table."""
    if case not in _DREF:
        mem = pd.read_csv(ROOT / "results" / case / "members.csv")
        b = mem[(mem.kind == "beam") & (mem.carried_kN > 0)].carried_kN
        _DREF[case] = float(b.median()) if len(b) else float(mem.carried_kN.median())
    return _DREF[case]


if __name__ == "__main__":
    main()
