"""Write the twin's latest results back into Revit (bidirectional link).

- colours every clashing structural member of this model in the active view by its
  worst clash severity;
- places a marker (DirectShape, Generic Model) at each clash point, with severity,
  eta, LPCI and the element ids in its Comments.
"""
from __future__ import print_function

from pyrevit import forms, revit, script

from dtclash_revit import extract, twin_io, writeback

doc, view = revit.doc, revit.active_view
res = twin_io.read_results()
if not res:
    forms.alert("No twin results yet (data/twin/outbox/latest.json).", exitscript=True)

with revit.Transaction("DT clash write-back"):
    n_members, n_markers = writeback.apply(doc, view, res, extract.doc_tag(doc))

out = script.get_output()
out.print_md("**Twin v{}**: coloured {} members, placed {} markers (Critical/Major).".format(
    res.get("version"), n_members, n_markers))
