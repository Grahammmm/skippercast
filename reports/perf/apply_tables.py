#!/usr/bin/env python3
"""PERF-BASELINE-1: regenerate the generated tables of the report from raw/summary.json, raw/extras.json and raw/ready-summary.json.

Usage: python3 reports/perf/apply_tables.py <report.md> [--readiness-only]
(--readiness-only fills only the tables of A.3b, A.5b, A.7b and leaves A.3 to A.7 as they are.)
Replaces, in place: A.3, A.4, A.5 (first table of each), A.6 (whole body), A.7 (its three tables), and the tables of the
readiness sections A.3b, A.5b, A.7b when those headings exist (each of their tables, in order).
"""
import subprocess
import sys

report = sys.argv[1]
lines = open(report, encoding='utf-8').read().split('\n')


def gen(cmd, *args):
    return subprocess.check_output(['python3', f'reports/perf/{cmd}.py', *args], text=True).rstrip('\n').split('\n')


def section(heading):
    start = next(i for i, l in enumerate(lines) if l.startswith(heading))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('### ') or lines[i].startswith('## ')), len(lines))
    return start, end


def tables_in(start, end):
    out, i = [], start
    while i < end:
        if lines[i].startswith('|'):
            j = i
            while j < end and lines[j].startswith('|'):
                j += 1
            out.append((i, j)); i = j
        else:
            i += 1
    return out


def replace_tables(heading, new_tables):
    """Replace the first len(new_tables) tables of the section, last first so the indices stay valid."""
    start, end = section(heading)
    found = tables_in(start, end)
    assert len(found) >= len(new_tables), (heading, len(found), len(new_tables))
    for (a, b), new in reversed(list(zip(found, new_tables))):
        new = [l for l in new if l.startswith('|')]
        lines[a:b] = new
    print(f'{heading}: replaced {len(new_tables)} table(s)')


if '--readiness-only' not in sys.argv[2:]:
    replace_tables('### A.3 ', [gen('make_tables', 'live-main')])
    replace_tables('### A.4 ', [gen('make_tables', 'live-kinds')])
    replace_tables('### A.5 ', [gen('make_tables', 'live-extras')])
    replace_tables('### A.7 ', [gen('make_tables', 'layers-main'), gen('make_tables', 'layers-kinds'), gen('make_tables', 'layers-extras')])
    # A.6: the heaviest-request lists are one body
    start, end = section('### A.6 ')
    body = ['', 'Network requests only: inline `data:` URLs never crossed the link and are not ranked (A.1).', ''] + gen('make_tables', 'heaviest') + ['']
    lines[start + 1:end] = body
    print('### A.6: body replaced')
for heading, sections in (('### A.3b ', ['live', 'live-layerdata', 'status-live']), ('### A.5b ', ['duty-live']), ('### A.7b ', ['layers', 'layers-layerdata', 'duty-layers', 'status-layers'])):
    if any(l.startswith(heading) for l in lines):
        replace_tables(heading, [gen('ready_tables', s) for s in sections])
open(report, 'w', encoding='utf-8').write('\n'.join(lines))
