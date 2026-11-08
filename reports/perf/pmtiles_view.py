#!/usr/bin/env python3
"""Compact per-zoom table of pmtiles_sizes.mjs output."""
import json, sys
d = json.load(open(sys.argv[1]))
for src, a in d.items():
    print(f"\n{src}: type={a['tileType']} comp={a['tileCompression']} z{a['minZoom']}-{a['maxZoom']} layers={a['vectorLayers']}")
    for z, s in sorted(a['zooms'].items(), key=lambda kv: int(kv[0])):
        print(f"  z{z:>2} tiles={s['tiles']:>6} total={s['totalBytes']/1e6:8.2f}MB median={s['medianBytes']/1e3:7.1f}KB p95={s['p95Bytes']/1e3:7.1f}KB max={s['maxBytes']/1e3:7.1f}KB >500KB={s['over500KB']}")
