#!/usr/bin/env python3
"""PERF-BASELINE-1: replace the body of a report section (heading line to the next '### ' heading) with a file's text.

Usage: python3 reports/perf/splice_section.py <report.md> <heading-prefix> <body.md>
"""
import sys

report, heading, body_file = sys.argv[1:4]
lines = open(report, encoding='utf-8').read().split('\n')
body = open(body_file, encoding='utf-8').read().rstrip('\n').split('\n')
start = next(i for i, l in enumerate(lines) if l.startswith(heading))
end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('### ') or lines[i].startswith('## '))
lines[start + 1:end] = [''] + body + ['']
open(report, 'w', encoding='utf-8').write('\n'.join(lines))
print(f'{heading}: replaced {end - start - 1} lines with {len(body) + 2}')
