"""Broad-phase scalability: tile a real model k times (k = 1, 2, 4, 8) side by side and time the
vectorised brute-force AABB test against the R-tree. Candidate sets are asserted identical.

    .venv\\Scripts\\python experiments\\scalability.py data\\raw\\<model>
Output: results/<case>/scalability.csv
"""
from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dtclash.clash import broadphase_bruteforce, broadphase_rtree  # noqa: E402
from dtclash.model import Model  # noqa: E402


class _Box:
    """Lightweight stand-in: the broad phase only reads .bbox."""
    __slots__ = ("bbox",)

    def __init__(self, bbox):
        self.bbox = bbox


def tile(elems, k, pitch):
    out = []
    for i in range(k):
        off = np.array([i * pitch, 0, 0, i * pitch, 0, 0], float)
        out += [_Box(e.bbox + off) for e in elems]
    return out


def timed(f, *a, reps=3):
    ts, res = [], None
    for _ in range(reps):
        t0 = time.perf_counter()
        res = f(*a)
        ts.append(time.perf_counter() - t0)
    return float(np.median(ts)), res


def main():
    model = Model(sys.argv[1])
    case = model.meta["host_tag"]
    span = float(max(e.bbox[3] for e in model.elements) - min(e.bbox[0] for e in model.elements))
    pitch = span + 50.0
    rows = []
    for k in (1, 2, 4, 8):
        S, M = tile(model.structural, k, pitch), tile(model.mep, k, pitch)
        t_bf, bf = timed(broadphase_bruteforce, S, M, 0.025, reps=1 if k >= 4 else 3)
        t_rt, rt = timed(broadphase_rtree, S, M, 0.025)
        assert set(bf) == set(rt)
        rows.append({"k": k, "n_struct": len(S), "n_mep": len(M), "pairs": len(S) * len(M),
                     "candidates": len(rt), "bruteforce_s": t_bf, "rtree_s": t_rt})
        print(rows[-1])
    out = ROOT / "results" / case / "scalability.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print("->", out)


if __name__ == "__main__":
    main()
