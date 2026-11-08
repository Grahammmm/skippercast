#!/usr/bin/env python3
"""PERF-BASELINE-1: medians of measure.mjs runs -> reports/perf/raw/summary.json and Markdown tables on stdout.

Usage: python3 reports/perf/summarize.py reports/perf/raw/live-desktop.json reports/perf/raw/live-phone.json ... > tables.md
Each (page, profile, pass) group's metrics are the median of its runs (3 by default). The 10 heaviest requests
are taken from the run whose canvas-quiet time (else LCP) is the group's median.

PR-1767 fix: request counts, bytes, bytes by type, PMTiles totals and the heaviest list are recomputed here from each
run's request list with inline data:/blob: URLs excluded (they are not network transfers), so raw files written by the
earlier measure.mjs give the same numbers as new ones. 'canvasQuietMs' (legacy raw key 'mapUsableMs') is a proxy, not
map usability; see the report's method section.
"""
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

METRICS = ['layerDataStartMs', 'layerDataEndMs', 'fcpMs', 'lcpMs', 'readyMs', 'mapCanvasMs', 'canvasQuietMs', 'tbtMs', 'cls', 'longestTaskMs', 'scriptMs', 'taskMs',
           'jsHeapUsedBytes', 'requestCount', 'bytesTotal', 'requestsBeforeFcp', 'requestsBeforeLcp', 'clientRedirectMs', 'settledMs']
KINDS = ['html', 'js', 'css', 'json', 'tiles', 'fonts', 'images', 'other']


def is_inline(q):
    return q['url'].startswith(('data:', 'blob:'))


def normalise(r):
    """Copy of a run with the network-only figures recomputed (inline data:/blob: URLs excluded)."""
    r = dict(r)
    r['canvasQuietMs'] = r['canvasQuietMs'] if 'canvasQuietMs' in r else r.get('mapUsableMs')
    reqs = [q for q in r['requests'] if not is_inline(q)]
    r['requests'] = reqs
    r['requestCount'] = len(reqs)
    r['bytesTotal'] = sum(q['bytes'] or 0 for q in reqs)
    by = {}
    for q in reqs:
        k = by.setdefault(q['kind'], {'requests': 0, 'bytes': 0, 'fromCache': 0})
        k['requests'] += 1
        k['bytes'] += q['bytes'] or 0
        k['fromCache'] += 1 if q['fromCache'] else 0
    r['byKind'] = by
    pm = [q for q in reqs if '.pmtiles' in q['url'] and q['range']]
    r['pmtiles'] = {'rangeRequests': len(pm), 'bytes': sum(q['bytes'] or 0 for q in pm), 'fromCache': sum(1 for q in pm if q['fromCache'])}
    r['heaviest'] = [{'url': q['url'], 'kind': q['kind'], 'bytes': q['bytes'], 'startMs': q['startMs'], 'endMs': q['endMs']}
                     for q in sorted(reqs, key=lambda q: -(q['bytes'] or 0))[:10]]
    # Layer data finished: the last end time among the large data requests of a layer test page (waterfall-derived).
    data = [q for q in reqs if q['kind'] == 'json' and (q['bytes'] or 0) >= 100000 and q['endMs'] is not None]
    r['layerDataStartMs'] = min((q['startMs'] for q in data), default=None)
    r['layerDataEndMs'] = max((q['endMs'] for q in data), default=None)
    n = len(r['requests'])
    r['requestsBeforeLcp'] = None if r.get('lcpMs') is None else sum(1 for q in reqs if q['startMs'] <= r['lcpMs'])
    r['requestsBeforeFcp'] = None if r.get('fcpMs') is None else sum(1 for q in reqs if q['startMs'] <= r['fcpMs'])
    return r


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
        groups[(r['page'], r['profile'], r['pass'])].append(normalise(r))

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
    key = 'canvasQuietMs' if row['canvasQuietMs'] is not None else 'lcpMs'
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


print('| page | profile | pass | FCP | LCP | brief shown | canvas quiet (proxy) | TBT to proxy | CLS | longest task | JS main-thread (script) | heap | requests | bytes | req. before LCP | PMTiles range req / bytes | 15 MB export loaded |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for r in summary:
    print(f"| {r['page']} | {r['profile']} | {r['pass']} | {fmt_ms(r['fcpMs'])} | {fmt_ms(r['lcpMs'])} | {fmt_ms(r['readyMs'])} | {fmt_ms(r['canvasQuietMs'])} | {fmt_ms(r['tbtMs'])} | {r['cls']} | {fmt_ms(r['longestTaskMs'])} | {fmt_ms(r['scriptMs'])} | {fmt_b(r['jsHeapUsedBytes'])} | {r['requestCount']} | {fmt_b(r['bytesTotal'])} | {r['requestsBeforeLcp']} | {r['pmtilesRangeRequests']} / {fmt_b(r['pmtilesBytes'])} | {r['habitatExportLoaded']}/{r['runs']} |")
print()
print('| page | profile | pass | ' + ' | '.join(KINDS) + ' |')
print('|---|---|---|' + '---|' * len(KINDS))
for r in summary:
    print(f"| {r['page']} | {r['profile']} | {r['pass']} | " + ' | '.join(f"{fmt_b(r['bytesByKind'][k])} ({r['requestsByKind'][k]})" for k in KINDS) + ' |')
