"""Synthetic one-bay frame with hand-checkable answers (used by tests and the paper's
verification section).

  slab 6 x 6 x 0.2 m on four perimeter beams (0.3 x 0.6), on four 0.4 x 0.4 columns
  (3.0 m), on four 1.5 x 1.5 x 0.5 footings. Optional pipe crossing one beam.
"""
from __future__ import annotations

import numpy as np
import trimesh

from dtclash.model import Element, Model

H_COL, SPAN = 3.0, 6.0


def _el(uid, role, bic, mesh: trimesh.Trimesh, location=None, props=None):
    return Element(uid=uid, id=hash(uid) % 10**6, doc="synthetic", role=role, bic=bic,
                   category=bic, family=None, type=None, level=None, location=location,
                   bbox=np.r_[mesh.bounds[0], mesh.bounds[1]], props=props or {}, joins=[],
                   verts=np.asarray(mesh.vertices), faces=np.asarray(mesh.faces))


def box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    m = trimesh.creation.box(extents=hi - lo)
    m.apply_translation((lo + hi) / 2)
    return m


def frame_model(pipe_xi: float | None = 0.5, pipe_d: float = 0.15, pipe_z: float | None = None):
    els = []
    cols = [(0, 0), (SPAN, 0), (SPAN, SPAN), (0, SPAN)]
    zt = 0.5 + H_COL                      # top of columns = beam top = slab soffit
    for k, (x, y) in enumerate(cols):
        els.append(_el(f"F{k}", "structural", "OST_StructuralFoundation",
                       box((x - .75, y - .75, 0), (x + .75, y + .75, .5))))
        els.append(_el(f"C{k}", "structural", "OST_StructuralColumns",
                       box((x - .2, y - .2, .5), (x + .2, y + .2, zt)),
                       location={"kind": "point", "p": [x, y, .5]},
                       props={"material_type": "Concrete"}))
    for k in range(4):
        (x0, y0), (x1, y1) = cols[k], cols[(k + 1) % 4]
        lo = (min(x0, x1) - .15, min(y0, y1) - .15, zt - .6)
        hi = (max(x0, x1) + .15, max(y0, y1) + .15, zt)
        els.append(_el(f"B{k}", "structural", "OST_StructuralFraming", box(lo, hi),
                       location={"kind": "curve", "p0": [x0, y0, zt], "p1": [x1, y1, zt]},
                       props={"material_type": "Concrete", "struct_type": "Beam",
                              "section_h": .6, "section_b": .3}))
    els.append(_el("S0", "structural", "OST_Floors", box((-.15, -.15, zt), (SPAN + .15, SPAN + .15, zt + .2)),
                   props={"thickness": .2}))
    if pipe_xi is not None:   # pipe parallel to y, crossing beam B0 (y = 0 line) at x = xi*SPAN
        x = pipe_xi * SPAN
        z = zt - 0.3 if pipe_z is None else pipe_z
        p = trimesh.creation.cylinder(radius=pipe_d / 2, height=2.0, sections=24)
        p.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        p.apply_translation((x, 0, z))
        els.append(_el("P0", "mep", "OST_PipeCurves", p,
                       location={"kind": "curve", "p0": [x, -1, z], "p1": [x, 1, z]},
                       props={"outer_diameter": pipe_d}))
    m = Model.__new__(Model)
    m.folder, m.meta = None, {"host_tag": "synthetic"}
    m.elements = els
    m.reindex()
    m.reference_pairs = set()
    return m
