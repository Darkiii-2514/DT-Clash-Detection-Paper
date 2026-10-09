"""pyrevit run entry point: export one or more models for the clash framework.

    pyrevit run revit\\batch\\export_model.py "<model.rvt>" --revit=2027

Models are opened detached and closed WITHOUT saving (sample files are read-only).
Output: <project>/data/raw/<model-tag>/ (see dtclash_revit.extract).
"""
from __future__ import print_function

import os
import sys
import traceback

ROOT = os.environ.get("DTCLASH_ROOT") or os.path.join(
    os.path.expanduser("~"), "Documents", "DT-Clash-Detection-Paper")
sys.path.insert(0, os.path.join(ROOT, "revit", "DTClash.extension", "lib"))

from Autodesk.Revit import DB  # noqa: E402
from pyrevit import HOST_APP  # noqa: E402
from dtclash_revit import extract  # noqa: E402

LOG = os.path.join(ROOT, "data", "raw", "export_log.txt")


def log(msg):
    with open(LOG, "a") as f:
        f.write(str(msg) + "\n")
    print(msg)


def open_readonly(path):
    mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
    opts = DB.OpenOptions()
    opts.Audit = False
    if DB.BasicFileInfo.Extract(path).IsWorkshared:
        opts.DetachFromCentralOption = DB.DetachFromCentralOption.DetachAndPreserveWorksets
        opts.SetOpenWorksetsConfiguration(
            DB.WorksetConfiguration(DB.WorksetConfigurationOption.OpenAllWorksets))
    return HOST_APP.app.OpenDocumentFile(mp, opts)


for model in __models__:  # noqa: F821  (injected by pyrevit run)
    tag = os.path.splitext(os.path.basename(model))[0].replace(" ", "_")
    out_dir = os.path.join(ROOT, "data", "raw", tag)
    log("=== %s -> %s" % (model, out_dir))
    doc = None
    # an export with records but no meta.json was interrupted: keep its complete records
    resume = (os.path.exists(os.path.join(out_dir, "elements.jsonl"))
              and not os.path.exists(os.path.join(out_dir, "meta.json")))
    try:
        doc = open_readonly(model)
        extract.export(doc, out_dir, host_tag=tag, with_reference=True, log=log, resume=resume)
    except Exception:
        log(traceback.format_exc())
    finally:
        if doc is not None:
            doc.Close(False)
