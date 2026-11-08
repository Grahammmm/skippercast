#!/usr/bin/env python3
"""Quick look at one measure.mjs output: per page/pass, heaviest requests, kinds, long tasks."""
import gzip, json, sys
d = json.load(gzip.open(sys.argv[1], 'rt') if sys.argv[1].endswith('.gz') else open(sys.argv[1]))
want = sys.argv[2:] or None
for r in d["results"]:
    if want and r["page"] not in want:
        continue
    print(f"\n=== {r['profile']} {r['page']} {r['pass']} #{r['run']} final={r.get('finalUrl')} redirectMs={r.get('clientRedirectMs')} longTasks={r.get('longTasks')} longest={r.get('longestTaskMs')} script={r.get('scriptMs')} task={r.get('taskMs')} heap={r.get('jsHeapUsedBytes')} canvas={r.get('mapCanvasMs')} lcpEl={r.get('lcpElement')}")
    for k, v in sorted(r.get("byKind", {}).items()):
        print(f"   {k:7s} n={v['requests']:4d} bytes={v['bytes']:>10,d} cached={v['fromCache']}")
    print("   pmtiles:", r.get("pmtiles"), "beforeLCP:", r.get("requestsBeforeLcp"), "beforeFCP:", r.get("requestsBeforeFcp"))
    for h in r.get("heaviest", []):
        print(f"   {h['bytes'] or 0:>10,d} {h['kind']:6s} {h['startMs']:>6}-{h['endMs']} {h['url'][:130]}")
