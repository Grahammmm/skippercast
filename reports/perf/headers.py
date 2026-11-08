#!/usr/bin/env python3
"""Headers view of one measure.mjs output: status, encoding, cache-control, cf-cache for distinct same-origin URLs of one page/pass."""
import gzip, json, sys
d = json.load(gzip.open(sys.argv[1], 'rt') if sys.argv[1].endswith('.gz') else open(sys.argv[1]))
page, prof, pas = sys.argv[2], sys.argv[3], sys.argv[4]
seen = set()
for r in d["results"]:
    if r["page"] != page or r["profile"] != prof or r["pass"] != pas or r["run"] != 1:
        continue
    for q in r["requests"]:
        key = q["url"].split("?")[0] + str(q.get("range"))
        if key in seen: continue
        seen.add(key)
        print(f"{q['startMs']:>6} {q['endMs']!s:>6} {q['status']!s:>4} {q['bytes'] or 0:>9,d} {q['kind']:6s} cache={int(q['fromCache'])} enc={q['encoding']} cc={q['cacheControl']} cf={q['cfCache']} {q['protocol']} {q['url'][:110]} {q.get('range') or ''}")
