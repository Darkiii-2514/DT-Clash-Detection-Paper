"""Full export of the active model and its links, then switch the twin hook on."""
from __future__ import print_function

import os

from pyrevit import revit, script

from dtclash_revit import extract, twin_io

out = script.get_output()
doc = revit.doc
tag = extract.doc_tag(doc)
target = os.path.join(twin_io.ROOT, "data", "raw", tag)
meta = extract.export(doc, target, host_tag=tag, with_reference=True, log=out.print_md)
twin_io.set_enabled(True)
twin_io.write_delta({"doc": tag, "full_export": target})
out.print_md("**Exported** {} structural / {} MEP elements to `{}`; twin sync is ON."
             .format(meta["counts"]["structural"], meta["counts"]["mep"], target))
