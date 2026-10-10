"""Repeat the narrow phase on clash pairs whose uids end with the given suffixes; report variability."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dtclash.clash import ClashDetector  # noqa: E402
from dtclash.model import Model  # noqa: E402
from dtclash.severity import local_impact  # noqa: E402

model = Model(sys.argv[1])
for spec in sys.argv[2:]:
    s_suf, m_suf = spec.split(",")
    S = next(e for e in model.structural if e.uid.endswith(s_suf))
    M = next(e for e in model.mep if e.uid.endswith(m_suf))
    print(f"{S.kind} {S.family} parts={len(S.parts)} watertight={S.mesh.is_watertight} | "
          f"{M.kind} {M.family} parts={len(M.parts)} watertight={M.mesh.is_watertight} "
          f"parts_watertight={M.parts_watertight}")
    for k in range(4):
        c = ClashDetector(model).narrow(S, M)
        print(f"   run{k}: {c.kind} vol={c.overlap_volume:.6e} method={c.method} "
              f"ext=({c.du:.4f},{c.dv:.4f},{c.dw:.4f}) eta={local_impact(c, S, M, None)[0]:.6f}")
