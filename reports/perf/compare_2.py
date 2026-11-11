#!/usr/bin/env python3
"""SC1922-12: read-only comparison of measure.mjs raw page-load files (stdout only, standard library only).

Usage:
  python3 reports/perf/compare_2.py [options] RAW.json [RAW.json ...]

  --baseline-summary PATH        committed reports/perf/raw/summary.json (group medians and *_all arrays to compare against)
  --baseline-raw PATH            raw file(s) the baseline summary was made from (repeatable); needed for the baseline's JS ranges
                                 and for the baseline's ds582 / string-catalogue / Aerial figures
  --catalogue-asset [LABEL=]NAME catalogue asset of the build that produced RAW (repeatable; path or basename; query stripped).
                                 LABEL is 'english' (default: the shared/English string asset) or 'spanish' (the Spanish table).
                                 With no 'spanish' asset named, Spanish bytes are reported as unknown, never as zero.
  --baseline-catalogue-asset ... the same, for the --baseline-raw files (e.g. strings.dae9ed705a.js)
  --json                         print the full result as JSON instead of tables

Nothing is written: no output file, no network, no import of the baseline scripts. Malformed or schema-less input stops
with exit status 2 and a message. Runs that carry an 'error' are counted and listed, never treated as measured; a null
metric is 'unmeasured' (not zero) and is left out of the median, with its non-null count shown.
Inline data:/blob: URLs are not network transfers and are excluded, as reports/perf/summarize.py does. Bytes are the
recorded CDP encodedDataLength (transferred bytes), never file sizes. Aerial timing is 'first Aerial tile received':
the earliest response end among imagery.nationalmap.gov requests, a network proxy and not a draw time.
"""
import json
import os
import statistics
import sys
from collections import defaultdict

METRICS = [('fcpMs', 'FCP ms'), ('lcpMs', 'LCP ms'), ('tbtMs', 'TBT ms'), ('readyMs', 'brief shown (readyMs) ms'),
           ('requestCount', 'requests'), ('bytesTotal', 'bytes'), ('jsBytes', 'JS bytes'), ('jsRequests', 'JS requests')]
EXTRA = [('ds582', 'ds582 requests'), ('stringsEn', 'string catalogue bytes (English/shared)'),
         ('stringsEs', 'string catalogue bytes (Spanish table)'), ('stringsEnRequests', 'string catalogue requests (English/shared)'),
         ('aerialCount', 'imagery.nationalmap.gov requests'), ('aerialBytes', 'imagery.nationalmap.gov bytes'),
         ('aerialFirstEnd', 'first Aerial tile received ms (network proxy, not a draw time)')]
UNIT = {'fcpMs': 'SC1407-03/-04/-08/-10 combined (also -06/-07/-09)', 'lcpMs': 'SC1407-03/-04/-08/-10 combined', 'tbtMs': 'SC1407-03/-04/-08/-10 combined',
        'readyMs': 'SC1407-03/-04/-08/-10 combined', 'requestCount': 'SC1407-03/-04/-08/-10 combined (also -06/-07/-09)',
        'bytesTotal': 'SC1407-03/-04/-08/-10 combined (also -06/-07/-09)', 'jsBytes': 'SC1407-08/-10 (also -03/-04/-09)',
        'jsRequests': 'SC1407-08/-10 (also -03/-04/-09)', 'ds582': 'SC1407-06', 'stringsEn': 'SC1407-09', 'stringsEs': 'SC1407-09',
        'stringsEnRequests': 'SC1407-09', 'aerialCount': 'SC1407-07', 'aerialBytes': 'SC1407-07', 'aerialFirstEnd': 'SC1407-07'}


def refuse(msg):
    sys.stderr.write('compare_2.py: ' + msg + '\n')
    sys.exit(2)


def load(path):
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        refuse(f'cannot read {path}: {e}')
    if not isinstance(doc, dict) or not isinstance(doc.get('results'), list):
        refuse(f'{path} has no "results" list (not a measure.mjs raw file)')
    for i, r in enumerate(doc['results']):
        if not isinstance(r, dict) or not all(k in r for k in ('page', 'profile', 'pass', 'run')):
            refuse(f'{path} result #{i} lacks page/profile/pass/run')
        if 'error' not in r and not isinstance(r.get('requests'), list):
            refuse(f'{path} result #{i} ({r["page"]} {r["profile"]} {r["pass"]} #{r["run"]}) has no request list and no error')
    return doc


def split_assets(values, what):
    out = {'english': [], 'spanish': []}
    for v in values:
        label, name = ('english', v)
        if '=' in v:
            label, name = v.split('=', 1)
        if label not in out:
            refuse(f'{what}: unknown label "{label}" (use english= or spanish=)')
        base = os.path.basename(name.split('?')[0])
        if not base:
            refuse(f'{what}: empty asset name in "{v}"')
        out[label].append(base)
    return out


def base_name(url):
    return os.path.basename(url.split('?')[0].split('#')[0])


def derive(r, assets):
    """Per-load figures from one run's request list (inline data:/blob: excluded, nothing de-duplicated)."""
    reqs = [q for q in r['requests'] if not q['url'].startswith(('data:', 'blob:'))]
    js = [q for q in reqs if q.get('kind') == 'js']
    en = [q for q in reqs if base_name(q['url']) in assets['english']] if assets['english'] else None
    es = [q for q in reqs if base_name(q['url']) in assets['spanish']] if assets['spanish'] else None
    aerial = [q for q in reqs if 'imagery.nationalmap.gov' in q['url']]
    ends = [q['endMs'] for q in aerial if q.get('endMs') is not None and not q.get('failed')]
    return {
        'fcpMs': r.get('fcpMs'), 'lcpMs': r.get('lcpMs'), 'tbtMs': r.get('tbtMs'), 'readyMs': r.get('readyMs'),
        'requestCount': len(reqs), 'bytesTotal': sum(q.get('bytes') or 0 for q in reqs),
        'jsBytes': sum(q.get('bytes') or 0 for q in js), 'jsRequests': len(js),
        'ds582': sum(1 for q in reqs if 'biosds582' in q['url']),
        'stringsEn': None if en is None else sum(q.get('bytes') or 0 for q in en),
        'stringsEnRequests': None if en is None else len(en),
        'stringsEs': None if es is None else sum(q.get('bytes') or 0 for q in es),   # None = Spanish asset identity unknown, not zero
        'aerialCount': len(aerial), 'aerialBytes': sum(q.get('bytes') or 0 for q in aerial),
        'aerialFirstEnd': min(ends) if ends else None,   # None = no completed response end ("unavailable")
        'aerialFailed': sum(1 for q in aerial if q.get('failed')),
        'aerialNoEnd': sum(1 for q in aerial if q.get('endMs') is None),
        'stringsEnNames': sorted({base_name(q['url']) for q in (en or [])}), 'stringsEsNames': sorted({base_name(q['url']) for q in (es or [])}),
        'settled': r.get('settled'), 'fromCacheAerial': sum(1 for q in aerial if q.get('fromCache')),
    }


def rnd(m):
    return round(m, 4) if isinstance(m, float) and m < 10 else round(m)


def stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {'n': 0, 'of': len(values), 'median': None, 'min': None, 'max': None}
    return {'n': len(vals), 'of': len(values), 'median': rnd(statistics.median(vals)), 'min': min(vals), 'max': max(vals)}


def group_docs(paths, assets):
    groups = defaultdict(lambda: {'loads': [], 'errors': []})
    meta = []
    for p in paths:
        doc = load(p)
        meta.append({'file': p, 'base': doc.get('base'), 'chromium': doc.get('chromium'), 'startedAt': doc.get('startedAt'),
                     'finishedAt': doc.get('finishedAt'), 'argv': doc.get('argv'), 'results': len(doc['results'])})
        for r in doc['results']:
            key = (r['page'], r['profile'], r['pass'])
            if 'error' in r:
                groups[key]['errors'].append({'run': r['run'], 'error': r['error']})
                continue
            d = derive(r, assets)
            d['run'] = r['run']
            groups[key]['loads'].append(d)
    out = {}
    for key, g in groups.items():
        row = {'runs': len(g['loads']), 'errors': g['errors'], 'perLoad': g['loads'], 'unsettled': sum(1 for d in g['loads'] if d['settled'] is False)}
        for m, _ in METRICS + EXTRA:
            row[m] = stats([d[m] for d in g['loads']])
        out[key] = row
    return out, meta


def fmt(s):
    if s['median'] is None:
        return 'unmeasured' if s['of'] else '-'
    rng = f"{s['min']}" if s['min'] == s['max'] else f"{s['min']}-{s['max']}"
    note = '' if s['n'] == s['of'] else f" [{s['n']}/{s['of']} measured]"
    return f"{s['median']} ({rng}){note}"


def main(argv):
    paths, opts = [], {'baseline-raw': [], 'catalogue-asset': [], 'baseline-catalogue-asset': [], 'baseline-summary': None, 'json': False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--json':
            opts['json'] = True
        elif a in ('--baseline-summary', '--baseline-raw', '--catalogue-asset', '--baseline-catalogue-asset'):
            if i + 1 >= len(argv):
                refuse(a + ' needs a value')
            i += 1
            if a == '--baseline-summary':
                opts['baseline-summary'] = argv[i]
            else:
                opts[a[2:]].append(argv[i])
        elif a.startswith('--'):
            refuse('unknown option ' + a)
        else:
            paths.append(a)
        i += 1
    if not paths:
        refuse('give at least one raw JSON path (see the module docstring)')
    assets = split_assets(opts['catalogue-asset'], '--catalogue-asset')
    base_assets = split_assets(opts['baseline-catalogue-asset'], '--baseline-catalogue-asset')
    new, meta = group_docs(paths, assets)
    base = base_meta = summary = None
    if opts['baseline-raw']:
        base, base_meta = group_docs(opts['baseline-raw'], base_assets)
    if opts['baseline-summary']:
        try:
            with open(opts['baseline-summary']) as f:
                summary = {(g['page'], g['profile'], g['pass']): g for g in json.load(f)['groups']}
        except (OSError, ValueError, KeyError, TypeError) as e:
            refuse(f'cannot read baseline summary {opts["baseline-summary"]}: {e}')

    result = {'inputs': meta, 'catalogueAssets': assets, 'baselineInputs': base_meta, 'baselineCatalogueAssets': base_assets, 'groups': [], 'worse': [], 'summaryMismatches': []}
    for key in sorted(new):
        g = new[key]
        row = {'page': key[0], 'profile': key[1], 'pass': key[2], 'runs': g['runs'], 'errorRuns': g['errors'], 'unsettledRuns': g['unsettled'], 'metrics': {}, 'baseline': {}}
        for m, _ in METRICS + EXTRA:
            row['metrics'][m] = g[m]
        row['perLoad'] = g['perLoad']
        bg = base.get(key) if base else None
        bs = summary.get(key) if summary else None
        if bg:
            row['baselineRuns'] = bg['runs']
            for m, _ in METRICS + EXTRA:
                row['baseline'][m] = bg[m]
        if bs:
            # the committed summary is authoritative for FCP/LCP/TBT/ready/request/byte medians and ranges (its *_all arrays)
            row['baselineSummaryRuns'] = bs['runs']
            for m, k in (('fcpMs', 'fcpMs'), ('lcpMs', 'lcpMs'), ('tbtMs', 'tbtMs'), ('readyMs', 'readyMs'), ('requestCount', 'requestCount'), ('bytesTotal', 'bytesTotal')):
                st = stats(bs.get(k + '_all', []))
                if bg and bg[m] != st:
                    result['summaryMismatches'].append({'group': key, 'metric': m, 'rawDerived': bg[m], 'summary': st})
                row['baseline'][m] = st
        for m, _ in METRICS + EXTRA:
            b, n = row['baseline'].get(m), row['metrics'][m]
            if b and b['median'] is not None and n['median'] is not None and n['median'] > b['median']:
                result['worse'].append({'page': key[0], 'profile': key[1], 'pass': key[2], 'metric': m, 'baselineMedian': b['median'], 'newMedian': n['median'], 'delta': rnd(n['median'] - b['median']), 'unit': UNIT[m]})
        result['groups'].append(row)

    if opts['json']:
        print(json.dumps(result, indent=1, sort_keys=True))
        return
    print('Inputs:')
    for m in meta:
        print(f"  {m['file']}: base {m['base']}, {m['chromium']}, started {m['startedAt']}, finished {m['finishedAt']}, {m['results']} results")
    print('Catalogue assets (new):', json.dumps(assets), '| baseline:', json.dumps(base_assets))
    print('Aerial timing below is "first Aerial tile received", a network proxy and not a draw time. Spanish bytes: n/a = asset identity unknown.')
    for row in result['groups']:
        print(f"\n## {row['page']} / {row['profile']} / {row['pass']}: {row['runs']} successful run(s), {len(row['errorRuns'])} error run(s), {row['unsettledRuns']} not settled")
        for e in row['errorRuns']:
            print(f"   error run #{e['run']}: {e['error'][:160]}")
        print('| metric | unit | new: median (min-max) | baseline: median (min-max) | delta of medians |')
        print('|---|---|---|---|---|')
        for m, label in METRICS + EXTRA:
            n, b = row['metrics'][m], row['baseline'].get(m)
            d = '' if not (b and b['median'] is not None and n['median'] is not None) else f"{rnd(n['median'] - b['median']):+}"
            nn = fmt(n) if n['of'] and (n['median'] is not None or m not in ('stringsEn', 'stringsEs', 'stringsEnRequests')) else 'n/a (asset identity unknown)'
            if m == 'stringsEs' and n['of'] and n['median'] is None and n['n'] == 0:
                nn = 'n/a (Spanish asset identity unknown)'
            bb = fmt(b) if b else 'not given'
            if b and m in ('stringsEs', 'stringsEn', 'stringsEnRequests') and b['median'] is None:
                bb = 'n/a (asset identity unknown)'
            print(f"| {label} | {UNIT[m]} | {nn} | {bb} | {d} |")
        print('per load (run: ds582, stringsEn B, stringsEs B, aerial n / B / first end, aerial failed / no end, JS req / B, requests):')
        for d in row['perLoad']:
            print(f"   #{d['run']}: ds582={d['ds582']} stringsEn={d['stringsEn']} {d['stringsEnNames']} stringsEs={d['stringsEs']} {d['stringsEsNames']} aerial={d['aerialCount']}/{d['aerialBytes']}/{d['aerialFirstEnd']} "
                  f"aerialFailed={d['aerialFailed']} aerialNoEnd={d['aerialNoEnd']} aerialFromCache={d['fromCacheAerial']} js={d['jsRequests']}/{d['jsBytes']} requests={d['requestCount']}")
    if summary is not None:
        print('\nBaseline summary vs figures re-derived from the baseline raw files:', 'no mismatches' if not result['summaryMismatches'] and base else (f"{len(result['summaryMismatches'])} mismatch(es): " + json.dumps(result['summaryMismatches']) if base else 'no baseline raw given, not checked'))
    print('\nMetrics whose new median is higher (worse) than the baseline median (lab numbers on a shared host; not a pass or fail):')
    if not result['worse']:
        print('  none')
    for w in result['worse']:
        print(f"  {w['page']}/{w['profile']}/{w['pass']} {w['metric']}: {w['baselineMedian']} -> {w['newMedian']} ({w['delta']:+}) [{w['unit']}]")


if __name__ == '__main__':
    main(sys.argv[1:])
