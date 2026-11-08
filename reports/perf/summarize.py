#!/usr/bin/env python3
"""PERF-BASELINE-1: medians of measure.mjs runs -> reports/perf/raw/summary.json and Markdown tables on stdout.

Usage: python3 reports/perf/summarize.py reports/perf/raw/live-desktop.json reports/perf/raw/live-phone.json ... > tables.md
Each (page, profile, pass) group's metrics are the median of its runs (3 by default). The 10 heaviest requests
are taken from the run whose network bytes are the group's median.

Round 2 (review item 3): inline `data:` URLs never cross the network, so they are removed from every request count,
byte total, by-type table, PMTiles figure and heaviest-request list; they are reported on their own (inlineData*).
Transfer length of the rest = CDP encodedDataLength; a request the page cancels after reading what it needs (the reef
export, ERR_ABORTED) counts the bytes that had arrived; a request still open at the end of the run counts the bytes
received so far; a request without a length counts 0 and is listed in `unknownLength`; a cache hit counts 0.
"""
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

METRICS = ['fcpMs', 'lcpMs', 'readyMs', 'mapCanvasMs', 'mapUsableMs', 'tbtMs', 'cls', 'longestTaskMs', 'scriptMs', 'taskMs',
           'jsHeapUsedBytes', 'requestCount', 'bytesTotal', 'requestsBeforeFcp', 'requestsBeforeLcp', 'clientRedirectMs', 'settledMs',
           'inlineDataCount', 'inlineDataBytes', 'unknownLength', 'abortedBytes']
KINDS = ['html', 'js', 'css', 'json', 'tiles', 'fonts', 'images', 'other']


def med(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    m = statistics.median(vals)
    return round(m, 4) if isinstance(m, float) and m < 10 else round(m)


def clean(r):
    """Recompute counts, bytes, by-kind, PMTiles figures and heaviest from the network requests only (no data: URLs)."""
    reqs = r['requests']
    net = [q for q in reqs if not q['url'].startswith('data:')]
    inline = [q for q in reqs if q['url'].startswith('data:')]
    r['requestCount'] = len(net)
    r['bytesTotal'] = sum(q['bytes'] or 0 for q in net)
    by = {}
    for q in net:
        k = by.setdefault(q['kind'], {'requests': 0, 'bytes': 0, 'fromCache': 0})
        k['requests'] += 1
        k['bytes'] += q['bytes'] or 0
        k['fromCache'] += 1 if q['fromCache'] else 0
    r['byKind'] = by
    pm = [q for q in net if '.pmtiles' in q['url'] and q.get('range')]
    r['pmtiles'] = {'rangeRequests': len(pm), 'bytes': sum(q['bytes'] or 0 for q in pm), 'fromCache': sum(1 for q in pm if q['fromCache'])}
    r['heaviest'] = [{'url': q['url'], 'kind': q['kind'], 'bytes': q['bytes'], 'startMs': q['startMs'], 'endMs': q['endMs']}
                     for q in sorted(net, key=lambda q: -(q['bytes'] or 0))[:10]]
    r['requestsBeforeLcp'] = None if r.get('lcpMs') is None else sum(1 for q in net if q['startMs'] <= r['lcpMs'])
    r['requestsBeforeFcp'] = None if r.get('fcpMs') is None else sum(1 for q in net if q['startMs'] <= r['fcpMs'])
    r['inlineDataCount'] = len(inline)
    r['inlineDataBytes'] = sum(q['bytes'] or 0 for q in inline)
    r['unknownLength'] = sum(1 for q in net if q['bytes'] is None and not q['fromCache'])
    r['abortedBytes'] = sum(q['bytes'] or 0 for q in net if q.get('failed'))
    return r


groups = defaultdict(list)
sources = []
for path in sys.argv[1:]:
    doc = json.load(gzip.open(path, 'rt') if path.endswith('.gz') else open(path))
    sources.append({'file': path, 'base': doc['base'], 'chromium': doc['chromium'], 'startedAt': doc['startedAt'], 'finishedAt': doc.get('finishedAt'), 'argv': doc['argv']})
    for r in doc['results']:
        if 'error' in r:
            continue
        groups[(r['page'], r['profile'], r['pass'])].append(clean(r))

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
    target = row['bytesTotal']
    pick = min(runs, key=lambda r: abs(r['bytesTotal'] - target))
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
