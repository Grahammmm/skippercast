#!/usr/bin/env python3
"""PERF-BASELINE-1: list every (page, profile, pass) group in raw/summary.json whose run count is not 3 or that did not settle."""
import json
from pathlib import Path

groups = json.loads(Path('reports/perf/raw/summary.json').read_text())['groups']
bad = [(g['page'], g['profile'], g['pass'], g['runs'], g['settledAll']) for g in groups if g['runs'] != 3 or not g['settledAll']]
print(f'{len(groups)} groups; {len(bad)} with runs != 3 or not settled')
for row in bad:
    print(row)
