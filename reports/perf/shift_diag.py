#!/usr/bin/env python3
"""shift_diag.py <ready.json> <frames-dir> <run-id>... : the failed drag-shift check of A.1b (diagnostic, not used by analyse.py).

For each run: the last canvas crop before the drag probe is compared with the last one within 5 s after it. Only pixels that are
textured and really changed are scored; for each horizontal shift the share of them that reappear shifted (gray difference <= 14/255)
is computed. A rigid pan of the whole picture by the drag would give one sharp peak at the pan distance (60 CSS px = 60 * screencast
scale in frame pixels) holding most of those pixels. The output lists the top shifts and their share.
"""
import json
import sys
from pathlib import Path

from PIL import ImageChops, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
import analyse as A

THR_MOVED, THR_SAME, TEX = 24, 14, 12


def scores(ga, gb, lo, hi):
    t = ImageChops.subtract(ga.filter(ImageFilter.MaxFilter(3)), ga.filter(ImageFilter.MinFilter(3))).point(lambda v: 255 if v > TEX else 0)
    moved = ImageChops.difference(ga, gb).point(lambda v: 255 if v > THR_MOVED else 0)
    base = ImageChops.multiply(t, moved)
    nb = sum(base.histogram()[255:])
    out = []
    for dx in range(lo, hi):
        same = ImageChops.difference(ga, ImageChops.offset(gb, dx, 0)).point(lambda v: 255 if v <= THR_SAME else 0)
        out.append((dx, sum(ImageChops.multiply(base, same).histogram()[255:])))
    return out, nb


def main():
    raw, fdir = sys.argv[1], sys.argv[2]
    doc = json.loads(Path(raw).read_text())
    for rid in sys.argv[3:]:
        run = next(r for r in doc['results'] if r['id'] == rid)
        probe_ms = (run['probe'].get('tInput') or 1e18) - run['wallStartMs']
        fr = A.run_frames(run, fdir)
        pre = [f for f in fr if f['ms'] < probe_ms]
        post = [f for f in fr if probe_ms <= f['ms'] < probe_ms + 5000]
        c, v = run['canvas'], run['viewport']
        a = A.crop_of(pre[-1]['path'], c, v).convert('L')
        b = A.crop_of(post[-1]['path'], c, v).convert('L')
        sc = a.width / c['w']
        res, nb = scores(a, b, 2, int(sc * 200))
        top = sorted(res, key=lambda x: -x[1])[:4]
        print(rid, 'scale', round(sc, 2), 'expected shift px', round(60 * sc), 'moved textured px', nb,
              'top', [(d, n, round(n / max(1, nb), 2)) for d, n in top])


if __name__ == '__main__':
    main()
