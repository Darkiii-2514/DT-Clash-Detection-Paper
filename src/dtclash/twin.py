"""Digital-twin synchronisation layer.

The twin holds the current model state, its clash set and severities, and a versioned
history in SQLite. When the authoring model changes (a delta exported by the pyRevit
document-changed hook, or a fresh full export) the twin:

  1. diffs element fingerprints -> added / modified / deleted,
  2. drops clashes that involve changed or deleted elements,
  3. re-runs detection only for (changed structural x all MEP) U (all structural x changed MEP)
     using a persistent R-tree that is updated in place,
  4. rebuilds the load-path graph only if a structural element changed, and re-assesses
     every clash on members whose LPCI moved,
  5. records a new version, a delta report and per-step latency.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from rtree import index

from .clash import Clash, ClashDetector
from .loadpath import LoadPathGraph
from .model import Element, Model
from .severity import assess

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions(version INTEGER PRIMARY KEY, created REAL, source TEXT,
    n_added INT, n_modified INT, n_deleted INT, n_clashes INT, latency_ms REAL, report TEXT);
CREATE TABLE IF NOT EXISTS elements(uid TEXT PRIMARY KEY, fingerprint TEXT, role TEXT, kind TEXT,
    since_version INT);
CREATE TABLE IF NOT EXISTS clashes(version INT, s TEXT, m TEXT, kind TEXT, eta REAL, lpci REAL,
    score REAL, severity TEXT, point TEXT, PRIMARY KEY(version, s, m));
CREATE TABLE IF NOT EXISTS events(version INT, ts REAL, type TEXT, uid TEXT, detail TEXT);
"""


def fingerprint(e: Element) -> str:
    h = hashlib.sha1()
    h.update(np.round(e.verts, 4).astype(np.float32).tobytes())
    h.update(np.asarray(e.faces, np.int32).tobytes())
    h.update(json.dumps(e.props, sort_keys=True, default=str).encode())
    h.update((e.bic or "").encode())
    return h.hexdigest()


@dataclass
class Delta:
    added: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    deleted: list = field(default_factory=list)

    @property
    def empty(self):
        return not (self.added or self.modified or self.deleted)


class DigitalTwin:
    def __init__(self, model: Model, db_path: str | Path, clearance=0.025, alpha=0.5, beta=2.0):
        self.model = model
        self.clearance, self.alpha, self.beta = clearance, alpha, beta
        self.db = sqlite3.connect(str(db_path))
        self.db.executescript(SCHEMA)
        self.version = 0
        self.fps: dict[str, str] = {}
        self.clashes: dict[tuple[str, str], Clash] = {}
        self.assess: dict[tuple[str, str], object] = {}
        self.lp: LoadPathGraph | None = None
        self.detector = ClashDetector(model, clearance=clearance)
        self._mep_idx = None
        self._mep_slot: dict[str, int] = {}

    # ------------------------------------------------------------------ indexes
    def _rebuild_mep_index(self):
        p = index.Property()
        p.dimension = 3
        self._mep_idx = index.Index(properties=p, interleaved=True)
        self._mep_slot = {}
        self._next_slot = 0
        for e in self.model.mep:
            self._insert_mep(e)

    def _mep_box(self, e):
        return tuple(np.r_[e.bbox[:3] - self.clearance, e.bbox[3:] + self.clearance])

    def _insert_mep(self, e):
        slot = self._next_slot
        self._next_slot += 1
        self._mep_slot[e.uid] = slot
        self._mep_idx.insert(slot, self._mep_box(e), obj=e.uid)

    def _delete_mep(self, e):
        slot = self._mep_slot.pop(e.uid, None)
        if slot is not None:
            self._mep_idx.delete(slot, self._mep_box(e))

    # ------------------------------------------------------------------ full synchronisation
    def full_sync(self, source="initial"):
        t0 = time.perf_counter()
        self.fps = {e.uid: fingerprint(e) for e in self.model.elements}
        self._rebuild_mep_index()
        self.clashes = {(c.s, c.m): c for c in self.detector.run()}
        self.lp = LoadPathGraph(self.model, alpha=self.alpha)
        self.lp.run()
        self._reassess(list(self.clashes))
        ms = (time.perf_counter() - t0) * 1000
        self._commit(source, Delta(added=list(self.fps)), ms, {"mode": "full", "total_ms": ms})
        return ms

    # ------------------------------------------------------------------ deltas
    def diff(self, new_elements: list[Element]) -> Delta:
        new = {e.uid: e for e in new_elements}
        d = Delta()
        for uid, e in new.items():
            fp = fingerprint(e)
            if uid not in self.fps:
                d.added.append(uid)
            elif self.fps[uid] != fp:
                d.modified.append(uid)
        d.deleted = [u for u in self.fps if u not in new]
        return d

    def apply(self, new_elements: list[Element] | None = None, delta_records: list[Element] | None = None,
              deleted: list[str] | None = None, source="delta"):
        """Either pass the complete new element list, or only the changed records + deleted uids
        (what the Revit hook produces)."""
        timings = {}
        t0 = time.perf_counter()
        m = self.model
        if new_elements is not None:
            d = self.diff(new_elements)
            changed = {e.uid: e for e in new_elements if e.uid in set(d.added) | set(d.modified)}
        else:
            changed = {e.uid: e for e in (delta_records or [])}
            d = Delta(added=[u for u in changed if u not in self.fps],
                      modified=[u for u in changed if u in self.fps and self.fps[u] != fingerprint(changed[u])],
                      deleted=list(deleted or []))
            changed = {u: changed[u] for u in d.added + d.modified}
        timings["diff_ms"] = (time.perf_counter() - t0) * 1000
        if d.empty:
            return d, {"mode": "noop", **timings}

        # --- update model containers + MEP index
        t1 = time.perf_counter()
        gone = set(d.deleted) | set(d.modified)
        for uid in gone:
            old = m.by_uid.get(uid)
            if old is not None and old.role == "mep":
                self._delete_mep(old)
            self.detector.fcl.drop(uid)
        m.elements = [e for e in m.elements if e.uid not in gone] + list(changed.values())
        m.reindex()
        for e in changed.values():
            if e.role == "mep":
                self._insert_mep(e)
        for uid in d.deleted:
            self.fps.pop(uid, None)
        for uid, e in changed.items():
            self.fps[uid] = fingerprint(e)
        timings["update_ms"] = (time.perf_counter() - t1) * 1000

        # --- clash maintenance
        t2 = time.perf_counter()
        touched = gone | set(changed)
        before = dict(self.clashes)
        self.clashes = {k: c for k, c in self.clashes.items() if k[0] not in touched and k[1] not in touched}
        new_s = [e for e in changed.values() if e.role == "structural"]
        new_m = [e for e in changed.values() if e.role == "mep"]
        tested = 0
        for s in new_s:  # changed structural x all MEP (via index)
            for uid in self._mep_idx.intersection(tuple(s.bbox), objects="raw"):
                c = self.detector.narrow(s, m.by_uid[uid]); tested += 1
                if c:
                    self.clashes[(c.s, c.m)] = c
        if new_m:        # all structural x changed MEP
            from .clash import broadphase_rtree
            for i, j in broadphase_rtree(m.structural, new_m, self.clearance):
                if m.structural[i].uid in changed:
                    continue  # already tested above
                c = self.detector.narrow(m.structural[i], new_m[j]); tested += 1
                if c:
                    self.clashes[(c.s, c.m)] = c
        timings["clash_ms"] = (time.perf_counter() - t2) * 1000

        # --- load path + severity
        t3 = time.perf_counter()
        structural_changed = bool(new_s) or any(u in self.lp.elems for u in d.deleted)
        stale = set()
        if structural_changed:
            old_lpci = {u: v["LPCI"] for u, v in self.lp.metrics.items()}
            self.lp.update(changed=[e.uid for e in new_s],
                           deleted=[u for u in d.deleted if u in old_lpci])
            stale = {u for u, v in self.lp.metrics.items() if abs(v["LPCI"] - old_lpci.get(u, -1)) > 1e-9}
        timings["loadpath_ms"] = (time.perf_counter() - t3) * 1000
        t4 = time.perf_counter()
        if structural_changed:   # support sets (e.g. slab punching zones) may change even where LPCI does not
            redo = list(self.clashes)
        else:
            redo = [k for k in self.clashes if k not in before or k[0] in touched or k[1] in touched]
        for k in [k for k in self.assess if k not in self.clashes]:
            del self.assess[k]
        self._reassess(redo)
        timings["severity_ms"] = (time.perf_counter() - t4) * 1000

        ms = (time.perf_counter() - t0) * 1000
        report = {
            "mode": "incremental", "pairs_tested": tested, **timings, "total_ms": ms,
            "new_clashes": sorted(set(self.clashes) - set(before)),
            "resolved_clashes": sorted(set(before) - set(self.clashes)),
            "lpci_changed_members": len(stale),
        }
        self._commit(source, d, ms, report)
        return d, report

    # ------------------------------------------------------------------ helpers
    def _reassess(self, keys):
        keys = [k for k in keys if k in self.clashes]
        res = assess([self.clashes[k] for k in keys], self.model, self.lp, beta=self.beta)
        for k, a in zip(keys, res):
            self.assess[k] = a

    def _commit(self, source, d: Delta, ms, report):
        self.version += 1
        v = self.version
        cur = self.db.cursor()
        cur.execute("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?)",
                    (v, time.time(), source, len(d.added), len(d.modified), len(d.deleted),
                     len(self.clashes), ms, json.dumps(report, default=str)))
        for uid in d.added + d.modified:
            e = self.model.by_uid[uid]
            cur.execute("INSERT OR REPLACE INTO elements VALUES (?,?,?,?,?)",
                        (uid, self.fps[uid], e.role, e.kind, v))
        for uid in d.deleted:
            cur.execute("DELETE FROM elements WHERE uid=?", (uid,))
        for t, lst in (("added", d.added), ("modified", d.modified), ("deleted", d.deleted)):
            if source != "initial":
                cur.executemany("INSERT INTO events VALUES (?,?,?,?,?)",
                                [(v, time.time(), t, u, None) for u in lst])
        cur.executemany("INSERT INTO clashes VALUES (?,?,?,?,?,?,?,?,?)", [
            (v, k[0], k[1], c.kind, self.assess[k].eta, self.assess[k].C, self.assess[k].score,
             self.assess[k].severity, json.dumps(c.point)) for k, c in self.clashes.items()])
        self.db.commit()

    def snapshot(self):
        """Comparable state: {(s, m): (kind, severity, round(eta, 6))}."""
        return {k: (c.kind, self.assess[k].severity, round(self.assess[k].eta, 6))
                for k, c in self.clashes.items()}
