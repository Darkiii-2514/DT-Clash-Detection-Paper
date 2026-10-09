import numpy as np
import pytest

from dtclash.clash import ClashDetector, broadphase_bruteforce, broadphase_rtree
from dtclash.loadpath import GROUND, LoadPathGraph
from dtclash.severity import assess
from synthetic import SPAN, frame_model


def test_broadphases_agree():
    m = frame_model()
    a = set(broadphase_rtree(m.structural, m.mep, 0.025))
    b = set(broadphase_bruteforce(m.structural, m.mep, 0.025))
    assert a == b and a


def test_pipe_through_beam_is_hard_clash_at_midspan():
    m = frame_model(pipe_xi=0.5, pipe_d=0.15)
    clashes = ClashDetector(m).run()
    beam = [c for c in clashes if c.s == "B0"]
    assert len(beam) == 1
    c = beam[0]
    assert c.kind == "hard"
    # intersection = pipe cylinder segment through the 0.3 m beam: pi r^2 * 0.3
    assert c.overlap_volume == pytest.approx(np.pi * 0.075 ** 2 * 0.3, rel=0.05)
    assert c.xi == pytest.approx(0.5, abs=0.05)
    assert c.dw == pytest.approx(0.15, abs=0.01)
    assert c.crossing_angle == pytest.approx(90, abs=1)


def test_clearance_clash_detected_when_pipe_runs_under_beam():
    m = frame_model(pipe_xi=0.5, pipe_d=0.10, pipe_z=0.5 + 3.0 - 0.6 - 0.065)  # 15 mm gap
    c = [c for c in ClashDetector(m, clearance=0.025).run() if c.s == "B0"]
    assert c and c[0].kind == "clearance" and c[0].distance == pytest.approx(0.015, abs=0.003)


def test_load_path_directions_and_equilibrium():
    m = frame_model(pipe_xi=None)
    lp = LoadPathGraph(m).build().propagate()
    G = lp.G
    assert G.has_edge("S0", "B0") and G.has_edge("B0", "C0") and G.has_edge("C0", "F0")
    assert G.has_edge("F0", GROUND)
    assert not lp.notes["unsupported"]
    total_own = sum(lp.own.values())
    into_ground = sum(lp.carried[f"F{k}"] for k in range(4))
    assert into_ground == pytest.approx(total_own, rel=1e-6)   # load is conserved
    # symmetry: each column carries a quarter of everything above it
    above = total_own - sum(lp.own[f"F{k}"] for k in range(4))
    for k in range(4):
        assert lp.carried[f"C{k}"] == pytest.approx(above / 4, rel=0.05)


def test_criticality_ordering():
    m = frame_model(pipe_xi=None)
    lp = LoadPathGraph(m)
    met = lp.run()
    # every column/footing is a single path for part of the load -> rho > 0
    assert all(met[f"C{k}"]["rho"] > 0 for k in range(4))
    # a footing carries at least as much as the column on it
    assert met["F0"]["lam"] >= met["C0"]["lam"]
    # the slab dominates nothing but itself
    assert met["S0"]["n_dominated"] == 0


def test_severity_midspan_vs_support():
    sev = {}
    for xi in (0.5, 0.1):
        m = frame_model(pipe_xi=xi, pipe_d=0.25)
        lp = LoadPathGraph(m)
        lp.run()
        clashes = [c for c in ClashDetector(m).run() if c.s == "B0"]
        a = assess(clashes, m, lp)[0]
        sev[xi] = a
    assert sev[0.5].action == "flexure" or sev[0.5].action == "shear"
    assert sev[0.1].action == "shear"          # near support shear governs
    assert 0 < sev[0.5].eta <= 1 and 0 < sev[0.1].eta <= 1


def test_fully_embedded_conduit_is_detected():
    """A conduit wholly inside the slab has no surface crossing - containment must be caught."""
    import trimesh
    from synthetic import _el
    m = frame_model(pipe_xi=None)
    p = trimesh.creation.cylinder(radius=0.02, height=2.0, sections=16)
    p.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    p.apply_translation((3.0, 3.0, 3.5 + 0.1))          # slab spans z 3.5..3.7
    e = _el("K0", "mep", "OST_Conduit", p, location={"kind": "curve", "p0": [2, 3, 3.6], "p1": [4, 3, 3.6]},
            props={"outer_diameter": 0.04})
    m.elements.append(e)
    m.reindex()
    c = [c for c in ClashDetector(m).run() if c.m == "K0"]
    assert len(c) == 1 and c[0].kind == "hard" and c[0].s == "S0"
    assert c[0].overlap_volume == pytest.approx(np.pi * 0.02 ** 2 * 2.0, rel=0.05)
