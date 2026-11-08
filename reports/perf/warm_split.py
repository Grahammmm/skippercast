#!/usr/bin/env python3
"""PERF-BASELINE-1: split a warm desktop visit's network bytes by what they are (B1/P5 evidence).

Usage: python3 reports/perf/warm_split.py [reports/perf/raw/live-desktop.json] [page]
Prints, per run of the warm pass: network requests/bytes (not answered from the cache, no inline data: URLs), the
no-store share, and the reef export, seafloor tiles + ledger + manifest, coast/ocean + coast/report and the rest.
"""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'reports/perf/raw/live-desktop.json'
page = sys.argv[2] if len(sys.argv) > 2 else 'brief'
d = json.load(open(path))
for r in d['results']:
    if r['page'] != page or r['pass'] != 'warm':
        continue
    net = [q for q in r['requests'] if not q['fromCache'] and not q['url'].startswith('data:')]
    b = lambda f: sum(q['bytes'] or 0 for q in net if f(q))
    ns = lambda q: 'no-store' in (q.get('cacheControl') or '')
    print(f"run {r['run']}: {len(net)} req / {b(lambda q: True)} B; no-store {sum(1 for q in net if ns(q))} req / {b(ns)} B; "
          f"export {b(lambda q: 'habitat-export' in q['url'])}; seafloor pmtiles+ledger+manifest {b(lambda q: 'seafloor-morro-bay.pmtiles' in q['url'] or 'ledger' in q['url'] or 'manifest' in q['url'])}; "
          f"coast/ocean+report {b(lambda q: '/api/coast/' in q['url'])}")
