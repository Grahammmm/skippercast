#!/usr/bin/env python3
"""Waterfall excerpt of one run: python3 reports/perf/waterfall.py <raw.json> <page> <profile> <pass> <run> [min_bytes]
Prints the document, every request of at least min_bytes (default 20 KB), each request's start/end in ms from the
first navigation, plus the run's paint and map-usable marks, in time order."""
import gzip, json, sys
d = json.load(gzip.open(sys.argv[1], 'rt') if sys.argv[1].endswith('.gz') else open(sys.argv[1]))
page, prof, pas, run = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
floor = int(sys.argv[6]) if len(sys.argv) > 6 else 20000
r = next(x for x in d['results'] if x['page'] == page and x['profile'] == prof and x['pass'] == pas and x['run'] == run)
rows = []
for q in r['requests']:
    if q['type'] == 'Document' or (q['bytes'] or 0) >= floor:
        u = q['url'].split('?')[0].replace('https://skippercast.com', '')
        if '?' in q['url'] and 'skippercast.com' in q['url']:
            u += '?' + q['url'].split('?')[1][:40]
        rows.append((q['startMs'], f"{q['startMs']:>7} → {q['endMs'] if q['endMs'] is not None else '…':>7}  {(q['bytes'] or 0)/1e3:>9.1f} KB  {q['kind']:6s} {u[:95]}{'  [' + q['failed'] + ']' if q['failed'] else ''}"))
for name, key in [('FCP', 'fcpMs'), ('LCP', 'lcpMs'), ('brief shown', 'readyMs'), ('map canvas', 'mapCanvasMs'), ('canvas quiet (proxy, not map usable)', 'canvasQuietMs')]:
    if r.get(key) is None and key == 'canvasQuietMs':
        key = 'mapUsableMs'
    if r.get(key) is not None:
        rows.append((r[key], f"{r[key]:>7}   ── {name} ──"))
for _, line in sorted(rows, key=lambda x: x[0]):
    print(line)
print(f"requests={r['requestCount']} bytes={r['bytesTotal']/1e6:.2f} MB tbt={r['tbtMs']} longest task={r['longestTaskMs']} script={r['scriptMs']} ms")
