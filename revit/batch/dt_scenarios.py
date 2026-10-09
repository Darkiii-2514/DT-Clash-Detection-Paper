"""Scripted design changes in Revit to measure the digital-twin loop (pyrevit run).

For each change: one Revit transaction -> DocumentChanged -> hook.handle() writes a delta
-> the twin service (running separately) updates and publishes. The script pauses after
each change so the service can process it; the model is closed WITHOUT saving.

Scenario set depends on what the opened model contains:
  structural host : move beam down 150 mm | change beam to a deeper type | delete beam
  MEP host        : move pipe/duct up 200 mm | enlarge pipe diameter x1.5 | delete pipe
"""
from __future__ import print_function

import json
import os
import random
import sys
import time
import traceback

ROOT = os.environ.get("DTCLASH_ROOT") or os.path.join(
    os.path.expanduser("~"), "Documents", "DT-Clash-Detection-Paper")
sys.path.insert(0, os.path.join(ROOT, "revit", "DTClash.extension", "lib"))

from Autodesk.Revit import DB  # noqa: E402
from pyrevit import HOST_APP  # noqa: E402
from dtclash_revit import extract, hook  # noqa: E402

N_PER_SCENARIO = int(os.environ.get("DTCLASH_N", "15"))
PAUSE_S = float(os.environ.get("DTCLASH_PAUSE", "4"))
LOG = os.path.join(ROOT, "data", "twin", "scenario_log.jsonl")
FT = extract.FT
rng = random.Random(42)


def log(rec):
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def run_tx(doc, name, fn):
    t0 = time.time()
    t = DB.Transaction(doc, name)
    t.Start()
    try:
        fn()
        t.Commit()
        ok = True
    except Exception as ex:
        t.RollBack()
        ok = False
        log({"scenario": name, "error": str(ex)})
    return ok, (time.time() - t0) * 1000.0


def deeper_type(doc, beam):
    """Another framing type of the same family with a larger section height, if any."""
    cur = doc.GetElement(beam.GetTypeId())
    fam = cur.Family
    best, best_h = None, extract.lookup_double(beam, ["h", "d", "Height", "Depth"]) or 0
    for tid in fam.GetFamilySymbolIds():
        t = doc.GetElement(tid)
        h = None
        for n in ("h", "d", "Height", "Depth"):
            p = t.LookupParameter(n)
            if p is not None and p.HasValue and p.StorageType == DB.StorageType.Double:
                h = p.AsDouble() * FT
                break
        if h is not None and h > best_h + 0.05 and (best is None or h < best[1]):
            best = (t, h)
    return best[0] if best else None


def structural_scenarios(doc):
    beams = [b for b in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
             .WhereElementIsNotElementType().ToElements() if isinstance(b.Location, DB.LocationCurve)]
    rng.shuffle(beams)
    picks = beams[:3 * N_PER_SCENARIO]
    for b in picks[:N_PER_SCENARIO]:
        yield "move_beam_down_150mm", b.Id, lambda b=b: DB.ElementTransformUtils.MoveElement(
            doc, b.Id, DB.XYZ(0, 0, -0.15 / FT))
    for b in picks[N_PER_SCENARIO:2 * N_PER_SCENARIO]:
        t = deeper_type(doc, b)
        if t is not None:
            yield "deeper_beam_type", b.Id, lambda b=b, t=t: setattr(b, "Symbol", t)
    for b in picks[2 * N_PER_SCENARIO:]:
        yield "delete_beam", b.Id, lambda b=b: doc.Delete(b.Id)


def mep_scenarios(doc):
    pipes = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_PipeCurves)
                 .WhereElementIsNotElementType().ToElements())
    ducts = list(DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_DuctCurves)
                 .WhereElementIsNotElementType().ToElements())
    runs = pipes + ducts
    rng.shuffle(runs)
    rng.shuffle(pipes)
    for e in runs[:N_PER_SCENARIO]:
        yield "move_run_up_200mm", e.Id, lambda e=e: DB.ElementTransformUtils.MoveElement(
            doc, e.Id, DB.XYZ(0, 0, 0.2 / FT))
    for e in pipes[:N_PER_SCENARIO]:
        def grow(e=e):
            p = e.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
            p.Set(p.AsDouble() * 1.5)
        yield "enlarge_pipe_x1.5", e.Id, grow
    for e in pipes[N_PER_SCENARIO:2 * N_PER_SCENARIO]:
        yield "delete_pipe", e.Id, lambda e=e: doc.Delete(e.Id)


def open_doc(path):
    mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
    opts = DB.OpenOptions()
    opts.Audit = False
    return HOST_APP.app.OpenDocumentFile(mp, opts)


for model in __models__:  # noqa: F821
    doc = None
    app = HOST_APP.app
    written = []

    def on_changed(sender, args):
        try:
            name = hook.handle(args)
            if name:
                written.append(name)
        except Exception:
            log({"hook_error": traceback.format_exc()})

    try:
        doc = open_doc(model)
        tag = extract.doc_tag(doc)
        n_beams = DB.FilteredElementCollector(doc).OfCategory(
            DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType().GetElementCount()
        scen = structural_scenarios(doc) if n_beams else mep_scenarios(doc)
        app.DocumentChanged += on_changed
        for name, eid, fn in scen:
            before = len(written)
            ok, tx_ms = run_tx(doc, "DT " + name, fn)
            log({"model": tag, "scenario": name, "element_id": extract.id_val(eid), "ok": ok,
                 "tx_ms": tx_ms, "delta": written[before:] if len(written) > before else None,
                 "t_epoch": time.time()})
            time.sleep(PAUSE_S)
    except Exception:
        log({"fatal": traceback.format_exc()})
    finally:
        try:
            app.DocumentChanged -= on_changed
        except Exception:
            pass
        if doc is not None:
            doc.Close(False)
