"""Choose beams for the digital-twin demonstration video by dry-running the change in the twin.

    .venv\\Scripts\\python experiments\\pick_video_beam.py data\\raw\\Snowdon_Towers_Sample_Structural [--k 12]

Candidates are beams with a clearance clash to a duct or pipe that runs just beneath them, so
lowering the beam by 150 mm turns the near miss into a hard clash. Each candidate is lowered in
the twin, the new clashes and their proposed severity are recorded, and the beam is restored.
Output: data/processed/video_beam_candidates.csv (best first).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dtclash.edits import translate  # noqa: E402
from dtclash.model import Model  # noqa: E402
from dtclash.twin import DigitalTwin  # noqa: E402

ORDER = {"Coordination": -1, "Negligible": 0, "Minor": 1, "Major": 2, "Critical": 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--dz", type=float, default=-0.15)
    a = ap.parse_args()
    base = Path(a.base)
    h = pd.read_csv(ROOT / "results" / base.name / "clashes.csv")
    c = h[(h.kind == "clearance") & (h.s_kind == "beam") & h.m_kind.isin(["duct", "pipe"])].copy()
    c = c.sort_values(["D_kN", "m_size"], ascending=False).drop_duplicates("s").head(a.k)

    tw = DigitalTwin(Model(base), Path(tempfile.mkdtemp()) / "pick.db")
    tw.full_sync()
    rows = []
    for r in c.itertuples():
        e = tw.model.by_uid[r.s]
        before = set(tw.clashes)
        _, rep = tw.apply(delta_records=[translate(e, (0, 0, a.dz))], source="pick")
        new = [k for k in tw.clashes if k not in before and k[0] == r.s and tw.clashes[k].kind == "hard"]
        sev = sorted((tw.assess[k].severity for k in new), key=ORDER.get, reverse=True)
        rows.append({"beam": r.s, "beam_id": int(e.id), "family": e.family, "type": e.type, "level": e.level,
                     "carried_kN": round(r.D_kN, 1), "n_new_hard": len(new), "worst": sev[0] if sev else None,
                     "new_severities": ";".join(sev), "update_ms": round(rep.get("total_ms", float("nan")), 1)})
        tw.apply(delta_records=[e], source="restore")       # put the original element back
        print(rows[-1])
    out = pd.DataFrame(rows)
    out["rank"] = out.worst.map(ORDER).fillna(-2)
    out = out.sort_values(["rank", "n_new_hard", "carried_kN"], ascending=False).drop(columns="rank")
    dst = ROOT / "data" / "processed" / "video_beam_candidates.csv"
    out.to_csv(dst, index=False)
    print("->", dst)


if __name__ == "__main__":
    main()
