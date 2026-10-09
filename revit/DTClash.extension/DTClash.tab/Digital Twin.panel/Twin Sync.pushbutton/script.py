"""Toggle live synchronisation (the document-changed hook) on or off."""
from pyrevit import forms

from dtclash_revit import twin_io

on = not twin_io.enabled()
twin_io.set_enabled(on)
forms.alert("Digital-twin sync is now {}.".format("ON" if on else "OFF"), title="DT Clash")
