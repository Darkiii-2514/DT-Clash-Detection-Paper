"""pyrevit run entry point: save a copy of a model with its clash severity written back.

    pyrevit run revit\\batch\\make_results_model.py "<model.rvt>" --revit=2027

Reads results/<model-tag>/clashes.csv (run experiments/run_case.py first), opens the model
detached, adds a 3D view "DTClash - Clash severity" (clashing members coloured by their worst
proposed severity, markers at Critical/Major clashes, MEP transparent, architectural detail
hidden), makes it the starting view and saves the copy as
    revit/models/DTClash_results/<original file name>.rvt
The original sample file is never saved. The copy keeps the original file name so that the
DTClash tools recognise its element uids; links are re-pointed to the original link files.
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

from dtclash_revit import writeback  # noqa: E402

OUT = os.path.join(ROOT, "revit", "models", "DTClash_results")
LOG = os.path.join(OUT, "build_log.txt")
VIEW_NAME = "DTClash - Clash severity"
HIDE = ("OST_Ceilings", "OST_Furniture", "OST_FurnitureSystems", "OST_Casework", "OST_Doors",
        "OST_Windows", "OST_CurtainWallPanels", "OST_CurtainWallMullions", "OST_StairsRailing",
        "OST_PlumbingFixtures", "OST_LightingFixtures", "OST_SpecialityEquipment", "OST_Planting",
        "OST_Entourage", "OST_GenericAnnotation", "OST_Rooms", "OST_Areas", "OST_Topography",
        "OST_Toposolid", "OST_Site", "OST_Parking", "OST_Roads")
MEP = ("OST_DuctCurves", "OST_DuctFitting", "OST_DuctAccessory", "OST_DuctTerminal", "OST_FlexDuctCurves",
       "OST_PipeCurves", "OST_PipeFitting", "OST_PipeAccessory", "OST_FlexPipeCurves", "OST_Conduit",
       "OST_ConduitFitting", "OST_CableTray", "OST_CableTrayFitting", "OST_MechanicalEquipment",
       "OST_ElectricalEquipment", "OST_ElectricalFixtures", "OST_Sprinklers")


def log(msg):
    with open(LOG, "a") as f:
        f.write(str(msg) + "\n")
    print(msg)


def open_detached(path):
    mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
    opts = DB.OpenOptions()
    opts.Audit = False
    if DB.BasicFileInfo.Extract(path).IsWorkshared:
        # a standalone (non-workshared) copy: no central file, no local-copy prompts
        opts.DetachFromCentralOption = DB.DetachFromCentralOption.DetachAndDiscardWorksets
        opts.SetOpenWorksetsConfiguration(
            DB.WorksetConfiguration(DB.WorksetConfigurationOption.OpenAllWorksets))
    return HOST_APP.app.OpenDocumentFile(mp, opts)


def categories(doc, names):
    for n in names:
        bic = getattr(DB.BuiltInCategory, n, None)
        cat = DB.Category.GetCategory(doc, bic) if bic is not None else None
        if cat is not None:
            yield cat


def make_view(doc):
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if v.Name == VIEW_NAME:
            doc.Delete(v.Id)
    vft = next(t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
               if t.ViewFamily == DB.ViewFamily.ThreeDimensional)
    view = DB.View3D.CreateIsometric(doc, vft.Id)
    view.ViewTemplateId = DB.ElementId.InvalidElementId
    view.Name = VIEW_NAME
    view.DisplayStyle = DB.DisplayStyle.Shading
    view.DetailLevel = DB.ViewDetailLevel.Fine
    for cat in categories(doc, HIDE):
        if view.CanCategoryBeHidden(cat.Id):
            view.SetCategoryHidden(cat.Id, True)
    see_through = DB.OverrideGraphicSettings()
    see_through.SetSurfaceTransparency(60)
    for cat in categories(doc, MEP):
        view.SetCategoryOverrides(cat.Id, see_through)
    return view


def link_paths(doc):
    """file name -> absolute path of every Revit link, as loaded from the original location."""
    out = {}
    for lt in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkType):
        efr = lt.GetExternalFileReference()
        p = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(efr.GetAbsolutePath())
        out[os.path.basename(p)] = p
        log("  link %s (%s)" % (p, efr.PathType))
    return out


def repoint_links(saved, abs_paths):
    """Make the saved copy's links absolute so they still resolve from the new folder."""
    mp = DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(saved)
    td = DB.TransmissionData.ReadTransmissionData(mp)
    if td is None:
        return 0
    n = 0
    for rid in td.GetAllExternalFileReferenceIds():
        ref = td.GetLastSavedReferenceData(rid)
        if ref.ExternalFileReferenceType != DB.ExternalFileReferenceType.RevitLink:
            continue
        name = os.path.basename(DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(ref.GetPath()))
        if name in abs_paths:
            td.SetDesiredReferenceData(rid, DB.ModelPathUtils.ConvertUserVisiblePathToModelPath(abs_paths[name]),
                                       DB.PathType.Absolute, True)
            n += 1
    td.IsTransmitted = False
    DB.TransmissionData.WriteTransmissionData(mp, td)
    return n


if not os.path.isdir(OUT):
    os.makedirs(OUT)

for model in __models__:  # noqa: F821  (injected by pyrevit run)
    name = os.path.basename(model)
    tag = os.path.splitext(name)[0].replace(" ", "_")
    src = os.path.join(ROOT, "results", tag, "clashes.csv")
    dst = os.path.join(OUT, name)
    log("=== %s -> %s" % (model, dst))
    doc = None
    links = {}
    try:
        res = writeback.results_from_csv(src)
        doc = open_detached(model)
        links = link_paths(doc)
        t = DB.Transaction(doc, "DTClash results model")
        t.Start()
        view = make_view(doc)
        n_members, n_markers = writeback.apply(doc, view, res, tag)
        DB.StartingViewSettings.GetStartingViewSettings(doc).ViewId = view.Id
        t.Commit()
        log("  %d clashes, coloured %d members, placed %d markers" % (len(res["clashes"]), n_members, n_markers))
        opts = DB.SaveAsOptions()
        opts.OverwriteExistingFile = True
        opts.MaximumBackups = 1
        doc.SaveAs(dst, opts)
        doc.Close(False)
        doc = None
        log("  saved; re-pointed %d links" % repoint_links(dst, links))
    except Exception:
        log(traceback.format_exc())
    finally:
        if doc is not None:
            doc.Close(False)
