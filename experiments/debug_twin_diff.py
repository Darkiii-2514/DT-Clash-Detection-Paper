"""Reproduce the first twin_bench checkpoint and print how incremental and full states differ."""
import random
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "experiments")]

from dtclash.model import Model  # noqa: E402
from dtclash.twin import DigitalTwin  # noqa: E402
from twin_bench import TYPES, full_state_snapshot, make_event  # noqa: E402

model = Model(sys.argv[1])
n_events = int(sys.argv[2]) if len(sys.argv) > 2 else 20
rng = random.Random(7)
with tempfile.TemporaryDirectory() as td:
    tw = DigitalTwin(model, Path(td) / "t.db")
    tw.full_sync()
    events = [t for t in TYPES for _ in range(20)]
    rng.shuffle(events)
    log = []
    for k, kind in enumerate(events[:n_events], 1):
        kwargs, target = make_event(kind, tw, rng, k)
        tw.apply(**kwargs, source=f"dbg-{k}")
        log.append((k, kind, target))
    inc = tw.snapshot()
    full, _ = full_state_snapshot(tw.model)
    tw.db.close()
diff = {k: (inc.get(k), full.get(k)) for k in set(inc) | set(full) if inc.get(k) != full.get(k)}
print(f"{len(diff)} differing clash pairs of {len(full)}")
kinds = Counter()
for (s, m), (a, b) in list(diff.items()):
    es, em = model.by_uid.get(s), model.by_uid.get(m)
    kinds[(es.kind if es else "?", "only-inc" if b is None else "only-full" if a is None else "value")] += 1
print(kinds)
for (s, m), (a, b) in list(diff.items())[:12]:
    es = model.by_uid.get(s)
    print(f"  {es.kind if es else '?':<6} {s[-12:]} x {m[-12:]}: incremental={a} full={b}")
touched = {t for _, _, t in log}
print("diff pairs touching an edited element:", sum(1 for (s, m) in diff if s in touched or m in touched))
print("structural events:", [(k, kd) for k, kd, _ in log if kd.startswith("struct")])
