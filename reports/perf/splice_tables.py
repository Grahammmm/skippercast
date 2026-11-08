#!/usr/bin/env python3
"""PERF-BASELINE-1: replace a Markdown table in the report with a regenerated one (or just diff it).

Usage: python3 reports/perf/splice_tables.py <report.md> <heading-prefix> <table.md> [--write]
The table is the first run of lines starting with '|' after the heading line that starts with <heading-prefix>.
Without --write it prints the changed rows only.
"""
import sys

report, heading, table_file = sys.argv[1:4]
write = '--write' in sys.argv
lines = open(report, encoding='utf-8').read().split('\n')
new = [l for l in open(table_file, encoding='utf-8').read().split('\n') if l.startswith('|')]
start = next(i for i, l in enumerate(lines) if l.startswith(heading))
i = start
while not lines[i].startswith('|'):
    i += 1
j = i
while j < len(lines) and lines[j].startswith('|'):
    j += 1
old = lines[i:j]
changed = [(o, n) for o, n in zip(old, new) if o != n]
print(f'{heading!r}: old rows {len(old)}, new rows {len(new)}, changed {len(changed)}')
if not write:
    for o, n in changed:
        print('- ' + o)
        print('+ ' + n)
else:
    lines[i:j] = new
    open(report, 'w', encoding='utf-8').write('\n'.join(lines))
