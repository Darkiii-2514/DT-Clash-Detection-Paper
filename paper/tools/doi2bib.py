"""Fetch BibTeX for every DOI in a list straight from doi.org (content negotiation),
re-key it, and report anything that could not be resolved (stdlib only).

    python paper/tools/doi2bib.py paper/lit/selected_dois.txt paper/refs.bib
"""
import re
import sys
import time
import urllib.request


def fetch(doi):
    req = urllib.request.Request("https://doi.org/" + doi,
                                 headers={"Accept": "application/x-bibtex; charset=utf-8",
                                          "User-Agent": "dtclash-refs/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def main(src, dst):
    out, bad = [], []
    for line in open(src, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, doi, why = (x.strip() for x in line.split("|", 2))
        try:
            bib = fetch(doi).strip()
            bib = re.sub(r"^@(\w+)\{[^,]*,", lambda m: "@%s{%s," % (m.group(1), key), bib, count=1)
            title = re.search(r"title\s*=\s*\{(.+?)\},", bib)
            out.append("%% %s\n%s\n" % (why, bib))
            print("ok   %-26s %s" % (key, (title.group(1) if title else "?")[:90]))
        except Exception as ex:
            bad.append((key, doi, str(ex)))
            print("FAIL %-26s %s  (%s)" % (key, doi, ex))
        time.sleep(0.3)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\n%d resolved, %d failed -> %s" % (len(out), len(bad), dst))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(*sys.argv[1:3])
