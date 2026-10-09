"""One-off: renumber figures 6-8 to match order of first citation and rename the files."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "paper"
md = P / "manuscript.md"
t = md.read_text(encoding="utf-8")
# in-text references (placeholders avoid chained replacements)
t = re.sub(r"Fig\. 8([a-d])", r"Fig. @6\1", t)
t = re.sub(r"Fig\. 6(?![\d])", "Fig. @7", t)
t = re.sub(r"Fig\. 7(?![\d])", "Fig. @8", t)
t = t.replace("Fig. @", "Fig. ")
# file names
ren = {"fig8_examples.png": "fig6_examples.png", "fig6_sensitivity.png": "fig7_sensitivity.png",
       "fig7_twin_latency.png": "fig8_twin_latency.png"}
for a, b in ren.items():
    t = t.replace(f"figures/{a}", f"figures/{b}")
md.write_text(t, encoding="utf-8")
fig_dir = P / "figures"
tmp = {}
for a, b in ren.items():
    if (fig_dir / a).exists():
        (fig_dir / a).rename(fig_dir / (b + ".tmp"))
        tmp[b + ".tmp"] = b
for a, b in tmp.items():
    (fig_dir / a).rename(fig_dir / b)
f = ROOT / "experiments" / "figures.py"
s = f.read_text(encoding="utf-8")
for a, b in ren.items():
    s = s.replace(f'"{a}"', f'"{b}"')
f.write_text(s, encoding="utf-8")
print("renumbered:", ren)
