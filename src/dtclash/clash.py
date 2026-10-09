"""Structural-vs-MEP clash detection.

Broad phase : axis-aligned boxes (inflated by the clearance tolerance) indexed in an
              R-tree; a vectorised brute-force variant is kept as the baseline.
Narrow phase: exact mesh-mesh collision / distance with FCL, then the intersection
              solid (manifold boolean, sampling fallback) for volume, centroid and
              the clash extents in the structural member's local frame.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict, field

import fcl
import numpy as np
import trimesh
from rtree import index

from .model import Element, Model

VOL_EPS = 1e-6        # m^3 (1 cm^3): below this an intersection is a touch, not a hard clash


@dataclass
class Clash:
    s: str                      # structural element uid
    m: str                      # MEP element uid
    kind: str                   # "hard" | "touch" | "clearance"
    distance: float             # 0 for hard/touch, gap for clearance [m]
    overlap_volume: float       # [m^3]
    point: list                 # clash centroid, host coords [m]
    du: float = 0.0             # extent of the clash region along member axis u [m]
    dv: float = 0.0             # ... along width v
    dw: float = 0.0             # ... along depth w
    xi: float = 0.5             # normalised position of the clash along u (0..1)
    lo: list = None             # clash region min (u, v, w) in the member frame [m]
    hi: list = None             # clash region max (u, v, w)
    crossing_angle: float = 90  # angle between MEP axis and structural axis [deg]
    mep_vertical: bool = False  # MEP element axis within 30 deg of vertical
    method: str = "manifold"    # how the intersection was measured
    extra: dict = field(default_factory=dict)

    def as_row(self):
        d = asdict(self)
        d.update(d.pop("extra"))
        for k, name in (("lo", "lo"), ("hi", "hi")):
            v = d.pop(k) or [None] * 3
            d.update({f"{name}_u": v[0], f"{name}_v": v[1], f"{name}_w": v[2]})
        return d


# --------------------------------------------------------------------------- broad phase
def _boxes(elems, pad=0.0):
    b = np.stack([e.bbox for e in elems])
    b[:, :3] -= pad
    b[:, 3:] += pad
    return b


def broadphase_rtree(struct, mep, clearance):
    """Candidate (i, j) pairs: struct[i] box overlaps mep[j] box inflated by clearance."""
    mb = _boxes(mep, clearance)
    p = index.Property()
    p.dimension = 3
    idx = index.Index(((j, tuple(b), None) for j, b in enumerate(mb)), properties=p, interleaved=True)
    pairs = []
    for i, b in enumerate(_boxes(struct)):
        pairs.extend((i, j) for j in idx.intersection(tuple(b)))
    return pairs


def broadphase_bruteforce(struct, mep, clearance, chunk=512):
    """O(n*m) vectorised AABB test - baseline for the scalability comparison."""
    sb, mb = _boxes(struct), _boxes(mep, clearance)
    pairs = []
    for k in range(0, len(sb), chunk):
        s = sb[k:k + chunk, None, :]
        ok = np.all(s[..., :3] <= mb[None, :, 3:], axis=-1) & np.all(s[..., 3:] >= mb[None, :, :3], axis=-1)
        ii, jj = np.nonzero(ok)
        pairs.extend(zip((ii + k).tolist(), jj.tolist()))
    return pairs


# --------------------------------------------------------------------------- narrow phase
class _FclCache:
    def __init__(self):
        self._c = {}

    def get(self, e: Element):
        o = self._c.get(e.uid)
        if o is None:
            m = e.mesh
            bvh = fcl.BVHModel()
            bvh.beginModel(len(m.vertices), len(m.faces))
            bvh.addSubModel(np.asarray(m.vertices, float), np.asarray(m.faces, np.int32))
            bvh.endModel()
            o = fcl.CollisionObject(bvh, fcl.Transform())
            self._c[e.uid] = o
        return o

    def drop(self, uid):
        self._c.pop(uid, None)


def _axis(e: Element):
    loc = e.location or {}
    if loc.get("kind") == "curve":
        d = np.asarray(loc["p1"]) - np.asarray(loc["p0"])
        n = np.linalg.norm(d)
        if n > 1e-9:
            return d / n
    return e.frame.u


class _seeded:
    """trimesh resolves inside/outside tests on open meshes with random rays: fix the seed
    locally so results are reproducible, without disturbing global random state."""

    def __enter__(self):
        self.state = np.random.get_state()
        np.random.seed(12345)

    def __exit__(self, *exc):
        np.random.set_state(self.state)


def _boxes_overlap(a: trimesh.Trimesh, b: trimesh.Trimesh, pad=0.0) -> bool:
    return bool(np.all(a.bounds[0] - pad <= b.bounds[1]) and np.all(b.bounds[0] - pad <= a.bounds[1]))


def _contains(s: Element, m: Element) -> bool:
    """True if m lies (at least partly) inside s or s inside m, with no surface crossing."""
    lo = np.maximum(s.bbox[:3], m.bbox[:3])
    hi = np.minimum(s.bbox[3:], m.bbox[3:])
    if np.any(hi < lo):
        return False
    with _seeded():
        for a, b in ((s, m), (m, s)):
            for pa in a.parts:
                for pb in b.parts:
                    if not _boxes_overlap(pa, pb):
                        continue
                    v = pb.vertices
                    inb = np.all((v >= pa.bounds[0]) & (v <= pa.bounds[1]), axis=1)
                    if not inb.any():
                        continue
                    probe = np.vstack([v[inb][:4], pb.centroid])
                    if pa.contains(probe).any():
                        return True
    return False


def _intersection_points(s: Element, m: Element, n_grid=14):
    """Points describing the intersection solid + its volume. Returns (pts, vol, method).
    Exact (Manifold) Boolean, applied component-wise when an element is made of several
    closed solids; deterministic point sampling only if a component is not closed."""
    try:
        if s.parts_watertight and m.parts_watertight:
            pts, vol = [], 0.0
            for ps in s.parts:
                for pm in m.parts:
                    if not _boxes_overlap(ps, pm):
                        continue
                    inter = trimesh.boolean.intersection([ps, pm], engine="manifold")
                    if inter is not None and len(inter.vertices):
                        pts.append(np.asarray(inter.vertices))
                        vol += float(abs(inter.volume))
            method = "manifold" if len(s.parts) == 1 and len(m.parts) == 1 else "manifold-parts"
            return (np.vstack(pts) if pts else np.empty((0, 3))), vol, method
    except Exception:
        pass
    # fallback: sample the overlap of the two boxes and keep points inside both meshes
    lo = np.maximum(s.bbox[:3], m.bbox[:3])
    hi = np.minimum(s.bbox[3:], m.bbox[3:])
    if np.any(hi <= lo):
        return np.empty((0, 3)), 0.0, "sampled"
    g = [np.linspace(lo[k], hi[k], n_grid) for k in range(3)]
    pts = np.stack(np.meshgrid(*g, indexing="ij"), -1).reshape(-1, 3)
    with _seeded():
        inside = s.mesh.contains(pts) & m.mesh.contains(pts)
    vol = float(np.prod(hi - lo) * inside.mean())
    return pts[inside], vol, "sampled"


class ClashDetector:
    def __init__(self, model: Model, clearance: float = 0.025, broadphase: str = "rtree"):
        self.model = model
        self.clearance = clearance
        self.broadphase = broadphase
        self.fcl = _FclCache()
        self.timing = {}

    def candidates(self, struct, mep):
        f = broadphase_rtree if self.broadphase == "rtree" else broadphase_bruteforce
        return f(struct, mep, self.clearance)

    def narrow(self, s: Element, m: Element) -> Clash | None:
        os_, om = self.fcl.get(s), self.fcl.get(m)
        creq = fcl.CollisionRequest(num_max_contacts=1, enable_contact=False)
        cres = fcl.CollisionResult()
        hit = fcl.collide(os_, om, creq, cres) > 0
        contained = False
        if not hit:
            # surface-triangle tests miss full containment (e.g. an elbow embedded in a slab):
            # check whether either mesh has a vertex inside the other
            contained = _contains(s, m)
            hit = contained
        if not hit:
            dreq = fcl.DistanceRequest(enable_nearest_points=True)
            dres = fcl.DistanceResult()
            d = fcl.distance(os_, om, dreq, dres)
            if d > self.clearance:
                return None
            p = (np.asarray(dres.nearest_points[0]) + np.asarray(dres.nearest_points[1])) / 2
            c = Clash(s.uid, m.uid, "clearance", float(d), 0.0, p.round(4).tolist(), method="fcl-distance")
            self._localise(c, s, m, np.atleast_2d(p))
            return c
        pts, vol, method = _intersection_points(s, m)
        if contained:
            method += "+contained"
        kind = "hard" if vol > VOL_EPS else "touch"
        if len(pts) == 0:  # touching faces: use the overlap box centre
            lo = np.maximum(s.bbox[:3], m.bbox[:3])
            hi = np.minimum(s.bbox[3:], m.bbox[3:])
            pts = np.atleast_2d((lo + hi) / 2)
        c = Clash(s.uid, m.uid, kind, 0.0, vol, pts.mean(0).round(4).tolist(), method=method)
        self._localise(c, s, m, pts)
        return c

    def _localise(self, c: Clash, s: Element, m: Element, pts):
        f = s.frame
        loc = f.to_local(pts)
        lo, hi = loc.min(0), loc.max(0)
        c.lo, c.hi = lo.round(4).tolist(), hi.round(4).tolist()
        c.du, c.dv, c.dw = (float(x) for x in hi - lo)
        c.xi = float(np.clip(loc[:, 0].mean() / f.length, 0, 1)) if f.length > 1e-9 else 0.5
        am = _axis(m)
        a = abs(float(np.dot(am, _axis(s))))
        c.crossing_angle = float(np.degrees(np.arccos(np.clip(a, 0, 1))))
        c.mep_vertical = bool(m.is_linear and abs(am[2]) > np.cos(np.radians(30)))

    def run(self, struct=None, mep=None):
        struct = struct if struct is not None else self.model.structural
        mep = mep if mep is not None else self.model.mep
        t0 = time.perf_counter()
        pairs = self.candidates(struct, mep)
        t1 = time.perf_counter()
        clashes = []
        for i, j in pairs:
            c = self.narrow(struct[i], mep[j])
            if c is not None:
                clashes.append(c)
        t2 = time.perf_counter()
        self.timing = {"broadphase_s": t1 - t0, "narrowphase_s": t2 - t1,
                       "n_struct": len(struct), "n_mep": len(mep), "n_candidates": len(pairs),
                       "n_clashes": len(clashes)}
        return clashes
