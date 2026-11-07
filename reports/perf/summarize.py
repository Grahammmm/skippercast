#!/usr/bin/env python3
"""PERF-BASELINE-1: medians of measure.mjs runs -> reports/perf/raw/summary.json and Markdown tables on stdout.

Usage: python3 reports/perf/summarize.py reports/perf/raw/live-desktop.json reports/perf/raw/live-phone.json ... > tables.md
Each (page, profile, pass) group's metrics are the median of its runs (3 by default). The 10 heaviest requests
are taken from the run whose map-usable time (else LCP) is the group's median.
"""
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

METRICS = ['fcpMs', 'lcpMs', 'readyMs', 'mapCanvasMs', 'mapUsableMs', 'tbtMs', 'cls', 'longestTaskMs', 'scriptMs', 'taskMs',
           'jsHeapUsedBytes', 'requestCount', 'bytesTotal', 'requestsBeforeFcp', 'requestsBeforeLcp', 'clientRedirectMs', 'settledMs']
KINDS = ['html', 'js', 'css', 'json', 'tiles', 'fonts', 'images', 'other']


def med(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    m = statistics.median(vals)
    return round(m, 4) if isinstance(m, float) and m < 10 else round(m)


groups = defaultdict(list)
sources = []
for path in sys.argv[1:]:
    doc = json.load(gzip.open(path, 'rt') if path.endswith('.gz') else open(path))
    sources.append({'file': path, 'base': doc['base'], 'chromium': doc['chromium'], 'startedAt': doc['startedAt'], 'finishedAt': doc.get('finishedAt'), 'argv': doc['argv']})
    for r in doc['results']:
        if 'error' in r:
            continue
        groups[(r['page'], r['profile'], r['pass'])].append(r)

summary = []
for (page, prof, pas), runs in sorted(groups.items()):
    row = {'page': page, 'profile': prof, 'pass': pas, 'runs': len(runs), 'settledAll': all(r['settled'] for r in runs)}
    for m in METRICS:
        row[m] = med([r.get(m) for r in runs])
        row[m + '_all'] = [r.get(m) for r in runs]
    row['bytesByKind'] = {k: med([r['byKind'].get(k, {}).get('bytes', 0) for r in runs]) for k in KINDS}
    row['requestsByKind'] = {k: med([r['byKind'].get(k, {}).get('requests', 0) for r in runs]) for k in KINDS}
    row['pmtilesRangeRequests'] = med([r['pmtiles']['rangeRequests'] for r in runs])
    row['pmtilesBytes'] = med([r['pmtiles']['bytes'] for r in runs])
    row['habitatExportLoaded'] = sum(1 for r in runs if any('habitat-export' in q['url'] for q in r['requests']))
    key = 'mapUsableMs' if row['mapUsableMs'] is not None else 'lcpMs'
    target = row[key]
    pick = min(runs, key=lambda r: abs((r.get(key) or 0) - (target or 0)))
    row['medianRun'] = pick['run']
    row['heaviest'] = pick['heaviest']
    summary.append(row)

out = Path('reports/perf/raw/summary.json')
out.write_text(json.dumps({'sources': sources, 'groups': summary}, indent=1))


def fmt_ms(v):
    return '–' if v is None else f'{v / 1000:.2f} s' if v >= 1000 else f'{v} ms'


def fmt_b(v):
    if v is None:
        return '–'
    if v >= 1e6:
        return f'{v / 1e6:.2f} MB'
    if v >= 1e3:
        return f'{v / 1e3:.0f} KB'
    return f'{v} B'


print('| page | profile | pass | FCP | LCP | brief shown | map usable | TBT | CLS | longest task | JS main-thread (script) | heap | requests | bytes | req. before LCP | PMTiles range req / bytes | 15 MB export loaded |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for r in summary:
    print(f"| {r['page']} | {r['profile']} | {r['pass']} | {fmt_ms(r['fcpMs'])} | {fmt_ms(r['lcpMs'])} | {fmt_ms(r['readyMs'])} | {fmt_ms(r['mapUsableMs'])} | {fmt_ms(r['tbtMs'])} | {r['cls']} | {fmt_ms(r['longestTaskMs'])} | {fmt_ms(r['scriptMs'])} | {fmt_b(r['jsHeapUsedBytes'])} | {r['requestCount']} | {fmt_b(r['bytesTotal'])} | {r['requestsBeforeLcp']} | {r['pmtilesRangeRequests']} / {fmt_b(r['pmtilesBytes'])} | {r['habitatExportLoaded']}/{r['runs']} |")
print()
print('| page | profile | pass | ' + ' | '.join(KINDS) + ' |')
print('|---|---|---|' + '---|' * len(KINDS))
for r in summary:
    print(f"| {r['page']} | {r['profile']} | {r['pass']} | " + ' | '.join(f"{fmt_b(r['bytesByKind'][k])} ({r['requestsByKind'][k]})" for k in KINDS) + ' |')
