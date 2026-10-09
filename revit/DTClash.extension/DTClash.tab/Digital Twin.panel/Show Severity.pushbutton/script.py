"""Write the twin's latest results back into Revit (bidirectional link).

- colours every clashing structural member of this model in the active view by its
  worst clash severity;
- places a marker (DirectShape, Generic Model) at each clash point, with severity,
  eta, LPCI and the element ids in its Comments.
"""
from __future__ import print_function

from System.Collections.Generic import List

from Autodesk.Revit import DB
from pyrevit import forms, revit, script

from dtclash_revit import extract, twin_io

COLORS = {"Critical": (220, 38, 38), "Major": (234, 88, 12), "Minor": (202, 138, 4),
          "Negligible": (100, 116, 139), "Coordination": (37, 99, 235)}
ORDER = ["Coordination", "Negligible", "Minor", "Major", "Critical"]
MARK = "DTClash"

doc, view = revit.doc, revit.active_view
res = twin_io.read_results()
if not res:
    forms.alert("No twin results yet (data/twin/outbox/latest.json).", exitscript=True)

tag = extract.doc_tag(doc)
FT = extract.FT
solid_fill = next((fp for fp in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement)
                   if fp.GetFillPattern().IsSolidFill), None)


def ogs_for(sev):
    r, g, b = COLORS[sev]
    o = DB.OverrideGraphicSettings()
    c = DB.Color(r, g, b)
    o.SetProjectionLineColor(c)
    if solid_fill is not None:
        o.SetSurfaceForegroundPatternId(solid_fill.Id)
        o.SetSurfaceForegroundPatternColor(c)
    return o


def cube(center_m, size_m):
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


worst = {}
for c in res["clashes"]:
    if c["s_doc"] == tag:
        cur = worst.get(c["s_id"])
        if cur is None or ORDER.index(c["severity"]) > ORDER.index(cur):
            worst[c["s_id"]] = c["severity"]

with revit.Transaction("DT clash write-back"):
    old = [ds.Id for ds in DB.FilteredElementCollector(doc).OfClass(DB.DirectShape)
           if (ds.Name or "").startswith(MARK)]
    if old:
        doc.Delete(List[DB.ElementId](old))
    for sid, sev in worst.items():
        e = doc.GetElement(DB.ElementId(sid))   # Int64 ctor in Revit 2024+
        if e is not None:
            view.SetElementOverrides(e.Id, ogs_for(sev))
    n = 0
    for c in res["clashes"]:
        if c["severity"] not in ("Critical", "Major") or c["s_doc"] != tag:
            continue
        ds = DB.DirectShape.CreateElement(doc, DB.ElementId(DB.BuiltInCategory.OST_GenericModel))
        geo = List[DB.GeometryObject]()
        geo.Add(cube(c["point"], 0.3 if c["severity"] == "Critical" else 0.2))
        ds.SetShape(geo)
        ds.SetName("%s %s" % (MARK, c["severity"]))
        p = ds.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p is not None:
            p.Set("%s | eta=%.3f LPCI=%.3f | %s:%s x %s:%s" % (
                c["severity"], c["eta"], c["LPCI"], c["s_doc"], c["s_id"], c["m_doc"], c["m_id"]))
        view.SetElementOverrides(ds.Id, ogs_for(c["severity"]))
        n += 1

out = script.get_output()
out.print_md("**Twin v{}**: coloured {} members, placed {} markers (Critical/Major).".format(
    res.get("version"), len(worst), n))
