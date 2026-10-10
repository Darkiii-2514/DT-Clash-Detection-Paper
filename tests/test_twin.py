import copy

import pytest

import numpy as np

from dtclash.twin import DigitalTwin
from synthetic import frame_model


def _moved(e, dxyz):
    e2 = copy.copy(e)
    e2.__dict__.pop("mesh", None)
    e2.__dict__.pop("frame", None)
    e2.__dict__.pop("parts", None)
    e2.__dict__.pop("solid_parts", None)
    e2.verts = e.verts + np.asarray(dxyz)
    e2.bbox = e.bbox + np.r_[dxyz, dxyz]
    if e.location and e.location.get("kind") == "curve":
        e2.location = {"kind": "curve", "p0": list(np.add(e.location["p0"], dxyz)),
                       "p1": list(np.add(e.location["p1"], dxyz))}
    return e2


def _full(model, tmp_path, name):
    tw = DigitalTwin(model, tmp_path / name)
    tw.full_sync()
    return tw.snapshot()


def test_incremental_equals_full_recompute(tmp_path):
    tw = DigitalTwin(frame_model(pipe_xi=0.5, pipe_d=0.2), tmp_path / "a.db")
    tw.full_sync()
    assert any(k[0] == "B0" for k in tw.clashes)

    # 1) move the pipe toward the support -> same clash pair, different severity
    pipe = tw.model.by_uid["P0"]
    d, rep = tw.apply(delta_records=[_moved(pipe, (-2.4, 0, 0))])
    assert d.modified == ["P0"] and rep["mode"] == "incremental"
    ref = frame_model(pipe_xi=0.1, pipe_d=0.2)
    assert tw.snapshot() == _full(ref, tmp_path, "b.db")

    # 2) delete the pipe -> clash resolved
    d, rep = tw.apply(delta_records=[], deleted=["P0"])
    assert not tw.clashes and rep["resolved_clashes"]

    # 3) structural change (raise a beam out of the way) re-runs the load path
    tw2 = DigitalTwin(frame_model(pipe_xi=0.5, pipe_d=0.2), tmp_path / "c.db")
    tw2.full_sync()
    beam = tw2.model.by_uid["B0"]
    d, rep = tw2.apply(delta_records=[_moved(beam, (0, 0, 0.5))])
    full = DigitalTwin(copy.copy(tw2.model), tmp_path / "d.db")
    full.full_sync()
    assert tw2.snapshot() == full.snapshot()


def test_noop_delta(tmp_path):
    tw = DigitalTwin(frame_model(), tmp_path / "e.db")
    tw.full_sync()
    d, rep = tw.apply(delta_records=[tw.model.by_uid["P0"]])
    assert d.empty and rep["mode"] == "noop"


def test_incremental_loadpath_equals_full():
    from dtclash.loadpath import LoadPathGraph
    m = frame_model(pipe_xi=None)
    lp = LoadPathGraph(m)
    lp.run()
    beam = m.by_uid["B1"]
    moved = _moved(beam, (0, 0, -0.02))           # small move keeps contacts
    m.elements = [e for e in m.elements if e.uid != "B1"] + [moved]
    m.reindex()
    lp.update(changed=["B1"], deleted=[])
    full = LoadPathGraph(m)
    full.run()
    assert set(lp.G.edges) == set(full.G.edges)
    for u in full.metrics:
        assert lp.metrics[u]["carried_kN"] == pytest.approx(full.metrics[u]["carried_kN"])
        assert lp.metrics[u]["LPCI"] == pytest.approx(full.metrics[u]["LPCI"])
