"""File-based exchange between Revit (pyRevit) and the Python digital-twin service.

    data/twin/ENABLED            presence switches the document-changed hook on
    data/twin/inbox/*.json       deltas written by Revit  (records + deleted ids)
    data/twin/outbox/latest.json results written by the twin service
"""
from __future__ import print_function

import json
import os
import time

ROOT = os.environ.get("DTCLASH_ROOT") or os.path.join(
    os.path.expanduser("~"), "Documents", "DT-Clash-Detection-Paper")
TWIN = os.path.join(ROOT, "data", "twin")
INBOX = os.path.join(TWIN, "inbox")
OUTBOX = os.path.join(TWIN, "outbox")
FLAG = os.path.join(TWIN, "ENABLED")


def ensure_dirs():
    for d in (INBOX, OUTBOX):
        if not os.path.isdir(d):
            os.makedirs(d)


def enabled():
    return os.path.exists(FLAG)


def set_enabled(on):
    ensure_dirs()
    if on:
        open(FLAG, "w").close()
    elif os.path.exists(FLAG):
        os.remove(FLAG)


_SEQ = [0]


def write_delta(payload):
    """Atomically drop a delta into the inbox (write tmp, then rename)."""
    from dtclash_revit.extract import dumps   # non-ASCII-safe under IronPython 2.7
    ensure_dirs()
    _SEQ[0] += 1
    name = "delta_%d_%06d.json" % (int(time.time() * 1000), _SEQ[0])
    tmp = os.path.join(INBOX, name + ".tmp")
    with open(tmp, "w") as f:
        f.write(dumps(payload))
    os.rename(tmp, os.path.join(INBOX, name))
    return name


def read_results():
    p = os.path.join(OUTBOX, "latest.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)
