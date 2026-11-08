#!/usr/bin/env python3
"""PERF-BASELINE-1 round 2: Markdown tables for the readiness runs (analyse.py output).

Usage: python3 reports/perf/ready_tables.py <section> [raw/ready-summary.json]
  section = live | layers | duty | status
Every number is the median of the 3 runs of a (page, profile, pass) group; a run that never reached the state counts as
infinitely late, so a median is "not reached" when two of three runs did not reach it (the per-run values are in the JSON).
"""
import json
import sys
from pathlib import Path

G = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else 'reports/perf/raw/ready-summary.json').read_text())['groups']
LIVE_ORDER = ['brief', 'map-home-returning'] + [f'live-layer-{x}' for x in ['none', 'swell', 'currents', 'stations', 'water-temp', 'chlorophyll', 'seafloor']]
LAYER_ORDER = ['layer-base-medium', 'layer-wind', 'layer-current', 'layer-tide', 'layer-sst', 'layer-chlorophyll', 'layer-bathy-2m', 'layer-bathy-2m-z12']
PROF = {'desktop': 0, 'phone': 1, 'phone-wifi': 2}


def ms(v, none='not reached'):
    return none if v is None else f'{v / 1000:.2f} s' if v >= 1000 else f'{int(v)} ms'


def rows(order):
    sel = [g for g in G if g['page'] in order]
    return sorted(sel, key=lambda g: (order.index(g['page']), PROF.get(g['profile'], 9), g['pass'] != 'cold'))


def timing(order):
    out = ['| page | profile | pass | runs ok | FCP | map painted | brief shown | map visually complete | **map usable** (painted + input ≤ 200 ms) | no freeze (long task ≥ 200 ms) after | long-task time | max input delay | TBT to usable | drag response |',
           '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for g in rows(order):
        comp = 'animated' if g['animated'] >= 2 else ms(g['completeMs'])
        out.append(f"| {g['page']} | {g['profile']} | {g['pass']} | {g['ok']}/{g['runs']} | {ms(g['fcpMs'], '–')} | {ms(g['paintedMs'])} | {ms(g['briefShownMs'], '–')} | {comp} | **{ms(g['usableMs'])}** | "
                   f"{ms(g['freeFromMs'])} | {ms(g['longTaskTotalMs'], '–')} | {ms(g['maxInputDelayMs'], '–')} | {ms(g['tbtMs'], '–')}{'*' if any(g.get('tbtMs_all', [])) and g['usableMs'] is None else ''} | {ms(g['responseMs'], 'no response')} |")
    return '\n'.join(out)


def layers(order):
    out = ['| page | profile | layer-specific requests | their bytes | layer data fully arrived | layer visibly differs from layer-off | requests failed | notes |',
           '|---|---|---|---|---|---|---|---|']
    for g in rows(order):
        if g['pass'] != 'cold' or 'layerReference' not in g:
            continue
        diff = '–' if g['layerVisibleDiff'] is None else f"{g['layerVisibleDiff'] * 100:.0f} % of pixels"
        nb = g['layerBytes']
        size = f'{nb / 1e6:.2f} MB' if nb >= 1e6 else f'{nb / 1e3:.0f} KB' if nb >= 1e3 else f'{int(nb)} B'
        note = ', '.join(g['layerExamples'][:2]) if g['layerExamples'] else 'data is inline in the page (no request)'
        out.append(f"| {g['page']} | {g['profile']} | {int(g['layerRequests'])} | {size} | {ms(g['layerDoneMs'], '–' if not g['layerRequests'] else 'not reached')} | {diff} | {g['layerFailed']} | {note} |")
    return '\n'.join(out)


def duty(order):
    out = ['| page | profile | pass | script time | observation window (same clock) | duty cycle (script / window) |', '|---|---|---|---|---|---|']
    for g in rows(order):
        if g['dutyCycle'] is None:
            continue
        out.append(f"| {g['page']} | {g['profile']} | {g['pass']} | {ms(g['scriptMs'])} | {ms(g['windowMs'])} | {g['dutyCycle'] * 100:.0f} % |")
    return '\n'.join(out)


def status(order):
    out = ['| page | profile | pass | runs by outcome | interaction probe failed | map covered by a dialog | visible error text | page errors |', '|---|---|---|---|---|---|---|---|']
    for g in rows(order):
        st = ', '.join(f'{k} {v}' for k, v in sorted(g['statuses'].items()))
        out.append(f"| {g['page']} | {g['profile']} | {g['pass']} | {st} | {g['interactionFailed']}/{g['runs']} | {g['mapCovered']}/{g['runs']} | {'; '.join(g['messages'])[:80] or '–'} | {len(g['pageErrors'])} |")
    return '\n'.join(out)


sec = sys.argv[1]
print({'live': lambda: timing(LIVE_ORDER), 'layers': lambda: timing(LAYER_ORDER), 'live-layerdata': lambda: layers(LIVE_ORDER), 'layers-layerdata': lambda: layers(LAYER_ORDER),
       'duty-live': lambda: duty(LIVE_ORDER), 'duty-layers': lambda: duty(LAYER_ORDER), 'status-live': lambda: status(LIVE_ORDER), 'status-layers': lambda: status(LAYER_ORDER)}[sec]())
