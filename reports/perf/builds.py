#!/usr/bin/env python3
"""PERF-BASELINE-1: which /assets/app.<hash>.js build each live run loaded (a deploy mid-measurement changes it).

Usage: python3 reports/perf/builds.py reports/perf/raw/live-*.json.gz
"""
import gzip
import json
import re
import sys
from collections import defaultdict

seen = defaultdict(set)
for path in sys.argv[1:]:
    doc = json.load(gzip.open(path, 'rt') if path.endswith('.gz') else open(path))
    for r in doc['results']:
        builds = {m.group(0) for q in r.get('requests', []) if (m := re.search(r'/assets/app\.[0-9a-f]{10}\.js', q['url']))}
        seen[(path.split('/')[-1], r['page'], r['profile'], r['pass'])].add((r['run'], ','.join(sorted(b.split('.')[1] for b in builds))))
for key in sorted(seen):
    runs = sorted(seen[key])
    print(key, [f'#{n}:{b}' for n, b in runs])
