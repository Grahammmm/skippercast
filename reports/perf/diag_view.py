#!/usr/bin/env python3
"""Compact view of diag.mjs output."""
import json, sys
d = json.load(open(sys.argv[1]))
for r in d["results"]:
    lt = r["longTasks"]
    print(f"run {r['run']} cls={r['cls']} longtasks={len(lt)} total={sum(x[1] for x in lt)}ms biggest={sorted(lt, key=lambda x: -x[1])[:5]}")
    for s in r["shifts"][:4]:
        print(f"  shift t={s['t']} v={s['v']} " + "; ".join(f"{x['node']} y{x['from']}->{x['to']}" for x in s["src"][:4]))
    for c in r["hotCallers"][:10]:
        print(f"  {c['ms']:>6}ms {c['k'][:230]}")
