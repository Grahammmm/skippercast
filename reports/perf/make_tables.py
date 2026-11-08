#!/usr/bin/env python3
"""PERF-BASELINE-1: Markdown tables for the report from raw/summary.json (summarize.py) and raw/extras.json (extras.py).

Usage: python3 reports/perf/make_tables.py <section>   section = live-main | live-kinds | live-extras | heaviest |
       layers-main | layers-kinds | layers-extras
"""
import json
import sys
from pathlib import Path

RAW = Path('reports/perf/raw')
S = json.loads((RAW / 'summary.json').read_text())['groups']
E = {(r['page'], r['profile'], r['pass']): r for r in json.loads((RAW / 'extras.json').read_text())}
KINDS = ['html', 'js', 'css', 'json', 'tiles', 'fonts', 'images', 'other']
LIVE_ORDER = ['landing', 'brief', 'map-home'] + [f'live-layer-{x}' for x in ['none', 'swell', 'currents', 'stations', 'water-temp', 'chlorophyll', 'seafloor']]
LAYER_ORDER = ['layer-base-medium', 'layer-wind', 'layer-current', 'layer-tide', 'layer-sst', 'layer-chlorophyll', 'layer-bathy-2m', 'layer-bathy-2m-z12']
PROF = {'desktop': 0, 'phone': 1, 'phone-wifi': 2}


def ms(v):
    return '–' if v is None else f'{v / 1000:.2f} s' if v >= 1000 else f'{int(v)} ms'


def b(v):
    if v is None:
        return '–'
    return f'{v / 1e6:.2f} MB' if v >= 1e6 else f'{v / 1e3:.0f} KB' if v >= 1e3 else f'{int(v)} B'


def rows(order):
    sel = [g for g in S if g['page'] in order]
    return sorted(sel, key=lambda g: (order.index(g['page']), PROF.get(g['profile'], 9), g['pass'] != 'cold'))


def main_table(order, live):
    out = ['| page | profile | pass | FCP | LCP | ' + ('brief shown | ' if live else '') + 'canvas + quiet thread (proxy) | TBT to proxy | CLS | longest task | JS script time | JS heap | requests | bytes | req. ≤ LCP | PMTiles req / bytes' + (' | export loaded' if live else '') + ' |',
           '|' + '---|' * (16 if live else 14)]
    for g in rows(order):
        cells = [g['page'], g['profile'], g['pass'], ms(g['fcpMs']), ms(g['lcpMs'])]
        if live:
            cells.append(ms(g['readyMs']))
        cells += [ms(g['mapUsableMs']), ms(g['tbtMs']), f"{g['cls']:.3f}" if g['cls'] is not None else '–', ms(g['longestTaskMs']), ms(g['scriptMs']),
                  b(g['jsHeapUsedBytes']), str(g['requestCount']), b(g['bytesTotal']), str(g['requestsBeforeLcp']), f"{g['pmtilesRangeRequests']} / {b(g['pmtilesBytes'])}"]
        if live:
            cells.append(f"{g['habitatExportLoaded']}/{g['runs']}")
        out.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(out)


def kinds_table(order):
    out = ['| page | profile | pass | ' + ' | '.join(KINDS) + ' |', '|---|---|---|' + '---|' * len(KINDS)]
    for g in rows(order):
        out.append(f"| {g['page']} | {g['profile']} | {g['pass']} | " + ' | '.join(f"{b(g['bytesByKind'][k])} ({int(g['requestsByKind'][k])})" for k in KINDS) + ' |')
    return '\n'.join(out)


def extras_table(order):
    out = ['| page | profile | pass | network req / bytes | no-store req / bytes | third-party req / bytes | req. ≤ FCP | observed window (network quiet) |',
           '|---|---|---|---|---|---|---|---|']
    for g in rows(order):
        e = E.get((g['page'], g['profile'], g['pass']))
        if not e:
            continue
        out.append(f"| {g['page']} | {g['profile']} | {g['pass']} | {int(e['warmNetworkRequests'])} / {b(e['warmNetworkBytes'])} | {int(e['noStoreRequests'])} / {b(e['noStoreBytes'])} | "
                   f"{int(e['thirdPartyRequests'])} / {b(e['thirdPartyBytes'])} | {e['requestsBeforeFcp']} | {ms(e['settledMs'])} |")
    return '\n'.join(out)


def heaviest(order):
    out = []
    for g in rows(order):
        if g['pass'] != 'cold':
            continue
        out.append(f"**{g['page']} · {g['profile']} · cold** (run {g['medianRun']}):")
        out.append('')
        out.append('| # | bytes | type | start → end | URL |')
        out.append('|---|---|---|---|---|')
        for i, h in enumerate(g['heaviest'], 1):
            u = h['url']
            u = u.split('?')[0] + ('?…' if '?' in u else '')
            u = u.replace('https://skippercast.com', '').replace('http://127.0.0.1:18772', '').replace('http://127.0.0.1:18781', '')
            out.append(f"| {i} | {b(h['bytes'])} | {h['kind']} | {h['startMs']} → {h['endMs'] if h['endMs'] is not None else '…'} ms | `{u[:110]}` |")
        out.append('')
    return '\n'.join(out)


sec = sys.argv[1]
print({'live-main': lambda: main_table(LIVE_ORDER, True), 'live-kinds': lambda: kinds_table(LIVE_ORDER), 'live-extras': lambda: extras_table(LIVE_ORDER),
       'heaviest': lambda: heaviest(LIVE_ORDER) + '\n' + heaviest(LAYER_ORDER),
       'layers-main': lambda: main_table(LAYER_ORDER, False), 'layers-kinds': lambda: kinds_table(LAYER_ORDER), 'layers-extras': lambda: extras_table(LAYER_ORDER)}[sec]())
