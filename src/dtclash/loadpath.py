"""Gravity load-path graph of the structural model and member criticality.

Graph G: directed edge a -> b means "a is supported by b" (load flows a -> b).
A virtual node GROUND terminates every complete load path.

Per member i:
  D_i  dependent load  = factored gravity load passing through i [kN]
                         (for an opening in a slab: the load of the local panel, see
                         consequence_at, because a whole-floor slab is one Revit element)
  E_i  orphaned load   = load of the OTHER elements whose every path to ground passes
                         through i (i dominates them in G) - the load left without an
                         alternate path if i is lost (alternate-load-path idea, UFC 4-023-03)
  lam_i, rho_i         = D_i and (E_i + own_i) as fractions of the building total (reported)
  LPCI_i = (1-alpha) * g(D_i) + alpha * g(E_i),   g(x) = log(1 + x/D_ref) / log(1 + D_max/D_ref)
         D_ref = median D of beams (a typical bay), D_max = largest D of any non-slab member.
  The log scale keeps beams, columns and transfer members on one comparable axis.
"""
from __future__ import annotations

from dataclasses import dataclass

import fcl
import networkx as nx
import numpy as np
from rtree import index

from .model import Element, Model

GROUND = "__ground__"
RANK = {"slab": 5, "brace": 4, "beam": 4, "wall": 2, "column": 2, "foundation": 1}
UNIT_WEIGHT = {"concrete": 24.0, "steel": 77.0, "wood": 5.0, "masonry": 20.0}  # kN/m^3


@dataclass
class LoadCase:
    """Factored gravity loading (ASCE 7 / ACI 318 basic combination 1.2D + 1.6L)."""
    sdl: float = 1.5     # superimposed dead load on slabs [kPa]
    ll: float = 2.4      # live load on slabs [kPa] (office, ASCE 7-22 Table 4.3-1)
    gamma_d: float = 1.2
    gamma_l: float = 1.6


def material_of(e: Element) -> str:
    s = " ".join(str(e.props.get(k, "")) for k in ("material_type", "material")).lower()
    for key in ("steel", "wood", "timber", "masonry", "concrete"):
        if key in s:
            return "wood" if key == "timber" else key
    return "steel" if e.kind == "brace" else "concrete"


def _zr(e):  # (bottom, top) elevation
    return float(e.bbox[2]), float(e.bbox[5])


def _xy_overlap(a, b, tol=0.0):
    ox = min(a.bbox[3], b.bbox[3]) - max(a.bbox[0], b.bbox[0]) + tol
    oy = min(a.bbox[4], b.bbox[4]) - max(a.bbox[1], b.bbox[1]) + tol
    return max(ox, 0) * max(oy, 0)


def _seg_dist(p, a, b):
    """Plan distance from point p to segment ab (2D)."""
    p, a, b = (np.asarray(x, float)[:2] for x in (p, a, b))
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
    return float(np.linalg.norm(p - (a + t * ab)))


class LoadPathGraph:
    def __init__(self, model: Model, contact_tol: float = 0.05, loads: LoadCase | None = None,
                 alpha: float = 0.3, end_tol: float = 0.15):
        self.model = model
        self.tol = contact_tol
        self.end_tol = end_tol
        self.loads = loads or LoadCase()
        self.alpha = alpha
        self.elems = {e.uid: e for e in model.structural}
        self.G = nx.DiGraph()
        self.notes = {"removed_cycle_edges": 0, "unsupported": []}

    # ------------------------------------------------------------------ contacts
    def _fcl(self, e):
        cache = self.__dict__.setdefault("_fcl_objs", {})
        o = cache.get(e.uid)
        if o is None:
            m = e.mesh
            bvh = fcl.BVHModel()
            bvh.beginModel(len(m.vertices), len(m.faces))
            bvh.addSubModel(np.asarray(m.vertices, float), np.asarray(m.faces, np.int32))
            bvh.endModel()
            o = cache[e.uid] = fcl.CollisionObject(bvh, fcl.Transform())
        return o

    def _contacts(self, subset: set | None = None):
        """Structural contact pairs (sorted uid tuples) from physical touch (mesh distance
        <= tol), Revit joins, and member-end proximity (<= end_tol). With `subset`, only pairs
        involving those elements are computed (incremental twin update)."""
        import trimesh
        els = list(self.elems.values())
        p = index.Property()
        p.dimension = 3
        idx = index.Index(((k, tuple(np.r_[e.bbox[:3] - self.tol, e.bbox[3:] + self.tol]), None)
                           for k, e in enumerate(els)), properties=p, interleaved=True)
        joined = {tuple(sorted((a.uid, j))) for a in els for j in a.joins}
        pairs = set()
        for i, e in enumerate(els):
            if subset is not None and e.uid not in subset:
                continue
            for k in idx.intersection(tuple(np.r_[e.bbox[:3] - self.tol, e.bbox[3:] + self.tol])):
                if k == i or (subset is None and k < i):
                    continue
                f = els[k]
                key = tuple(sorted((e.uid, f.uid)))
                if key in joined:
                    pairs.add(key)
                    continue
                d = fcl.distance(self._fcl(e), self._fcl(f), fcl.DistanceRequest(), fcl.DistanceResult())
                if d <= self.tol:
                    pairs.add(key)
        # member-end proximity (as analytical models connect by centre lines): physical steel
        # is often cut back at connections, leaving the mesh short of its support
        for i, e in enumerate(els):
            if e.kind not in ("beam", "brace") or not e.is_linear:
                continue
            for end in ("p0", "p1"):
                pt = np.asarray(e.location[end], float)
                for k in idx.intersection(tuple(np.r_[pt - self.end_tol, pt + self.end_tol])):
                    f = els[k]
                    if k == i or f.kind == "slab":
                        continue
                    if subset is not None and e.uid not in subset and f.uid not in subset:
                        continue
                    _, d, _ = trimesh.proximity.closest_point(f.mesh, pt[None])
                    if d[0] <= self.end_tol or f.mesh.contains(pt[None])[0]:
                        pairs.add(tuple(sorted((e.uid, f.uid))))
        return pairs

    # ------------------------------------------------------------------ orientation rules
    def _orient(self, a: Element, b: Element):
        """Return (upper, lower) = (supported, support) or None if no gravity relation."""
        ka, kb = a.kind, b.kind
        (a0, a1), (b0, b1) = _zr(a), _zr(b)
        t = self.tol
        if ka == kb == "slab":
            return None
        if {ka, kb} <= {"column", "wall"}:
            # stacked vertical elements: the one above rests on the one below
            if a0 >= b1 - 0.3:
                return a, b
            if b0 >= a1 - 0.3:
                return b, a
            return None
        if ka == "foundation" or kb == "foundation":
            f, o = (a, b) if ka == "foundation" else (b, a)
            if o.kind == "foundation":
                return None
            return (o, f) if _zr(o)[1] >= _zr(f)[1] - t else None
        if ka == kb == "beam":
            return self._beam_on_beam(a, b)
        # beam framing into a column/wall: the beam END lands on it -> beam bears on it;
        # a column/wall whose base sits within the beam span -> transfer (it bears on the beam)
        for bm, vt in ((a, b), (b, a)):
            if bm.kind in ("beam", "brace") and vt.kind in ("column", "wall") and bm.is_linear:
                reach = max(vt.frame.width, vt.frame.depth, 0.3) / 2 + t + 0.15
                ends = [np.asarray(bm.location[k]) for k in ("p0", "p1")]
                if vt.kind == "column":
                    end_at = min(np.linalg.norm(e_[:2] - vt.centroid[:2]) for e_ in ends) < reach
                else:
                    end_at = vt.is_linear and min(_seg_dist(e_, vt.location["p0"], vt.location["p1"])
                                                  for e_ in ends) < reach
                if end_at:
                    return bm, vt
                if _zr(vt)[0] >= _zr(bm)[1] - t - 0.05:
                    return vt, bm
                return bm, vt
        # a vertical element on a slab (transfer) or a slab on a column/wall
        for up, lo in ((a, b), (b, a)):
            if up.kind in ("column", "wall") and lo.kind == "slab":
                if _zr(up)[0] >= _zr(lo)[1] - t and _xy_overlap(up, lo) > 0:
                    return up, lo       # column/wall bears on the slab below
                return lo, up           # slab bears on column/wall
        # slab on beam (beam top at or below slab top)
        for up, lo in ((a, b), (b, a)):
            if up.kind == "slab" and lo.kind in ("beam", "brace"):
                return (up, lo) if _zr(lo)[1] <= _zr(up)[1] + t else (lo, up)
        if "brace" in (ka, kb):
            br, o = (a, b) if ka == "brace" else (b, a)
            return br, o
        # fallback: higher centroid rests on lower
        return (a, b) if a.centroid[2] >= b.centroid[2] else (b, a)

    def _beam_on_beam(self, a: Element, b: Element):
        """Secondary beam whose END lands on the other's span is supported by it."""
        def end_on_span(s, p):
            if not (s.location and p.location and s.location.get("kind") == "curve"
                    and p.location.get("kind") == "curve"):
                return False
            reach = max(p.frame.width, 0.2) / 2 + self.tol + 0.15
            for end in (s.location["p0"], s.location["p1"]):
                if _seg_dist(end, p.location["p0"], p.location["p1"]) < reach:
                    # ...but not end-to-end continuity of a split beam
                    if min(np.linalg.norm(np.subtract(end, p.location["p0"])[:2]),
                           np.linalg.norm(np.subtract(end, p.location["p1"])[:2])) > reach:
                        return True
            return False
        ab, ba = end_on_span(a, b), end_on_span(b, a)
        if ab and not ba:
            return a, b
        if ba and not ab:
            return b, a
        return None

    def _stack_edges(self):
        """Vertical elements separated by a slab: connect upper directly to lower."""
        vert = [e for e in self.elems.values() if e.kind in ("column", "wall")]
        out = []
        for u in vert:
            u0, _ = _zr(u)
            best, best_gap = None, 1e9
            for lo in vert:
                if lo is u:
                    continue
                _, l1 = _zr(lo)
                gap = u0 - l1
                if -0.05 <= gap <= 1.2 and _xy_overlap(u, lo) > 0.25 * min(
                        (u.bbox[3] - u.bbox[0]) * (u.bbox[4] - u.bbox[1]),
                        (lo.bbox[3] - lo.bbox[0]) * (lo.bbox[4] - lo.bbox[1])):
                    if gap < best_gap:
                        best, best_gap = lo, gap
            if best is not None:
                out.append((u.uid, best.uid))
        return out

    # ------------------------------------------------------------------ build
    def build(self, pairs: set | None = None):
        self.pairs = self._contacts() if pairs is None else pairs
        self.notes["contact_pairs"] = len(self.pairs)
        self.G = G = nx.DiGraph()
        self.notes["removed_cycle_edges"] = 0
        G.add_node(GROUND)
        for e in self.elems.values():
            G.add_node(e.uid, kind=e.kind)
        for ua, ub in sorted(self.pairs):          # sorted: deterministic edge order
            r = self._orient(self.elems[ua], self.elems[ub])
            if r:
                G.add_edge(r[0].uid, r[1].uid, src="contact")
        for u, v in self._stack_edges():
            if not G.has_edge(v, u):
                G.add_edge(u, v, src="stack")
        # vertical elements that are stacked should not also hang on the slab in between
        for u, v, d in list(G.edges(data=True)):
            if d.get("src") == "contact" and self.elems[u].kind in ("column", "wall") \
                    and self.elems[v].kind == "slab" and any(
                        G.edges[u, w].get("src") == "stack" for w in G.successors(u)):
                G.remove_edge(u, v)
        # ground: foundations, plus the lowest elements that rest on nothing
        zmin = min(_zr(e)[0] for e in self.elems.values())
        found_top = [(_zr(e)[1]) for e in self.elems.values() if e.kind == "foundation"]
        ground_z = (max(found_top) if found_top else zmin) + 0.3
        for e in self.elems.values():
            if e.kind == "foundation" or (G.out_degree(e.uid) == 0 and _zr(e)[0] <= ground_z):
                G.add_edge(e.uid, GROUND, src="ground")
        self._break_cycles()
        reach = nx.ancestors(G, GROUND)
        self.notes["unsupported"] = [u for u in self.elems if u not in reach]
        return self

    def _break_cycles(self):
        G = self.G
        while True:
            try:
                cyc = nx.find_cycle(G)
            except nx.NetworkXNoCycle:
                return
            # drop the edge that most violates the gravity hierarchy (lower rank -> higher rank,
            # or pointing upwards)
            def badness(e):
                a, b = self.elems[e[0]], self.elems[e[1]]
                return (RANK.get(b.kind, 3) - RANK.get(a.kind, 3)) + (b.centroid[2] - a.centroid[2])
            u, v = max(cyc, key=lambda e: badness(e))[:2]
            G.remove_edge(u, v)
            self.notes["removed_cycle_edges"] += 1

    # ------------------------------------------------------------------ loads
    def own_load(self, e: Element) -> float:
        """Factored gravity load originating at element e [kN]."""
        L = self.loads
        vol = e.props.get("volume") or abs(float(e.mesh.volume))
        q = L.gamma_d * vol * UNIT_WEIGHT[material_of(e)]
        if e.kind == "slab":
            t = e.props.get("thickness") or e.frame.depth
            area = vol / t if t > 1e-3 else e.frame.length * e.frame.width
            q += (L.gamma_d * L.sdl + L.gamma_l * L.ll) * area
        return q

    def _split(self, e: Element, supports: list[str]) -> np.ndarray:
        """Fraction of e's load carried by each support."""
        if len(supports) == 1:
            return np.ones(1)
        S = [self.elems.get(s) for s in supports]
        if e.kind == "slab":
            return self._tributary_area(e, S)
        if e.is_linear and e.kind in ("beam", "brace", "wall"):
            f = e.frame
            pos = np.array([np.clip(((s.centroid if s is not None else f.origin) - f.origin) @ f.u
                                    / max(f.length, 1e-6), 0, 1) for s in S])
            order = np.argsort(pos)
            p = pos[order]
            mids = np.r_[0.0, (p[1:] + p[:-1]) / 2, 1.0]
            w = np.empty(len(S))
            w[order] = np.diff(mids)
            return w / w.sum() if w.sum() > 0 else np.full(len(S), 1 / len(S))
        area = np.array([max(_xy_overlap(e, s), 1e-6) if s is not None else 1e-6 for s in S])
        return area / area.sum()

    def _tributary_area(self, slab: Element, S, spacing=0.5) -> np.ndarray:
        """Assign slab plan grid points to the nearest support (tributary-area method)."""
        lo, hi = slab.bbox[:2], slab.bbox[3:5]
        nx_, ny_ = max(int((hi[0] - lo[0]) / spacing), 2), max(int((hi[1] - lo[1]) / spacing), 2)
        gx, gy = np.meshgrid(np.linspace(lo[0], hi[0], nx_), np.linspace(lo[1], hi[1], ny_))
        pts = np.column_stack([gx.ravel(), gy.ravel()])
        # keep points that fall on the slab (ray test straight down through its mesh)
        origins = np.column_stack([pts, np.full(len(pts), slab.bbox[5] + 1.0)])
        hit = slab.mesh.ray.intersects_any(origins, np.tile([0, 0, -1.0], (len(pts), 1)))
        pts = pts[hit] if hit.any() else pts
        D = np.empty((len(pts), len(S)))
        for k, s in enumerate(S):
            if s is None:
                D[:, k] = np.inf
            elif s.is_linear:
                a, b = np.asarray(s.location["p0"])[:2], np.asarray(s.location["p1"])[:2]
                ab = b - a
                t = np.clip(((pts - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
                D[:, k] = np.linalg.norm(pts - (a + t[:, None] * ab), axis=1)
            else:
                D[:, k] = np.linalg.norm(pts - s.centroid[:2], axis=1)
        # a grid point equidistant from several supports is shared equally between them
        tie = D <= D.min(1, keepdims=True) + 1e-6
        w = (tie / tie.sum(1, keepdims=True)).sum(0)
        return w / w.sum() if w.sum() > 0 else np.full(len(S), 1 / len(S))

    def propagate(self):
        """Top-down accumulation of factored load through the DAG."""
        G = self.G
        own = {u: self.own_load(e) for u, e in self.elems.items()}
        carried = dict.fromkeys(G.nodes, 0.0)
        dead = set(self.notes["unsupported"])
        for u in nx.topological_sort(G):
            if u == GROUND:
                continue
            carried[u] += own.get(u, 0.0)
            # only supports that themselves reach the ground take load (no leakage into
            # modelling gaps); unsupported elements keep their load and are reported
            sup = [s for s in sorted(G.successors(u)) if s not in dead]
            if not sup:
                continue
            for s, frac in zip(sup, self._split(self.elems[u], sup)):
                G.edges[u, s]["share"] = float(frac)
                carried[s] += carried[u] * frac
        self.own, self.carried = own, carried
        return self

    # ------------------------------------------------------------------ criticality
    def criticality(self):
        G = self.G
        total = sum(self.own[u] for u in self.elems if u not in self.notes["unsupported"])
        R = G.reverse(copy=False)
        idom = nx.immediate_dominators(R, GROUND)
        self.dom_tree = dom_tree = nx.DiGraph((d, n) for n, d in idom.items() if n != d)
        orphan = {}
        for u in self.elems:
            sub = nx.descendants(dom_tree, u) if u in dom_tree else set()
            orphan[u] = sum(self.own.get(n, 0.0) for n in sub)
        beams = [self.carried[u] for u, e in self.elems.items() if e.kind == "beam" and self.carried[u] > 0]
        non_slab = [self.carried[u] for u, e in self.elems.items() if e.kind != "slab"]
        self.D_ref = float(np.median(beams)) if beams else float(np.median(list(self.carried.values())))
        self.D_max = max(non_slab) if non_slab else max(self.carried.values())
        self.metrics = {}
        for u, e in self.elems.items():
            D, E = self.carried[u], orphan[u]
            self.metrics[u] = {
                "kind": e.kind,
                "own_kN": self.own[u],
                "carried_kN": D,
                "orphan_kN": E,
                "lam": D / total,
                "rho": (E + self.own[u]) / total,
                "n_dominated": len(nx.descendants(dom_tree, u)) if u in dom_tree else 0,
                "n_supports": G.out_degree(u),
                "LPCI": self.lpci(D, E),
                "supported": u not in self.notes["unsupported"],
            }
        self.total_load = total
        return self.metrics

    def _g(self, x):
        return float(np.clip(np.log1p(max(x, 0.0) / self.D_ref) / np.log1p(self.D_max / self.D_ref), 0, 1))

    def lpci(self, D, E):
        return (1 - self.alpha) * self._g(D) + self.alpha * self._g(E)

    def _nearest_support_below(self, slab: Element, p, search=6.0, depth=1.0) -> float:
        """Plan distance from p to the nearest beam/wall/column directly under the slab
        (top within `depth` below the soffit) - physical, independent of graph edges."""
        if not hasattr(self, "_sup_idx"):
            prop = index.Property()
            prop.dimension = 3
            cand = [e for e in self.elems.values() if e.kind in ("beam", "wall", "column", "brace")]
            self._sup_list = cand
            self._sup_idx = index.Index(((k, tuple(e.bbox), None) for k, e in enumerate(cand)),
                                        properties=prop, interleaved=True)
        z0 = slab.bbox[2]
        q = (p[0] - search, p[1] - search, z0 - depth, p[0] + search, p[1] + search, z0 + 0.05)
        best = search / 2
        for k in self._sup_idx.intersection(q):
            s = self._sup_list[k]
            if s.kind in ("wall", "column"):
                # a vertical member supports the slab if it reaches the soffit (incl. members
                # continuing through the floor)
                if s.bbox[2] > z0 + 0.05 or s.bbox[5] < z0 - depth:
                    continue
            elif s.bbox[5] < z0 - depth or s.bbox[5] > slab.bbox[5] + 0.05:
                continue
            d = (_seg_dist(p, s.location["p0"], s.location["p1"]) if s.is_linear
                 else float(np.linalg.norm(p - s.centroid[:2])))
            best = min(best, d)
        return best

    def consequence_at(self, uid: str, point) -> tuple[float, float, float]:
        """(LPCI, D, E) for damage at `point` of member uid. Linear members, columns, walls and
        foundations use the whole-member values; a slab uses its local panel: factored area
        load over a panel of side R = clip(2 x distance to the nearest support below, 1, 6) m
        (R = 1 m for a slab on grade), plus the load of vertical elements bearing on the slab
        within R of the opening."""
        e = self.elems[uid]
        if e.kind != "slab":
            m = self.metrics[uid]
            return m["LPCI"], m["carried_kN"], m["orphan_kN"]
        p = np.asarray(point, float)[:2]
        if self.G.has_edge(uid, GROUND):
            R = 1.0          # slab on grade: the soil carries it, damage stays local
        else:
            R = float(np.clip(2 * self._nearest_support_below(e, p), 1.0, 6.0))
        L = self.loads
        t = e.props.get("thickness") or e.frame.depth
        q = L.gamma_d * (t * UNIT_WEIGHT[material_of(e)] + L.sdl) + L.gamma_l * L.ll
        # panel between supports: a point midway between supports s apart has d = s/2, so the
        # panel side is ~2d (R) and its area R^2 (clipped to 1..36 m^2 by the bounds on R)
        D = q * R ** 2
        E = 0.0
        for v in self.G.predecessors(uid):   # walls/columns standing on the slab near the opening
            w = self.elems[v]
            if w.kind in ("column", "wall") and np.linalg.norm(w.centroid[:2] - p) <= R:
                D += self.carried[v]
                E += self.carried[v] if self.G.out_degree(v) == 1 else 0.0
        return self.lpci(D, E), D, E

    def run(self):
        return self.build().propagate().criticality()

    def update(self, changed: list[str], deleted: list[str]):
        """Incremental rebuild after structural changes: keep cached contact pairs that do not
        involve changed/deleted members, recompute contacts only for the changed members, then
        re-orient, re-propagate and re-score (orientation + propagation are cheap)."""
        self.elems = {e.uid: e for e in self.model.structural}
        gone = set(changed) | set(deleted)
        for u in gone:
            self.__dict__.get("_fcl_objs", {}).pop(u, None)
        self.__dict__.pop("_sup_idx", None)
        keep = {p for p in self.pairs if p[0] not in gone and p[1] not in gone}
        new = self._contacts(subset={u for u in changed if u in self.elems})
        self.build(pairs=keep | new)
        self.propagate()
        return self.criticality()
