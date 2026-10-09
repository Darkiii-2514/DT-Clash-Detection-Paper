"""DocumentChanged -> twin delta. Shared by the pyRevit hook and the batch experiments."""
from __future__ import print_function

import time

from Autodesk.Revit import DB

from dtclash_revit import extract, twin_io

STRUCT_NAMES = ("OST_StructuralColumns", "OST_StructuralFraming", "OST_StructuralFoundation",
                "OST_Floors", "OST_Walls")


def handle(args, tag=None):
    """Export added/modified structural+MEP elements and deleted ids of one transaction."""
    t0 = time.time()
    doc = args.GetDocument()
    tag = tag or extract.doc_tag(doc)
    wanted = set(str(b) for b in extract.STRUCT_BICS + extract.MEP_BICS)
    records = []
    for eid in list(args.GetAddedElementIds()) + list(args.GetModifiedElementIds()):
        e = doc.GetElement(eid)
        if e is None or e.Category is None or isinstance(e, DB.ElementType):
            continue
        bic = extract.bic_name(e)
        if bic not in wanted:
            continue
        if bic in STRUCT_NAMES:
            if not extract.is_structural(e, bic):
                continue
            role = "structural"
        else:
            role = "mep"
        try:
            rec, _ = extract.element_record(e, tag, DB.Transform.Identity, role)
        except Exception:
            continue
        if rec["mesh"]["f"]:
            records.append(rec)
    deleted = [extract.id_val(i) for i in args.GetDeletedElementIds()]
    if not (records or deleted):
        return None
    return twin_io.write_delta({
        "doc": tag,
        "t_revit": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "t_epoch": t0,
        "transaction": list(args.GetTransactionNames()),
        "records": records,
        "deleted_ids": deleted,
        "t_export_ms": (time.time() - t0) * 1000.0,
    })
