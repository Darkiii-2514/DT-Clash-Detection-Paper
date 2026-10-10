"""Write clash severity back into a Revit view (used by Show Severity and the batch results model).

- colours every clashing structural member of the document by its worst clash severity;
- places a marker (DirectShape, Generic Model) at each Critical/Major clash point, with
  severity, eta, LPCI and the element ids in its Comments.

`res` has the format of the twin service's data/twin/outbox/latest.json; results_from_csv()
builds the same structure from results/<case>/clashes.csv.
"""
from __future__ import print_function

import csv
import json

import System
from System.Collections.Generic import List

from Autodesk.Revit import DB

FT = 0.3048
COLORS = {"Critical": (220, 38, 38), "Major": (234, 88, 12), "Minor": (202, 138, 4),
          "Negligible": (100, 116, 139), "Coordination": (37, 99, 235)}
ORDER = ["Coordination", "Negligible", "Minor", "Major", "Critical"]
MARK = "DTClash"


def element_id(i):
    return DB.ElementId(System.Int64(int(i)))   # Int64 ctor (Revit 2024+)


def results_from_csv(path):
    """clashes.csv (proposed severity) -> the latest.json structure."""
    rows = []
    with open(path, "rb") as f:
        for r in csv.DictReader(f):
            rows.append({"s_doc": r["s_doc"], "s_id": int(float(r["s_id"])),
                         "m_doc": r["m_doc"], "m_id": int(float(r["m_id"])),
                         "kind": r["kind"], "severity": r["sev_proposed"],
                         "eta": float(r["eta"] or 0), "LPCI": float(r["LPCI"] or 0),
                         "score": float(r["score"] or 0), "point": json.loads(r["point"])})
    rows.sort(key=lambda c: -c["score"])
    return {"version": "results", "clashes": rows}


def _solid_fill(doc):
    return next((fp for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement)
                 if fp.GetFillPattern().IsSolidFill), None)


def _ogs(sev, solid_fill):
    r, g, b = COLORS[sev]
    o = DB.OverrideGraphicSettings()
    c = DB.Color(r, g, b)
    o.SetProjectionLineColor(c)
    if solid_fill is not None:
        o.SetSurfaceForegroundPatternId(solid_fill.Id)
        o.SetSurfaceForegroundPatternColor(c)
    return o


def _cube(center_m, size_m):
    h = size_m / FT / 2
    cx, cy, cz = (v / FT for v in center_m)
    p = [DB.XYZ(cx - h, cy - h, cz - h), DB.XYZ(cx + h, cy - h, cz - h),
         DB.XYZ(cx + h, cy + h, cz - h), DB.XYZ(cx - h, cy + h, cz - h)]
    loop = DB.CurveLoop()
    for i in range(4):
        loop.Append(DB.Line.CreateBound(p[i], p[(i + 1) % 4]))
    loops = List[DB.CurveLoop]()
    loops.Add(loop)
    return DB.GeometryCreationUtilities.CreateExtrusionGeometry(loops, DB.XYZ.BasisZ, 2 * h)


def apply(doc, view, res, tag):
    """Colour members and place markers in `view`. Call inside an open transaction.
    Returns (members coloured, markers placed)."""
    solid_fill = _solid_fill(doc)
    worst = {}
    for c in res["clashes"]:
        if c["s_doc"] == tag:
            cur = worst.get(c["s_id"])
            if cur is None or ORDER.index(c["severity"]) > ORDER.index(cur):
                worst[c["s_id"]] = c["severity"]
    old = [ds.Id for ds in DB.FilteredElementCollector(doc).OfClass(DB.DirectShape)
           if (ds.Name or "").startswith(MARK)]
    if old:
        doc.Delete(List[DB.ElementId](old))
    n_members = 0
    for sid, sev in worst.items():
        e = doc.GetElement(element_id(sid))
        if e is not None:
            view.SetElementOverrides(e.Id, _ogs(sev, solid_fill))
            n_members += 1
    n_markers = 0
    for c in res["clashes"]:
        if c["severity"] not in ("Critical", "Major") or c["s_doc"] != tag:
            continue
        ds = DB.DirectShape.CreateElement(doc, DB.ElementId(DB.BuiltInCategory.OST_GenericModel))
        geo = List[DB.GeometryObject]()
        geo.Add(_cube(c["point"], 0.3 if c["severity"] == "Critical" else 0.2))
        ds.SetShape(geo)
        ds.SetName("%s %s" % (MARK, c["severity"]))
        p = ds.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p is not None:
            p.Set("%s | eta=%.3f LPCI=%.3f | %s:%s x %s:%s" % (
                c["severity"], c["eta"], c["LPCI"], c["s_doc"], c["s_id"], c["m_doc"], c["m_id"]))
        view.SetElementOverrides(ds.Id, _ogs(c["severity"], solid_fill))
        n_markers += 1
    return n_members, n_markers
