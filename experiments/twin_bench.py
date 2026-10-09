"""Digital-twin latency benchmark on a real exported model.

    .venv\\Scripts\\python experiments\\twin_bench.py data\\raw\\<model> [--per-type 20] [--check-every 10]

A seeded stream of design changes is applied one at a time through DigitalTwin.apply().
Every `check-every` events the incremental state is compared with a full recompute of the
same model state (correctness), and the full-recompute time is recorded (speed-up).
Outputs: results/<case>/twin_bench.csv, twin_bench_summary.json
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dtclash.edits import duplicate, scale_section, translate  # noqa: E402
from dtclash.model import Model  # noqa: E402
from dtclash.twin import DigitalTwin  # noqa: E402

TYPES = ["mep_move", "mep_resize", "mep_delete", "mep_add", "struct_move", "struct_delete"]


def pick_mep(tw, rng):
    """Half the time an MEP element that currently clashes, otherwise any linear run."""
    clashing = sorted({k[1] for k in tw.clashes})
    runs = [e.uid for e in tw.model.mep if e.is_linear]
    pool = clashing if (clashing and rng.random() < 0.5) else runs
    return tw.model.by_uid[rng.choice(pool)]


def pick_beam(tw, rng):
    clashing = sorted({k[0] for k in tw.clashes if tw.model.by_uid[k[0]].kind == "beam"})
    beams = [e.uid for e in tw.model.structural if e.kind == "beam"]
    pool = clashing if (clashing and rng.random() < 0.5) else beams
    return tw.model.by_uid[rng.choice(pool)]


def make_event(kind, tw, rng, k):
    if kind == "mep_move":
        e = pick_mep(tw, rng)
        return dict(delta_records=[translate(e, (0, 0, rng.choice([-1, 1]) * rng.uniform(0.1, 0.3)))]), e.uid
    if kind == "mep_resize":
        e = pick_mep(tw, rng)
        return dict(delta_records=[scale_section(e, 1.5)]), e.uid
    if kind == "mep_delete":
        e = pick_mep(tw, rng)
        return dict(delta_records=[], deleted=[e.uid]), e.uid
    if kind == "mep_add":
        e = pick_mep(tw, rng)
        return dict(delta_records=[duplicate(e, (rng.uniform(-1, 1), rng.uniform(-1, 1), 0), f"{e.doc}:bench-{k}")]), e.uid
    if kind == "struct_move":
        e = pick_beam(tw, rng)
        return dict(delta_records=[translate(e, (0, 0, -0.15))]), e.uid
    if kind == "struct_delete":
        e = pick_beam(tw, rng)
        return dict(delta_records=[], deleted=[e.uid]), e.uid
    raise ValueError(kind)


def full_state_snapshot(model_state):
    m = copy.copy(model_state)
    m.elements = list(model_state.elements)
    m.reindex()
    with tempfile.TemporaryDirectory() as td:
        t0 = time.perf_counter()
        tw = DigitalTwin(m, Path(td) / "full.db")
        tw.full_sync()
        ms = (time.perf_counter() - t0) * 1000
        snap = tw.snapshot()
        tw.db.close()
    return snap, ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("--per-type", type=int, default=20)
    ap.add_argument("--check-every", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    model = Model(a.export_dir)
    case = model.meta["host_tag"]
    out = ROOT / "results" / case
    out.mkdir(parents=True, exist_ok=True)
    db = out / "twin_bench.db"
    db.unlink(missing_ok=True)
    tw = DigitalTwin(model, db)
    t_full0 = tw.full_sync()
    print(f"{model}: initial full sync {t_full0/1000:.1f} s, {len(tw.clashes)} clashes")

    events = [t for t in TYPES for _ in range(a.per_type)]
    rng.shuffle(events)
    rows, checks = [], []
    for k, kind in enumerate(events, 1):
        kwargs, target = make_event(kind, tw, rng, k)
        n_before = len(tw.clashes)
        d, rep = tw.apply(**kwargs, source=f"bench-{k}")
        rows.append({"event": k, "type": kind, "target": target, "mode": rep.get("mode"),
                     "n_clashes_before": n_before, "n_clashes_after": len(tw.clashes),
                     "new": len(rep.get("new_clashes", [])), "resolved": len(rep.get("resolved_clashes", [])),
                     **{x: rep.get(x) for x in ("pairs_tested", "diff_ms", "update_ms", "clash_ms",
                                                 "loadpath_ms", "severity_ms", "total_ms", "lpci_changed_members")}})
        if k % a.check_every == 0:
            snap_full, ms_full = full_state_snapshot(tw.model)
            same = snap_full == tw.snapshot()
            checks.append({"event": k, "identical": same, "full_ms": ms_full, "n_clashes": len(snap_full)})
            print(f"  [{k:>3}] check identical={same}  full={ms_full/1000:.1f} s")
            if not same:
                a_, b_ = tw.snapshot(), snap_full
                diff = {kk: (a_.get(kk), b_.get(kk)) for kk in set(a_) | set(b_) if a_.get(kk) != b_.get(kk)}
                print("     differences:", list(diff.items())[:5])
    df = pd.DataFrame(rows)
    df.to_csv(out / "twin_bench.csv", index=False)
    ck = pd.DataFrame(checks)
    ck.to_csv(out / "twin_bench_checks.csv", index=False)
    summ = {
        "case": case, "initial_full_sync_ms": t_full0, "n_events": len(df),
        "latency_ms_by_type": df.groupby("type")["total_ms"].describe(percentiles=[.5, .95]).round(1).to_dict(orient="index"),
        "latency_ms_all": df["total_ms"].describe(percentiles=[.5, .95]).round(1).to_dict(),
        "full_recompute_ms_mean": float(ck["full_ms"].mean()) if len(ck) else None,
        "checks_identical": f"{int(ck['identical'].sum())}/{len(ck)}" if len(ck) else None,
        "speedup_median": float(ck["full_ms"].mean() / df["total_ms"].median()) if len(ck) else None,
    }
    (out / "twin_bench_summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps({k: summ[k] for k in ("latency_ms_all", "full_recompute_ms_mean", "checks_identical", "speedup_median")}, indent=1, default=str))
    print(df.groupby("type")["total_ms"].median().round(1).to_dict())


if __name__ == "__main__":
    main()
