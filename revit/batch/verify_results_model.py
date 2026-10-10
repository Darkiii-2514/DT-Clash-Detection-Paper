"""pyrevit run entry point: open saved DTClash results models (without saving) and report what they contain.

    pyrevit run revit\batch\verify_results_model.py "revit\models\DTClash_results\<model>.rvt" --revit=2027

Output: revit/models/DTClash_results/verify_log.txt
"""
from __future__ import print_function

import os

from Autodesk.Revit import DB
from pyrevit import HOST_APP

LOG = os.path.join(os.path.expanduser("~"), "Documents", "DT-Clash-Detection-Paper", "revit", "models",
                   "DTClash_results", "verify_log.txt")


def log(msg):
    with open(LOG, "a") as f:
        f.write(str(msg) + "\n")


for model in __models__:  # noqa: F821
    log("=== " + model)
    mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(model)
    doc = HOST_APP.app.OpenDocumentFile(mp, DB.OpenOptions())
    try:
        log("  workshared: %s" % doc.IsWorkshared)
        sv = doc.GetElement(DB.StartingViewSettings.GetStartingViewSettings(doc).ViewId)
        log("  starting view: %s" % (sv.Name if sv is not None else None))
        marks = [d for d in DB.FilteredElementCollector(doc).OfClass(DB.DirectShape)
                 if (d.Name or "").startswith("DTClash")]
        log("  markers: %d (%s)" % (len(marks), ", ".join(sorted(set(d.Name for d in marks)))))
        if sv is not None:
            log("  members with overrides in view: %d" % sum(
                1 for e in DB.FilteredElementCollector(doc, sv.Id).WhereElementIsNotElementType()
                if sv.GetElementOverrides(e.Id).SurfaceForegroundPatternColor.IsValid))
        for lt in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType):
            efr = lt.GetExternalFileReference()
            log("  link %s | %s | %s" % (DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(efr.GetAbsolutePath()),
                                         efr.PathType, efr.GetLinkedFileStatus()))
    finally:
        doc.Close(False)
