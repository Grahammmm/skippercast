#!/usr/bin/env python3
"""PERF-BASELINE-1: compact a measure.mjs output for the repository.

Usage: python3 reports/perf/compact_raw.py reports/perf/raw/live-phone.json ...
Writes the compacted <name>.json (the repository check refuses binary files, so no .gz): inline data: URLs are cut to 64 characters (their byte counts are kept),
everything else is unchanged. The scripts in reports/perf read either form.
"""
import gzip
import json
import sys

for path in sys.argv[1:]:
    doc = json.load(gzip.open(path, 'rt') if path.endswith('.gz') else open(path))
    for r in doc.get('results', []):
        for key in ('requests', 'heaviest'):
            for q in r.get(key, []):
                if q['url'].startswith('data:') and len(q['url']) > 64:
                    q['url'] = q['url'][:64] + f'…[{len(q["url"])} chars]'
    out = path[:-3] if path.endswith('.gz') else path
    with open(out, 'w') as f:
        json.dump(doc, f, separators=(',', ':'))
    print(out)
