"""Load-path-aware clash severity.

Local impact  eta in [0, 1]  - demand-weighted capacity loss index (DCLI):
    eta = max_a  f_a(location) * loss_a(geometry)
  a in {flexure, shear, axial, punching, ...}; f_a = relative demand of action a at the clash
  location (simply supported shapes along a member), loss_a = fraction of the corresponding
  sectional capacity removed by the clash region, computed from the region's exact position in
  the member's cross-section (rectangular hole inertia; I-section plastic modulus). Slab rules
  are adapted from ACI 318-19 (8.5.4 openings in two-way slabs, 22.6.4.3 openings within 4h of a
  column, 20.6 embedded conduits); beam opening limits from design guidance (h/3 for concrete
  web openings; AISC Design Guide 2 for steel).
Global consequence  C = LPCI at the clash location (loadpath.consequence_at).
Class  - risk matrix (eta level x C level); clearance clashes -> "Coordination".
Score  - s = eta * (1 + beta * C) / (1 + beta), used for ranking.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .clash import Clash
from .loadpath import GROUND, LoadPathGraph, material_of
from .model import Element

CLASSES = ["Negligible", "Minor", "Major", "Critical"]
ETA_LEVELS = (0.05, 0.15, 0.35)          # L0 | L1 | L2 | L3
# consequence levels in "bay-equivalents" (dependent load / D_ref, D_ref = typical direct slab-to-support load):
BAYS_D = (3.0, 15.0)                     # C1: < 3 bays | C2: 3-15 | C3: >= 15
BAYS_E = (1.0, 5.0)                      # ... or orphaned (no alternate path) load >= 1 / 5 bays
MATRIX = [  # rows: eta level L0..L3, cols: consequence C1..C3
    ["Negligible", "Negligible", "Minor"],
    ["Minor", "Minor", "Major"],
    ["Minor", "Major", "Critical"],
    ["Major", "Critical", "Critical"],
]
COVER = 0.05                 # m, band near beam faces where longitudinal bars sit
LARGE_OPENING_ETA = 0.15     # minimum loss for openings beyond design-guide size limits


@dataclass
class Assessment:
    eta: float
    action: str               # governing action
    loss: float               # capacity fraction lost for that action
    demand: float             # relative demand factor at the location
    flags: list
    C: float                  # consequence (LPCI at the clash location)
    D: float = 0.0            # dependent load [kN]
    E: float = 0.0            # orphaned load [kN]
    score: float = 0.0
    severity: str = ""
    extra: dict = field(default_factory=dict)


def level(x, cuts):
    return int(np.searchsorted(cuts, x, side="right"))


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _ranges(c: Clash, s: Element):
    """Clash region in member-local coordinates; falls back to centred extents."""
    if c.lo is not None and c.hi is not None:
        return np.asarray(c.lo, float), np.asarray(c.hi, float)
    f = s.frame
    mid = np.array([c.xi * f.length, f.width / 2, f.depth / 2])
    ext = np.array([c.du, c.dv, c.dw])
    return mid - ext / 2, mid + ext / 2


# ------------------------------------------------------------------ local impact by member type
OPEN_WEB_NAMES = ("bar joist", "k-series", "lh-series", "dlh-series", "open web", "truss")


def is_open_web(s: Element) -> bool:
    """Open-web joist / truss, by family name or - as a fallback - because its bars fill
    under 8% of the bounding box (rolled I-sections fill ~12-40%)."""
    name = f"{s.family or ''} {s.type or ''}".lower()
    if any(k in name for k in OPEN_WEB_NAMES):
        return True
    f = s.frame
    box = f.length * f.width * f.depth
    return box > 0 and abs(float(s.mesh.volume)) / box < 0.08


def _open_web(c: Clash, s: Element, m: Element):
    """Material fraction of the joist inside the clash slice that the MEP occupies; chord zone
    (outer 15% of depth) -> flexure, otherwise web members -> shear."""
    import trimesh
    f = s.frame
    lo, hi = _ranges(c, s)
    pad = 0.01
    o1 = f.origin + (lo[0] - pad) * f.u
    o2 = f.origin + (hi[0] + pad) * f.u
    v_slice = 0.0
    for part in s.parts:          # closed bar solids: capped slices have exact volume
        try:
            sl = trimesh.intersections.slice_mesh_plane(part, f.u, o1, cap=True)
            if sl is None or not len(sl.faces):
                continue
            sl = trimesh.intersections.slice_mesh_plane(sl, -f.u, o2, cap=True)
            if sl is not None and len(sl.faces):
                v_slice += abs(float(sl.volume))
        except Exception:
            continue
    loss = float(np.clip(c.overlap_volume / v_slice, 0, 1)) if v_slice > 1e-9 else 0.5
    xi = c.xi
    chord = lo[2] < 0.15 * f.depth or hi[2] > 0.85 * f.depth
    if chord:
        fM = 4 * xi * (1 - xi)
        return fM * loss, "flexure", loss, fM, ["open_web", "chord_cut"]
    fV = abs(1 - 2 * xi)
    return fV * loss, "shear", loss, fV, ["open_web", "web_member_cut"]


def _beam(c: Clash, s: Element, m: Element):
    if is_open_web(s):
        return _open_web(c, s, m)
    f = s.frame
    h = s.props.get("section_h") or f.depth
    b = s.props.get("section_b") or f.width
    lo, hi = _ranges(c, s)
    # section coordinates measured from the member's low corner (v across width, w up the depth)
    w0, w1 = max(lo[2], 0.0), min(hi[2], f.depth)
    v0, v1 = max(lo[1], 0.0), min(hi[1], f.width)
    ho, bh = max(w1 - w0, 0.0), max(v1 - v0, 0.0)
    y0 = abs((w0 + w1) / 2 - f.depth / 2)            # hole centre offset from mid-depth
    xi = c.xi
    fM, fV = 4 * xi * (1 - xi), abs(1 - 2 * xi)
    flags = []
    if material_of(s) == "steel":
        tf = s.props.get("flange_t") or h / 25
        tw = s.props.get("web_t") or h / 40
        bf = b
        Z = bf * tf * (h - tf) + tw * (h - 2 * tf) ** 2 / 4
        vc = f.width / 2                               # web centre line
        zl = 0.0
        # flanges: lost area x lever arm
        for (z0, z1) in ((0.0, tf), (f.depth - tf, f.depth)):
            o = _overlap(w0, w1, z0, z1)
            if o > 0:
                wf = _overlap(v0, v1, vc - bf / 2, vc + bf / 2)
                zl += o * wf * abs((z0 + z1) / 2 - f.depth / 2)
                if wf > 0.25 * bf:
                    flags.append("flange_cut")
        ow = _overlap(w0, w1, tf, f.depth - tf)
        web_hit = _overlap(v0, v1, vc - tw / 2, vc + tw / 2) > 0
        if web_hit and ow > 0:
            zl += tw * ow * max(y0, ow / 4)
        lossM = float(np.clip(zl / Z, 0, 1))
        lossV = float(np.clip(ow / max(h - 2 * tf, 1e-3), 0, 1)) if web_hit else 0.0
        if web_hit and (xi < h / max(f.length, 1e-3) or xi > 1 - h / max(f.length, 1e-3)):
            flags.append("within_d_of_support")       # AISC DG2: keep web openings >= d from supports
        if web_hit and ho > 0.7 * h:
            flags.append("opening_gt_0.7d")
            lossM, lossV = max(lossM, LARGE_OPENING_ETA), max(lossV, LARGE_OPENING_ETA)
    else:
        r, wfrac = ho / h, min(bh / b, 1.0)
        # rectangular hole (bh x ho) at offset y0: I_red/I = 1 - wfrac[(r^3) + 12 r (y0/h)^2]
        # (concrete and timber; only concrete has longitudinal bars near the faces)
        lossM = float(np.clip(wfrac * (r ** 3 + 12 * r * (y0 / h) ** 2), 0, 1))
        if material_of(s) == "concrete" and (w0 < COVER or w1 > f.depth - COVER) and wfrac > 0.1:
            flags.append("reinforcement_zone")        # longitudinal bars likely severed
            lossM = max(lossM, 0.5 * wfrac)
        lossV = float(np.clip(wfrac * r * (1 + 0.5 * c.du / max(h, 1e-3)), 0, 1))
        if r > 1 / 3 and wfrac > 0.5:
            flags.append("opening_gt_h/3")             # "large opening": special design needed
            lossM, lossV = max(lossM, LARGE_OPENING_ETA), max(lossV, LARGE_OPENING_ETA)
    if fM * lossM >= fV * lossV:
        return fM * lossM, "flexure", lossM, fM, flags
    return fV * lossV, "shear", lossV, fV, flags


def _axial(c: Clash, s: Element, m: Element):
    f = s.frame
    if material_of(s) == "steel":
        A = abs(float(s.mesh.volume)) / max(f.length, 1e-3)
    else:
        A = f.width * f.depth
    lo, hi = _ranges(c, s)
    A_lost = _overlap(lo[1], hi[1], 0, f.width) * _overlap(lo[2], hi[2], 0, f.depth)
    loss = float(np.clip(A_lost / max(A, 1e-6), 0, 1))
    return loss, "axial", loss, 1.0, ["column_penetration"] if s.kind == "column" else []


def _wall(c: Clash, s: Element, m: Element):
    f = s.frame
    L = max(f.length, 1e-3)
    loss = float(np.clip(c.du / L, 0, 1))
    near_end = min(c.xi, 1 - c.xi) * L < max(0.15 * L, 0.6)
    fd = 1.0 if near_end else 0.6
    return fd * loss, "in-plane", loss, fd, ["wall_boundary_zone"] if near_end else []


def _foundation(c: Clash, s: Element, m: Element):
    f = s.frame
    loss = float(np.clip(c.du * c.dv / max(f.length * f.width, 1e-6), 0, 1))
    return loss, "bearing", loss, 1.0, ["foundation_penetration"]


def _slab(c: Clash, s: Element, m: Element, lp: LoadPathGraph | None):
    f = s.frame
    t = s.props.get("thickness") or f.depth
    a = max(c.du, c.dv)
    p = np.asarray(c.point)
    flags = []
    horizontal_run = m.is_linear and not c.mep_vertical and m.kind in ("pipe", "conduit", "duct", "tray")
    if horizontal_run and c.dw < 0.9 * t:
        # run embedded in the slab (ACI 318-19 20.6: outside dimension <= t/3)
        loss = min(1.0, 0.375 * m.mep_size / t)      # = 0.125 at the t/3 limit
        if m.mep_size > t / 3:
            flags.append("embedded_gt_t/3")
        return loss, "embedded", loss, 1.0, flags
    flags.append("through" if c.dw >= 0.9 * t else "partial_penetration")
    cols = []
    if lp is not None and s.uid in lp.G:
        cols = [lp.elems[v] for v in lp.G.successors(s.uid)
                if v != GROUND and lp.elems[v].kind == "column"]
    if not cols:  # beam/wall-supported slab: one-way action, opening relative to the local panel
        sup = [lp.elems[v] for v in lp.G.successors(s.uid) if v != GROUND] if lp is not None and s.uid in lp.G else []
        if sup:
            d = [np.min([np.linalg.norm(p[:2] - np.asarray(x.location[k])[:2]) for k in ("p0", "p1")])
                 if x.is_linear else np.linalg.norm(p[:2] - x.centroid[:2]) for x in sup]
            span = float(np.clip(2 * np.min(d), 2.0, 12.0))
        else:
            span = 6.0
        loss = float(np.clip(a / span, 0, 1))
        return 0.5 * loss, "flexure", loss, 0.5, flags
    cxy = np.array([e.centroid[:2] for e in cols])
    d_all = np.linalg.norm(cxy - p[:2], axis=1)
    k = int(d_all.argmin())
    col = cols[k]
    span = float(np.median([np.sort(np.linalg.norm(cxy - q, axis=1))[1] for q in cxy])) if len(cxy) > 1 else 6.0
    # punching: ACI 318-19 22.6.4.3 - openings within 4h of the column face shorten b0
    c1 = max(col.frame.width, col.frame.depth)
    d_eff = 0.8 * t
    r0, b0 = c1 / 2 + d_eff / 2, 4 * (c1 + d_eff)
    eta_p = 0.0
    if max(d_all[k] - c1 / 2, 0.0) < 4 * t:
        flags.append("within_4h_of_column")
        eta_p = float(np.clip(r0 * a / max(d_all[k], r0) / b0, 0, 1))
    # two-way flexure: ACI 318-19 8.5.4 strip-based opening allowances
    u, v = f.u[:2] / np.linalg.norm(f.u[:2]), f.v[:2] / np.linalg.norm(f.v[:2])
    cs = 0.25 * span                                   # half column-strip width
    in_u = np.min(np.abs((cxy - p[:2]) @ v)) < cs
    in_v = np.min(np.abs((cxy - p[:2]) @ u)) < cs
    zone, fz = ("CS-CS", 1.0) if (in_u and in_v) else (("CS-MS", 0.5) if (in_u or in_v) else ("MS-MS", 0.1))
    flags.append(zone)
    lossF = float(np.clip(a / (2 * cs), 0, 1))
    if eta_p >= fz * lossF:
        return eta_p, "punching", eta_p, 1.0, flags
    return fz * lossF, "flexure", lossF, fz, flags


def local_impact(c: Clash, s: Element, m: Element, lp: LoadPathGraph | None = None):
    if c.kind == "clearance":
        return 0.0, "none", 0.0, 0.0, ["clearance_only"]
    if c.kind == "touch":
        return 0.0, "none", 0.0, 0.0, ["touch"]
    k = s.kind
    if k == "beam":
        return _beam(c, s, m)
    if k in ("column", "brace"):
        return _axial(c, s, m)
    if k == "wall":
        return _wall(c, s, m)
    if k == "foundation":
        return _foundation(c, s, m)
    if k == "slab":
        return _slab(c, s, m, lp)
    return 0.0, "unknown", 0.0, 0.0, ["unknown_kind"]


# ------------------------------------------------------------------ classification
def consequence_level(D, E, D_ref):
    nb, ne = D / D_ref, E / D_ref
    return max(level(nb, BAYS_D), level(ne, BAYS_E))


def classify(eta, c_level, kind):
    if kind == "clearance":
        return "Coordination"
    return MATRIX[level(eta, ETA_LEVELS)][c_level]


def assess(clashes, model, lp: LoadPathGraph | None, beta: float = 2.0, use_loadpath=True):
    out = []
    for c in clashes:
        s, m = model.by_uid[c.s], model.by_uid[c.m]
        eta, action, loss, demand, flags = local_impact(c, s, m, lp)
        if use_loadpath and lp is not None:
            C, D, E = lp.consequence_at(s.uid, c.point)
            cl = consequence_level(D, E, lp.D_ref)
        else:
            C, D, E, cl = 0.5, 0.0, 0.0, 1           # ablation: every member "extended" consequence
        score = eta * (1 + beta * C) / (1 + beta)
        a = Assessment(float(eta), action, float(loss), float(demand), flags, float(C),
                       float(D), float(E), float(score), classify(eta, cl, c.kind))
        a.extra["c_level"] = cl
        a.extra["bays"] = D / lp.D_ref if (use_loadpath and lp is not None) else None
        out.append(a)
    return out


# ------------------------------------------------------------------ baselines
def baseline_geometry(c: Clash):
    """Geometry-only practice: class from penetration depth (smallest clash extent)."""
    if c.kind == "clearance":
        return "Coordination"
    pen = min(c.du, c.dv, c.dw) if c.kind == "hard" else 0.0
    return CLASSES[level(pen, (0.010, 0.050, 0.150))]


CATEGORY_PRIORITY = {"column": 3, "foundation": 2, "wall": 2, "beam": 2, "brace": 2, "slab": 1}


def baseline_category(c: Clash, s: Element, m: Element):
    """Rule-of-thumb triage: member type priority, bumped for large MEP elements."""
    if c.kind == "clearance":
        return "Coordination"
    if c.kind == "touch":
        return "Negligible"
    p = CATEGORY_PRIORITY.get(s.kind, 1) + (1 if m.mep_size >= 0.3 else 0)
    return CLASSES[min(p, 3)]
