"""Count complete element records per document tag in a (possibly interrupted) export.

    .venv\\Scripts\\python experiments\\count_records.py data\\raw\\<model>\\elements.jsonl
"""
import collections
import re
import sys

U = re.compile(r'"uid":"((?:[^"\\]|\\.)*)"')
done, torn = collections.Counter(), 0
with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
    for line in f:
        if not line.endswith("\n"):
            torn += 1
            break
        s = line.rstrip("\n")
        m = U.search(s) if (s.startswith("{") and s.endswith("}")) else None
        if m:
            done[m.group(1).split(":")[0]] += 1
print(dict(done), "torn tail:", torn)
