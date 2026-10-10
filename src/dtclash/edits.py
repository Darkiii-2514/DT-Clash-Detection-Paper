"""Element edits used to drive the digital twin in experiments (copies; inputs untouched)."""
from __future__ import annotations

import copy

import numpy as np

from .model import Element

_CACHED = ("mesh", "frame", "parts", "solid_parts")


def _fresh(e: Element, verts: np.ndarray, **changes) -> Element:
    e2 = copy.copy(e)
    for k in _CACHED:
        e2.__dict__.pop(k, None)
    e2.verts = np.asarray(verts, float)
    e2.bbox = np.r_[e2.verts.min(0), e2.verts.max(0)]
    e2.props = dict(e.props)
    for k, v in changes.items():
        setattr(e2, k, v)
    return e2


def translate(e: Element, d) -> Element:
    d = np.asarray(d, float)
    loc = e.location
    if loc and loc.get("kind") == "curve":
        loc = {"kind": "curve", "p0": list(np.add(loc["p0"], d)), "p1": list(np.add(loc["p1"], d))}
    elif loc and loc.get("kind") == "point":
        loc = {"kind": "point", "p": list(np.add(loc["p"], d))}
    return _fresh(e, e.verts + d, location=loc)


def scale_section(e: Element, k: float) -> Element:
    """Enlarge a linear element's cross-section by k about its axis (e.g. a bigger pipe)."""
    if not e.is_linear:
        c = e.verts.mean(0)
        e2 = _fresh(e, c + (e.verts - c) * k)
    else:
        p0, p1 = np.asarray(e.location["p0"], float), np.asarray(e.location["p1"], float)
        u = (p1 - p0) / max(np.linalg.norm(p1 - p0), 1e-9)
        rel = e.verts - p0
        along = np.outer(rel @ u, u)
        e2 = _fresh(e, p0 + along + (rel - along) * k)
    for key in ("diameter", "outer_diameter", "width", "height"):
        if key in e2.props:
            e2.props[key] = e2.props[key] * k
    return e2


def duplicate(e: Element, d, new_uid: str) -> Element:
    e2 = translate(e, d)
    e2.uid = new_uid
    e2.id = -abs(hash(new_uid)) % 10**9
    return e2
