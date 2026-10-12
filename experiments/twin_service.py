"""Digital-twin service: keeps the twin in sync with Revit through the file inbox.

    .venv\\Scripts\\python experiments\\twin_service.py data\\raw\\<model-tag> [--once]

Revit (pyRevit hook) -> data/twin/inbox/delta_*.json -> this service (incremental update)
-> data/twin/outbox/latest.json -> Revit "Show Severity" button.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dtclash.model import Model, element_from_record  # noqa: E402
from dtclash.twin import DigitalTwin  # noqa: E402

TWIN = ROOT / "data" / "twin"
INBOX, OUTBOX, DONE = TWIN / "inbox", TWIN / "outbox", TWIN / "inbox" / "processed"


def publish(tw: DigitalTwin, extra: dict):
    m = tw.model
    rows = []
    for (s, mm), c in tw.clashes.items():
        a = tw.assess[(s, mm)]
        es, em = m.by_uid[s], m.by_uid[mm]
        rows.append({"s": s, "m": mm, "s_doc": es.doc, "s_id": es.id, "m_doc": em.doc, "m_id": em.id,
                     "s_kind": es.kind, "m_kind": em.kind, "kind": c.kind, "severity": a.severity,
                     "eta": a.eta, "LPCI": a.C, "score": a.score, "point": c.point})
    rows.sort(key=lambda r: -r["score"])
    payload = {"version": tw.version, "host_tag": m.meta.get("host_tag"), "t_published": time.time(),
               "clashes": rows, **extra}
    OUTBOX.mkdir(parents=True, exist_ok=True)
    tmp = OUTBOX / "latest.json.tmp"
    tmp.write_text(json.dumps(payload, default=str))
    for attempt in range(100):      # Windows refuses the rename while a reader (Revit) has the file open
        try:
            tmp.replace(OUTBOX / "latest.json")
            break
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.02)
    (OUTBOX / f"v{tw.version:04d}.json").write_text(json.dumps({k: v for k, v in payload.items() if k != "clashes"}
                                                                | {"n_clashes": len(rows)}, default=str))


def handle(tw: DigitalTwin, f: Path, log):
    d = json.loads(f.read_text())
    t_recv = time.time()
    if "full_export" in d:
        new = Model(d["full_export"])
        delta, rep = tw.apply(new_elements=new.elements, source=f.name)
    else:
        recs = [e for e in (element_from_record(r) for r in d.get("records", [])) if e is not None]
        doc = d["doc"].replace(" ", "_")
        dele = [tw.model.by_docid[(doc, i)] for i in d.get("deleted_ids", []) if (doc, i) in tw.model.by_docid]
        delta, rep = tw.apply(delta_records=recs, deleted=dele, source=f.name)
    extra = {"source": f.name, "report": rep, "t_revit_export_ms": d.get("t_export_ms"),
             "e2e_ms": (time.time() - d["t_epoch"]) * 1000 if "t_epoch" in d else None,
             "service_ms": (time.time() - t_recv) * 1000}
    publish(tw, extra)
    log.write(json.dumps({"file": f.name, "added": len(delta.added), "modified": len(delta.modified),
                          "deleted": len(delta.deleted), **{k: v for k, v in extra.items() if k != "report"},
                          **{k: v for k, v in rep.items() if k.endswith("_ms") or k in ("mode", "pairs_tested")}},
                         default=str) + "\n")
    log.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--poll", type=float, default=0.25)
    ap.add_argument("--once", action="store_true", help="process the current inbox and exit")
    a = ap.parse_args()
    for d in (INBOX, OUTBOX, DONE):
        d.mkdir(parents=True, exist_ok=True)
    model = Model(a.base)
    tw = DigitalTwin(model, TWIN / "twin.db")
    ms = tw.full_sync()
    publish(tw, {"source": "initial", "service_ms": ms})
    print(f"{model} -> twin v{tw.version}, {len(tw.clashes)} clashes ({ms/1000:.1f} s)")
    with open(TWIN / "service_log.jsonl", "a") as log:
        while True:
            files = sorted(INBOX.glob("delta_*.json"))
            for f in files:
                handle(tw, f, log)
                shutil.move(str(f), DONE / f.name)
                print(f"v{tw.version}: {f.name}")
            if a.once:
                break
            time.sleep(a.poll)


if __name__ == "__main__":
    main()
