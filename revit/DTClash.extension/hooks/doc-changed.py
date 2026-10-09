"""pyRevit hook (DocumentChanged): push changed structural/MEP elements to the twin.
Active only while data/twin/ENABLED exists (toggle with the "Twin Sync" button)."""
from pyrevit import EXEC_PARAMS

from dtclash_revit import hook, twin_io

if twin_io.enabled():
    hook.handle(EXEC_PARAMS.event_args)
