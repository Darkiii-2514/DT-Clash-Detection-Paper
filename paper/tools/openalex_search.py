"""Reproducible literature search against the OpenAlex API (stdlib only).

Usage:
    python paper/tools/openalex_search.py queries.txt out.json [--per-query 15]

Each non-empty line of queries.txt is one search string. Results are merged,
de-duplicated by DOI/OpenAlex id, and written with the query that found them,
so the search protocol can be reported in the paper.
"""
import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request

API = "https://api.openalex.org/works"
FIELDS = ("id,doi,title,publication_year,primary_location,cited_by_count,"
          "authorships,type,abstract_inverted_index")


def search(query, per_page):
    params = {
        "search": query,
        "per-page": str(per_page),
        "select": FIELDS,
        "filter": "type:article|review|proceedings-article|book-chapter",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "dtclash-litsearch/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["results"]


def abstract(inv):
    if not inv:
        return ""
    pos = sorted((i, w) for w, idx in inv.items() for i in idx)
    return " ".join(w for _, w in pos)


def slim(w, query):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    authors = [a["author"]["display_name"] for a in w.get("authorships", [])]
    return {
        "openalex": w["id"],
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "title": w.get("title"),
        "year": w.get("publication_year"),
        "venue": src.get("display_name"),
        "authors": authors,
        "cited_by": w.get("cited_by_count", 0),
        "type": w.get("type"),
        "abstract": abstract(w.get("abstract_inverted_index")),
        "found_by": [query],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries")
    ap.add_argument("out")
    ap.add_argument("--per-query", type=int, default=15)
    a = ap.parse_args()

    queries = [q.strip() for q in open(a.queries, encoding="utf-8") if q.strip() and not q.startswith("#")]
    merged = {}
    for q in queries:
        for w in search(q, a.per_query):
            key = (w.get("doi") or w["id"]).lower()
            if key in merged:
                merged[key]["found_by"].append(q)
            else:
                merged[key] = slim(w, q)
        time.sleep(0.2)  # stay well under OpenAlex rate limits

    out = {
        "source": API,
        "retrieved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "queries": queries,
        "results": sorted(merged.values(), key=lambda r: -r["cited_by"]),
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"{len(queries)} queries -> {len(merged)} unique works -> {a.out}")


if __name__ == "__main__":
    main()
