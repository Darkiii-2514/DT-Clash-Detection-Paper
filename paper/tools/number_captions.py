"""Number figure and table captions in order of appearance and check text references.

Figures: the order of ![...](figures/<file>) in manuscript.md defines Fig. 1..n; captions get a
"Fig. n. " prefix (idempotent). Tables: "Table: ..." captions (manuscript + paper/tables/*.md, in
placeholder order) get "Table n. ". Prints any "Fig. k" / "Table k" reference to a missing number.
"""
import re
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1]
md = PAPER / "manuscript.md"
text = md.read_text(encoding="utf-8")

# ---- figures
fig_re = re.compile(r"!\[(?:Fig\. \d+\. )?(.*?)\]\((figures/[^)]+)\)", re.S)
figs = []
def _fig(m):
    figs.append(m.group(2))
    return f"![Fig. {len(figs)}. {m.group(1)}]({m.group(2)})"
text = fig_re.sub(_fig, text)

# ---- tables: inline captions and placeholder files, in document order
order = []
for m in re.finditer(r"^Table: |<!--(TABLE\d+)-->", text, re.M):
    order.append(m.group(1) or "inline")
n = 0
lines = text.split("\n")
for i, line in enumerate(lines):
    if line.startswith("Table: "):
        n += 1
        lines[i] = "Table: " + f"Table {n}. " + re.sub(r"^Table \d+\. ", "", line[len("Table: "):])
    for ph in re.findall(r"<!--(TABLE\d+)-->", line):
        n += 1
        f = PAPER / "tables" / f"{ph.lower()}.md"
        if f.exists():
            t = f.read_text(encoding="utf-8")
            t = re.sub(r"^Table: (?:Table \d+\. )?", f"Table: Table {n}. ", t, count=1)
            f.write_text(t, encoding="utf-8")
text = "\n".join(lines)
md.write_text(text, encoding="utf-8")

for i, f in enumerate(figs, 1):
    print(f"Fig. {i}: {f}")
print(f"{n} tables")
refs = {int(x) for x in re.findall(r"Fig\. (\d+)[a-d]?(?![.\d])", text)}
bad = sorted(r for r in refs if r > len(figs))
if bad:
    print("references to missing figures:", bad)
