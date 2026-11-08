#!/usr/bin/env python3
"""Byte share of each top-level (and second-level) key of a JSON payload: python3 reports/perf/json_anatomy.py <file.json>"""
import json, sys
doc = json.load(open(sys.argv[1]))
total = len(json.dumps(doc, separators=(',', ':')))
print('total', total)
def show(obj, prefix, depth):
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: -len(json.dumps(kv[1], separators=(',', ':'))))
        for k, v in items[:12]:
            n = len(json.dumps(v, separators=(',', ':')))
            if n > total * 0.02:
                print(f"{prefix}{k}: {n:,} ({100*n/total:.0f}%) {type(v).__name__}{'[' + str(len(v)) + ']' if isinstance(v, (list, dict)) else ''}")
                if depth < 2:
                    show(v, prefix + '  ', depth + 1)
    elif isinstance(obj, list) and obj and depth < 2:
        show(obj[0], prefix + '  [0].', depth + 1)
show(doc, '', 0)
