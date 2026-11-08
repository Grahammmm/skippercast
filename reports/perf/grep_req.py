#!/usr/bin/env python3
"""Every request matching a substring, per run: python3 reports/perf/grep_req.py <raw.json> <substring> [page]"""
import gzip, json, sys
d = json.load(gzip.open(sys.argv[1], 'rt') if sys.argv[1].endswith('.gz') else open(sys.argv[1]))
for r in d["results"]:
    if len(sys.argv) > 3 and r["page"] != sys.argv[3]:
        continue
    for q in r.get("requests", []):
        if sys.argv[2] in q["url"]:
            print(r["profile"], r["page"], r["pass"], r["run"], q["status"], q["bytes"], q["startMs"], q["endMs"], q["failed"], q["fromCache"], q["url"][-60:])
