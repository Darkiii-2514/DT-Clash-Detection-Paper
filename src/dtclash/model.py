"""Load a Revit export (meta.json + elements.jsonl) into Python objects.

Every element gets a *local frame* (u = span/axis, v = width, w = depth) and
dimensions measured from its own mesh, so the analysis does not depend on how
a particular Revit family names its section parameters.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
import trimesh

STRUCT_KIND = {
    "OST_StructuralColumns": "column",
    "OST_StructuralFraming": "beam",
    "OST_StructuralFoundation": "foundation",
    "OST_Floors": "slab",
    "OST_Walls": "wall",
}
MEP_KIND = {
    "OST_DuctCurves": "duct", "OST_FlexDuctCurves": "duct",
    "OST_PipeCurves": "pipe", "OST_FlexPipeCurves": "pipe",
    "OST_CableTray": "tray", "OST_Conduit": "conduit",
    "OST_DuctFitting": "fitting", "OST_PipeFitting": "fitting",
    "OST_CableTrayFitting": "fitting", "OST_ConduitFitting": "fitting",
    "OST_DuctAccessory": "accessory", "OST_PipeAccessory": "accessory",
    "OST_MechanicalEquipment": "equipment", "OST_Sprinklers": "sprinkler",
}
Z = np.array([0.0, 0.0, 1.0])


@dataclass
class Frame:
    origin: np.ndarray      # start of member axis (or min corner for slabs)
    u: np.ndarray           # span / axis direction
    v: np.ndarray           # width direction
    w: np.ndarray           # depth direction (vertical for beams/slabs)
    length: float           # extent along u
    width: float            # extent along v
    depth: float            # extent along w

    def to_local(self, pts: np.ndarray) -> np.ndarray:
        d = np.atleast_2d(pts) - self.origin
        return np.column_stack([d @ self.u, d @ self.v, d @ self.w])


@dataclass
class Element:
    uid: str
    id: int
    doc: str
    role: str                     # "structural" | "mep"
    bic: str
    category: str | None
    family: str | None
    type: str | None
    level: str | None
    location: dict | None
    bbox: np.ndarray              # (6,) min xyz, max xyz  [m]
    props: dict
    joins: list[str]
    verts: np.ndarray             # (n,3) [m]
    faces: np.ndarray             # (k,3)
    truncated: bool = False
    _extra: dict = field(default_factory=dict, repr=False)

    # ---- classification
    @property
    def kind(self) -> str:
        if self.role == "structural":
            k = STRUCT_KIND.get(self.bic, "other")
            if k == "beam" and self.props.get("struct_type") == "Brace":
                return "brace"
            return k
        return MEP_KIND.get(self.bic, "other")

    @property
    def is_linear(self) -> bool:
        return bool(self.location and self.location.get("kind") == "curve")

    # ---- geometry
    @cached_property
    def mesh(self) -> trimesh.Trimesh:
        m = trimesh.Trimesh(self.verts, self.faces, process=True, validate=False)
        return m

    @cached_property
    def parts(self) -> list[trimesh.Trimesh]:
        """Closed component solids. Families built from touching solids (e.g. truss bars of a
        bar joist) share vertices after merging and are not watertight as a whole, but each
        component is; exact Booleans are then applied component-wise."""
        m = self.mesh
        if m.is_watertight:
            return [m]
        return list(m.split(only_watertight=False))

    @property
    def parts_watertight(self) -> bool:
        return all(p.is_watertight for p in self.parts)

    @cached_property
    def solid_parts(self) -> list[trimesh.Trimesh]:
        """Closed solids for Booleans: watertight components as they are, open components
        (whose inside is undefined) replaced by their convex hull - a deterministic,
        slightly conservative stand-in. Degenerate (flat) open components are dropped."""
        out = []
        for p in self.parts:
            if p.is_watertight:
                out.append(p)
                continue
            try:
                h = p.convex_hull
            except Exception:
                continue
            if h.is_watertight and abs(float(h.volume)) > 1e-9:
                out.append(h)
        return out

    @property
    def has_open_parts(self) -> bool:
        return not self.parts_watertight

    @cached_property
    def frame(self) -> Frame:
        return _frame(self)

    @property
    def centroid(self) -> np.ndarray:
        return self.verts.mean(axis=0)

    # ---- MEP size (outer dimension incl. insulation) used for opening checks
    @property
    def mep_size(self) -> float:
        p = self.props
        ins = 2 * p.get("insulation", 0.0)
        if "outer_diameter" in p:
            return p["outer_diameter"] + ins
        if "diameter" in p:
            return p["diameter"] + ins
        if "width" in p and "height" in p:
            return max(p["width"], p["height"]) + ins
        f = self.frame
        return max(f.width, f.depth)


_RAY_DIRS = np.array([[0.4395064455, 0.617598629942, 0.652231566745],
                      [-0.7071067812, 0.0, 0.7071067812],
                      [0.0, -0.8320502943, -0.5547001962]])


def inside(mesh: trimesh.Trimesh, pts) -> np.ndarray:
    """Deterministic point-in-mesh test: ray-crossing parity along three fixed directions,
    majority vote. trimesh's contains() resolves open meshes with unseeded random rays, which
    made results differ run to run; this test gives the same answer every time."""
    pts = np.atleast_2d(np.asarray(pts, float))
    votes = np.zeros(len(pts), int)
    for d in _RAY_DIRS:
        dirs = np.tile(d / np.linalg.norm(d), (len(pts), 1))
        _, ray_idx = mesh.ray.intersects_id(pts, dirs, multiple_hits=True)
        votes += (np.bincount(ray_idx, minlength=len(pts)) % 2).astype(int)
    return votes >= 2


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _frame(e: Element) -> Frame:
    pts = e.verts
    loc = e.location or {}
    if e.kind in ("slab", "foundation") or not e.is_linear:
        if e.kind == "column":
            u = Z.copy()
        elif e.kind in ("slab", "foundation"):
            # in-plan principal axis as u, depth vertical
            xy = pts[:, :2] - pts[:, :2].mean(0)
            _, _, vt = np.linalg.svd(xy, full_matrices=False) if len(xy) > 2 else (None, None, np.eye(2))
            u = np.array([vt[0, 0], vt[0, 1], 0.0])
        else:  # point-based elements (equipment etc.): principal axes
            c = pts - pts.mean(0)
            _, _, vt = np.linalg.svd(c, full_matrices=False)
            u = vt[0]
    else:
        u = _unit(np.asarray(loc["p1"]) - np.asarray(loc["p0"]))
    u = _unit(u)
    if e.kind in ("column",) or abs(u @ Z) > 0.9:          # vertical member
        w = _unit(np.cross(u, [1.0, 0.0, 0.0])) if abs(u[0]) < 0.9 else _unit(np.cross(u, [0.0, 1.0, 0.0]))
    else:                                                    # horizontal-ish: depth is vertical
        w = _unit(Z - (Z @ u) * u)
    v = _unit(np.cross(w, u))
    origin = pts.min(0) if not e.is_linear else np.asarray(loc["p0"], float)
    local = np.column_stack([(pts - origin) @ u, (pts - origin) @ v, (pts - origin) @ w])
    lo, hi = local.min(0), local.max(0)
    # re-anchor at the member's low corner on all three axes, so local coordinates span
    # [0,length] x [0,width] x [0,depth] (Revit beam location lines sit at the top face)
    origin = origin + lo[0] * u + lo[1] * v + lo[2] * w
    return Frame(origin, u, v, w, float(hi[0] - lo[0]), float(hi[1] - lo[1]), float(hi[2] - lo[2]))


def norm_uid(uid: str) -> str:
    """Document tags use underscores for spaces (older exports kept link-title spaces)."""
    doc, _, rest = uid.partition(":")
    return doc.replace(" ", "_") + ":" + rest


def element_from_record(r: dict) -> Element | None:
    m = r.get("mesh") or {}
    if not m.get("f"):
        return None
    return Element(
        uid=norm_uid(r["uid"]), id=r["id"], doc=r["doc"].replace(" ", "_"), role=r["role"], bic=r["bic"],
        category=r.get("category"), family=r.get("family"), type=r.get("type"),
        level=r.get("level"), location=r.get("location"),
        bbox=np.asarray(r["bbox"], float) if r.get("bbox") else _bbox(m["v"]),
        props=r.get("props") or {}, joins=[norm_uid(j) for j in r.get("joins") or []],
        verts=np.asarray(m["v"], float), faces=np.asarray(m["f"], np.int64),
        truncated=bool(m.get("truncated")),
    )


class Model:
    """A federated export: structural elements of the host + MEP from host/links."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.meta = json.loads((self.folder / "meta.json").read_text())
        self.elements: list[Element] = []
        with open(self.folder / "elements.jsonl", encoding="utf-8") as f:
            for line in f:
                e = element_from_record(json.loads(line))
                if e is not None:
                    self.elements.append(e)
        self.reindex()
        self.reference_pairs: set[tuple[str, str]] = set()
        ref = self.folder / "revit_reference.jsonl"
        self.meta["bad_reference_lines"] = 0
        if ref.exists():
            with open(ref, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:   # e.g. file still being written by Revit
                        self.meta["bad_reference_lines"] += 1
                        continue
                    self.reference_pairs.add((norm_uid(r["structural"]), norm_uid(r["mep"])))

    def reindex(self):
        self.by_uid = {e.uid: e for e in self.elements}
        self.by_docid = {(e.doc, e.id): e.uid for e in self.elements}
        self.structural = [e for e in self.elements if e.role == "structural"]
        self.mep = [e for e in self.elements if e.role == "mep"]

    def __repr__(self):
        return (f"Model({self.meta.get('host_tag')}: {len(self.structural)} structural, "
                f"{len(self.mep)} MEP, {len(self.reference_pairs)} Revit reference pairs)")


def _bbox(v):
    a = np.asarray(v, float)
    return np.concatenate([a.min(0), a.max(0)])
