"""Check journal limits: abstract <= 150 words; 3-5 highlights of <= 85 characters; <= 7 keywords."""
import re
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1]
ok = True
abstract = (PAPER / "tables" / "abstract.md").read_text(encoding="utf-8").strip()
n = len(re.findall(r"\b[\w’'.%-]+\b", abstract))
print(f"abstract: {n} words (limit 150)")
ok &= n <= 150
hl = [l[2:].strip() for l in (PAPER / "highlights.md").read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
print(f"highlights: {len(hl)} (3-5)")
ok &= 3 <= len(hl) <= 5
for h in hl:
    print(f"  {len(h):>3} chars  {h}")
    ok &= len(h) <= 85
kw = re.search(r"\*\*Keywords:\*\*(.+)", (PAPER / "manuscript.md").read_text(encoding="utf-8")).group(1)
k = [x.strip() for x in kw.split(";") if x.strip()]
print(f"keywords: {len(k)} (1-7)")
ok &= 1 <= len(k) <= 7
sys.exit(0 if ok else 1)
