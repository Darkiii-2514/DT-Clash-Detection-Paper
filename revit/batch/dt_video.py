"""pyrevit run entry point: record the digital-twin loop as frames for the demonstration video.

    (1) .venv\\Scripts\\python experiments\\twin_service.py data\\raw\\<model-tag>     (keep running)
    (2) set DTCLASH_BEAM=<element id>   (e.g. from data/processed/video_beam_candidates.csv)
        pyrevit run "<abs path>\\revit\\batch\\dt_video.py" "<abs path>\\revit\\models\\DTClash_results\\<model>.rvt" --revit=2027
    (3) .venv\\Scripts\\python experiments\\make_twin_video.py

Opens the results-model copy (never saved), frames the beam in the "DTClash - Clash severity"
view and runs: current state -> lower the beam by DTCLASH_DZ (default 150 mm) -> restore it.
Each change is one Revit transaction; DocumentChanged -> hook.handle() writes a delta, the twin
service publishes new results, which are written back to the view before a frame is exported.
Output: data/twin/video/frame_NN.png and steps.jsonl (timings and clash counts per step).
"""
from __future__ import print_function

import glob
import json
import os
import sys
import time
import traceback

ROOT = os.environ.get("DTCLASH_ROOT") or os.path.join(
    os.path.expanduser("~"), "Documents", "DT-Clash-Detection-Paper")
sys.path.insert(0, os.path.join(ROOT, "revit", "DTClash.extension", "lib"))

import System  # noqa: E402
from Autodesk.Revit import DB  # noqa: E402
from pyrevit import HOST_APP  # noqa: E402

from dtclash_revit import extract, hook, twin_io, writeback  # noqa: E402

FT = extract.FT
BEAM = int(os.environ.get("DTCLASH_BEAM", "0"))
DZ = float(os.environ.get("DTCLASH_DZ", "0.15"))
OUT = os.path.join(ROOT, "data", "twin", "video")
VIEW_NAME = "DTClash - Clash severity"
LATEST = os.path.join(twin_io.OUTBOX, "latest.json")


def log(rec):
    with open(os.path.join(OUT, "steps.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")


def version():
    try:
        with open(LATEST) as f:
            return json.load(f).get("version")
    except Exception:
        return None


def wait_new_version(v0, timeout=120.0):
    """Wait for the service's next vNNNN.json marker (checking existence does not lock
    latest.json, which the service replaces atomically), then read the results."""
    t0 = time.time()
    marker = os.path.join(twin_io.OUTBOX, "v%04d.json" % (int(v0) + 1))
    while time.time() - t0 < timeout:
        if os.path.exists(marker):
            for _ in range(50):
                try:
                    res = twin_io.read_results()
                    if res and res.get("version") != v0:
                        return res, (time.time() - t0) * 1000.0
                except Exception:
                    pass
                time.sleep(0.05)
        time.sleep(0.05)
    raise RuntimeError("twin service did not publish within %.0f s" % timeout)


def frame_view(doc, view, beam):
    """Zoom the severity view onto the beam: section box cut just below the slab it carries
    (so the beam and the ducts beneath it are visible from above), datums hidden, white background."""
    bb = beam.get_BoundingBox(None)
    pad_xy, below, top_cut = 5.0 / FT, 1.6 / FT, 0.01 / FT
    box = DB.BoundingBoxXYZ()
    box.Min = DB.XYZ(bb.Min.X - pad_xy, bb.Min.Y - pad_xy, bb.Min.Z - below)
    box.Max = DB.XYZ(bb.Max.X + pad_xy, bb.Max.Y + pad_xy, bb.Max.Z - top_cut)
    view.IsSectionBoxActive = True
    view.SetSectionBox(box)
    c = (bb.Min + bb.Max) * 0.5
    eye = c + DB.XYZ(-1.0, -1.3, 0.85).Normalize() * (40.0 / FT)
    fwd = (c - eye).Normalize()
    up = fwd.CrossProduct(DB.XYZ.BasisZ).CrossProduct(fwd).Normalize()
    view.SetOrientation(DB.ViewOrientation3D(eye, up, fwd))
    doc.Regenerate()
    crop_to(view, box, 1.0 / FT)
    for n in ("OST_Levels", "OST_Grids", "OST_SectionBox", "OST_Cameras", "OST_Elev", "OST_Sections",
              "OST_ReferenceLines", "OST_CLines", "OST_RvtLinks"):
        b = getattr(DB.BuiltInCategory, n, None)
        cat = DB.Category.GetCategory(doc, b) if b is not None else None
        if cat is not None and n != "OST_RvtLinks" and view.CanCategoryBeHidden(cat.Id):
            view.SetCategoryHidden(cat.Id, True)
    try:
        white = DB.Color(255, 255, 255)
        view.SetBackground(DB.ViewDisplayBackground.CreateGradient(white, white, white))
    except Exception:
        pass
    # non-clashing structure in neutral grey, so that only the severity colours stand out
    grey = DB.OverrideGraphicSettings()
    fill = writeback._solid_fill(doc)
    if fill is not None:
        grey.SetSurfaceForegroundPatternId(fill.Id)
        grey.SetSurfaceForegroundPatternColor(DB.Color(214, 214, 208))
    grey.SetProjectionLineColor(DB.Color(150, 150, 145))
    for n in ("OST_StructuralFraming", "OST_StructuralColumns", "OST_StructuralFoundation", "OST_Floors", "OST_Walls"):
        cat = DB.Category.GetCategory(doc, getattr(DB.BuiltInCategory, n))
        if cat is not None:
            view.SetCategoryOverrides(cat.Id, grey)
    see = DB.OverrideGraphicSettings()
    see.SetSurfaceTransparency(25)
    for n in writeback_mep_categories():
        cat = DB.Category.GetCategory(doc, n)
        if cat is not None:
            view.SetCategoryOverrides(cat.Id, see)


def crop_to(view, box, margin):
    """Crop the 3D view to the projection of `box` so image export fits the beam, not the model."""
    crop = view.CropBox
    inv = crop.Transform.Inverse
    pts = [inv.OfPoint(DB.XYZ(x, y, z)) for x in (box.Min.X, box.Max.X) for y in (box.Min.Y, box.Max.Y)
           for z in (box.Min.Z, box.Max.Z)]
    crop.Min = DB.XYZ(min(p.X for p in pts) - margin, min(p.Y for p in pts) - margin, crop.Min.Z)
    crop.Max = DB.XYZ(max(p.X for p in pts) + margin, max(p.Y for p in pts) + margin, crop.Max.Z)
    view.CropBoxActive = True
    view.CropBoxVisible = False
    view.CropBox = crop


def writeback_mep_categories():
    for n in ("OST_DuctCurves", "OST_DuctFitting", "OST_PipeCurves", "OST_PipeFitting", "OST_Conduit",
              "OST_CableTray", "OST_MechanicalEquipment"):
        b = getattr(DB.BuiltInCategory, n, None)
        if b is not None:
            yield b


def export(doc, view, idx):
    before = set(glob.glob(os.path.join(OUT, "_raw*.png")))
    o = DB.ImageExportOptions()
    o.ExportRange = DB.ExportRange.SetOfViews
    ids = System.Collections.Generic.List[DB.ElementId]()
    ids.Add(view.Id)
    o.SetViewsAndSheets(ids)
    o.FilePath = os.path.join(OUT, "_raw%02d" % idx)
    o.ZoomType = DB.ZoomFitType.FitToPage
    o.PixelSize = 2400
    o.FitDirection = DB.FitDirectionType.Horizontal
    o.ImageResolution = DB.ImageResolution.DPI_150
    o.ShadowViewsFileType = DB.ImageFileType.PNG
    o.HLRandWFViewsFileType = DB.ImageFileType.PNG
    doc.ExportImage(o)
    new = sorted(set(glob.glob(os.path.join(OUT, "_raw%02d*.png" % idx))) - before)
    dst = os.path.join(OUT, "frame_%02d.png" % idx)
    if os.path.exists(dst):
        os.remove(dst)
    os.rename(new[-1], dst)
    return dst


def shift_beam(beam, dz):
    """Raise/lower a framing member by dz metres. Sample framing is often pinned and its height is
    driven by the level offsets, which MoveElement leaves unchanged, so edit those directly."""
    if beam.Pinned:
        beam.Pinned = False          # in memory only: the model is closed without saving
    done = []
    for bip in (DB.BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION, DB.BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION):
        p = beam.get_Parameter(bip)
        if p is not None and not p.IsReadOnly:
            p.Set(p.AsDouble() + dz / FT)
            done.append(str(bip))
    if not done:
        DB.ElementTransformUtils.MoveElement(beam.Document, beam.Id, DB.XYZ(0, 0, dz / FT))
        done.append("MoveElement")
    return done


def level_name(e):
    p = e.get_Parameter(DB.BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM)
    return p.AsValueString() if p is not None else None


def beam_clashes(res, tag):
    return sorted(c["severity"] for c in res["clashes"]
                  if c["s_doc"] == tag and c["s_id"] == BEAM and c["kind"] == "hard")


def write_back(doc, view, res, tag):
    t = DB.Transaction(doc, "DTClash write-back")
    t.Start()
    n = writeback.apply(doc, view, res, tag)
    t.Commit()
    return n


if not os.path.isdir(OUT):
    os.makedirs(OUT)
for f in glob.glob(os.path.join(OUT, "*")):
    os.remove(f)

for model in __models__:  # noqa: F821
    app = HOST_APP.app
    doc = None
    written = []

    def on_changed(sender, args):
        try:
            if args.GetDocument().Title == doc.Title and "write-back" not in " ".join(args.GetTransactionNames()):
                name = hook.handle(args)
                if name:
                    written.append(name)
        except Exception:
            log({"hook_error": traceback.format_exc()})

    try:
        res0 = twin_io.read_results()
        if not res0:
            raise RuntimeError("start experiments/twin_service.py first (no data/twin/outbox/latest.json)")
        mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(model)
        doc = HOST_APP.app.OpenDocumentFile(mp, DB.OpenOptions())
        tag = extract.doc_tag(doc)
        beam = doc.GetElement(DB.ElementId(System.Int64(BEAM)))
        view = next(v for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D) if v.Name == VIEW_NAME)
        t = DB.Transaction(doc, "DTClash video view")
        t.Start()
        frame_view(doc, view, beam)
        t.Commit()
        write_back(doc, view, res0, tag)
        export(doc, view, 0)
        log({"step": 0, "label": "current design", "beam_hard": beam_clashes(res0, tag),
             "n_clashes": len(res0["clashes"]), "version": res0.get("version"),
             "beam": "%s : %s" % (beam.Symbol.Family.Name, beam.Name), "level": level_name(beam)})
        app.DocumentChanged += on_changed
        for step, (label, dz) in enumerate((("beam lowered by %d mm" % round(DZ * 1000), -DZ),
                                             ("beam restored", DZ)), 1):
            v0 = version()
            n0 = len(written)
            t0 = time.time()
            z_before = beam.get_BoundingBox(None).Min.Z * FT
            t = DB.Transaction(doc, "DT video: " + label)
            t.Start()
            how = shift_beam(beam, dz)
            t.Commit()
            z_after = beam.get_BoundingBox(None).Min.Z * FT
            tx_ms = (time.time() - t0) * 1000.0
            res, wait_ms = wait_new_version(v0)
            results_ms = (time.time() - t0) * 1000.0
            n_members, n_markers = write_back(doc, view, res, tag)
            export(doc, view, step)
            log({"step": step, "label": label, "tx_ms": tx_ms, "wait_ms": wait_ms,
                 "change_to_results_ms": results_ms,
                 "service_ms": res.get("service_ms"), "e2e_ms": res.get("e2e_ms"),
                 "deltas": written[n0:], "beam_hard": beam_clashes(res, tag), "how": how,
                 "beam_dz_m": round(z_after - z_before, 4),
                 "n_clashes": len(res["clashes"]), "version": res.get("version"),
                 "members_coloured": n_members, "markers": n_markers})
    except Exception:
        log({"fatal": traceback.format_exc()})
    finally:
        try:
            app.DocumentChanged -= on_changed
        except Exception:
            pass
        if doc is not None:
            doc.Close(False)
