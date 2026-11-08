#!/usr/bin/env python3
"""PERF-BASELINE-1 readiness analysis (round 2): decides from screencast pixels, requests and the interaction probe
when the map is painted, visually complete, responsive and (for an enabled layer) when the layer's data arrived.

Usage:
  python3 reports/perf/analyse.py explore <ready.json> <frames-dir> <run-id>     # print per-frame metrics for one run
  python3 reports/perf/analyse.py blank <frames-dir>/blank                         # self-test: a flat canvas must not be painted
  python3 reports/perf/analyse.py all <frames-dir> <out.json> <ready.json>...      # per-run decisions -> out.json
Criteria (all from pixels of the largest canvas, cropped from the screencast frames):
  painted     the crop is not a flat fill: its most common 4-bit colour covers <= 80% of the area and at least two other
              colours each cover >= 1%; a blank or single-colour canvas is never painted. Must stay true for the next 2 frames.
  complete    the first frame after which no frame differs from the final frame (before the interaction probe) in more than
              1% of the crop's pixels (per-pixel gray difference > 24/255). Animated layers (wind) never settle: reported
              as null with animated=true.
  responsive  the interaction probe: a 60 px drag after the load settled; the delay until the crop differs from the
              pre-drag frame in more than 0.5% of its pixels. No such frame within 5 s is a failure (null).
  layerDone   the time the last response arrived of the requests that the layer-off reference page does not make
              (live pages) or that match a per-page data pattern (test pages); a failed/4xx/5xx request is a failure.
"""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from PIL import Image, ImageChops, ImageOps

PAINT_TOP, PAINT_OTHERS = 0.80, 2


def crop_of(frame_path, canvas, viewport):
    im = Image.open(frame_path).convert('RGB')
    s = im.width / viewport['width']
    x0, y0 = max(0, int(canvas['x'] * s)), max(0, int(canvas['y'] * s))
    x1, y1 = min(im.width, int((canvas['x'] + canvas['w']) * s)), min(im.height, int((canvas['y'] + canvas['h']) * s))
    return im.crop((x0, y0, x1, y1))


def painted(im):
    small = ImageOps.posterize(im.resize((max(1, im.width // 2), max(1, im.height // 2))), 4)   # 4 bits per channel
    cols = sorted(small.getcolors(maxcolors=1 << 20), reverse=True)
    total = sum(n for n, _ in cols)
    top = cols[0][0] / total
    others = sum(1 for n, _ in cols[1:] if n / total >= 0.01)
    return top <= PAINT_TOP and others >= PAINT_OTHERS, round(top, 3), others


def diff_frac(a, b, thr=24):
    if a.size != b.size:
        b = b.resize(a.size)
    d = ImageChops.difference(a.convert('L'), b.convert('L'))
    h = d.histogram()
    return sum(h[thr + 1:]) / max(1, a.width * a.height)


def run_frames(run, fdir):
    ms0 = run['wallStartMs']
    out = []
    for f in run['frames']:
        out.append({'n': f['n'], 'ms': f['t'] * 1000 - ms0, 'path': Path(fdir) / run['id'] / f"{f['n']:04d}.jpg"})
    return out


def decide(run, fdir):
    res = {'page': run['page'], 'profile': run['profile'], 'pass': run['pass'], 'run': run['run'], 'frames': len(run['frames']), 'settledMs': run['settledMs']}
    canvas = run.get('canvas')
    frames = run_frames(run, fdir)
    if not canvas or canvas['w'] < 150 or canvas['h'] < 150 or not frames:
        res.update(paintedMs=None, completeMs=None, animated=None, status='no-map-canvas')
        return res
    off = run['timeOrigin'] - run['wallStartMs']          # ms from first request to the page's time origin
    probe_ms = (run['probe'].get('tInput') or 1e18) - run['wallStartMs']
    crops = [(f['ms'], crop_of(f['path'], canvas, run['viewport'])) for f in frames]
    pre = [(ms, c) for ms, c in crops if ms < probe_ms]
    res['firstFrameMs'] = round(frames[0]['ms'])
    # painted
    pt = None
    flags = {}
    def flag(i):
        if i not in flags:
            flags[i] = painted(pre[i][1])[0]
        return flags[i]
    for i, (ms, c) in enumerate(pre):
        if flag(i) and all(flag(j) for j in range(i, min(len(pre), i + 3))):
            pt = ms; break
    res['paintedMs'] = None if pt is None else round(pt)
    res['finalPaint'] = painted(pre[-1][1])[1:] if pre else None
    res['_final'] = pre[-1][1] if pre else None
    res['_probeMs'] = probe_ms
    # visually complete (relative to the last frame before the probe)
    if pre:
        final = pre[-1][1]
        bad = [ms for ms, c in pre if diff_frac(final, c) > 0.01]
        # a static picture produces no screencast frames; 10 or more frames in the last 2 s before the probe is continuous repainting (particles)
        animated = sum(1 for ms, _ in pre if ms > probe_ms - 2000) >= 10
        res['animated'] = animated
        res['completeMs'] = None if animated else round(max(bad) if bad else pre[0][0])
        # first frame after complete: the time of the first frame at which diff vs final stays <= 1%
        if not animated and bad:
            later = [ms for ms, _ in pre if ms > max(bad)]
            res['completeMs'] = round(later[0]) if later else round(max(bad))
    # responsive: first frame after the drag that differs from the last frame before it
    pr = run['probe']
    resp = None
    if pr.get('done') and pre:
        base = pre[-1][1]
        for ms, c in crops:
            if ms >= probe_ms and diff_frac(base, c, 16) > 0.005:
                resp = ms - probe_ms; break
    res['responseMs'] = None if resp is None else round(resp)
    res['interactionFailed'] = bool(pr.get('done')) and resp is None
    res['mapCovered'] = bool(pr.get('covered'))
    # usable = painted AND the page answers input: two consecutive probe events (1 per second) both wait <= 200 ms behind the main thread
    lt = sorted((s_ + off, d) for s_, d in run['longtasks'])
    delays = sorted((t + off, d) for t, d in run.get('inputDelays', []))
    usable = None
    if pt is not None:
        for i in range(len(delays) - 1):
            if delays[i][0] >= pt - 1000 and delays[i][1] <= 200 and delays[i + 1][1] <= 200:
                usable = max(pt, delays[i][0]); break
    res['usableMs'] = None if usable is None else round(usable)
    res['maxInputDelayMs'] = round(max((d for _, d in delays), default=0))
    res['inputProbes'] = len(delays)
    # secondary, main-thread-only criterion (the A.3 definition re-anchored on the painted frame): 1 s with no long task after painted
    t = pt
    if t is not None:
        for s_, d in lt:
            if s_ + d <= t:
                continue
            if s_ < t + 1000:
                t = max(t, s_ + d)
            else:
                break
    res['quietAfterPaintMs'] = None if pt is None else round(t)
    fcp = None if run['fcp'] is None else run['fcp'] + off
    res['fcpMs'] = None if fcp is None else round(fcp)
    tbt_end = usable if usable is not None else run['settledMs']
    res['tbtMs'] = None if fcp is None else round(sum(max(0, d - 50) for s_, d in lt if s_ >= fcp and s_ < tbt_end))
    res['tbtWindowOpen'] = usable is None
    res['briefShownMs'] = None if run['readyAt'] is None else round(run['readyAt'] + off)
    res['messages'] = run.get('messages', [])
    res['pageErrors'] = run.get('pageErrors', [])
    res['status'] = 'never-painted' if pt is None else 'not-responsive-within-window' if usable is None else 'interaction-failed' if res['interactionFailed'] else 'ok'
    c = run.get('cpu') or {}
    res['dutyCycle'] = None if not c.get('windowS') else round(c['scriptS'] / c['windowS'], 3)
    res['scriptMs'] = round(c.get('scriptS', 0) * 1000)
    res['windowMs'] = round(c.get('windowS', 0) * 1000)
    return res


LIVE_REF = 'live-layer-none'
RELIEF_REF = 'layer-base-medium'
PATTERN = {'layer-wind': r'maplayer-wind-1', 'layer-sst': r'maplayer-sst-1'}
NO_VISIBLE_DIFF = {'live-layer-none', 'layer-base-medium', 'layer-bathy-2m-z12', 'brief', 'map-home-returning', 'map-home', 'layer-wind', 'layer-sst'}


def path_of(u):
    return u.split('?')[0]


def layer_info(run, ref_paths, pattern, probe_ms):
    """Requests this page makes that the layer-off reference does not (or that match the page's data pattern), started before the drag probe."""
    import re
    mine = []
    for q in run['requests']:
        if q.get('data') or q['startMs'] >= probe_ms:
            continue
        if pattern is not None:
            if re.search(pattern, q['url']):
                mine.append(q)
        elif ref_paths is not None and path_of(q['url']) not in ref_paths:
            mine.append(q)
    if ref_paths is None and pattern is None:
        return None
    bad = [q for q in mine if (q['status'] or 0) >= 400 or (q.get('failed') and q['failed'] != 'net::ERR_ABORTED')]
    open_ = [q for q in mine if q['endMs'] is None]
    done = [q['endMs'] for q in mine if q['endMs'] is not None]
    return {'requests': len(mine), 'bytes': sum(q['bytes'] or 0 for q in mine), 'doneMs': max(done) if done and not open_ else None,
            'failed': len(bad), 'stillOpen': len(open_), 'firstStartMs': min((q['startMs'] for q in mine), default=None),
            'examples': sorted({path_of(q['url']).rsplit('/', 1)[-1] for q in mine})[:4]}


def med(vals):
    """Median of 3 where a run that never reached the state counts as infinity: two such runs make the median 'not reached' (None)."""
    v = sorted(float('inf') if x is None else x for x in vals)
    m = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
    return None if m == float('inf') else round(m, 3) if m < 10 else round(m)


def run_all(fdir, out, paths):
    runs = []
    for path in paths:
        doc = json.loads(Path(path).read_text())
        for r in doc['results']:
            if 'error' in r:
                runs.append({'page': r['page'], 'profile': r['profile'], 'pass': r['pass'], 'run': r['run'], 'status': 'error', 'error': r['error']}); continue
            d = decide(r, fdir)
            d['_req'] = r.get('requests')
            d['_raw'] = r
            runs.append(d)
    # reference paths per (profile, pass)
    refs = {}
    refimg = {}
    for d in runs:
        if '_raw' not in d:
            continue
        if d['page'] in (LIVE_REF, RELIEF_REF):
            refs.setdefault((d['profile'], d['pass'], d['page']), set()).update(path_of(q['url']) for q in d['_req'] if not q.get('data'))
            if d['run'] == 1 and d.get('_final') is not None:
                refimg[(d['profile'], d['pass'], d['page'])] = d['_final']
    for d in runs:
        if '_raw' not in d:
            continue
        page = d['page']
        refname = LIVE_REF if page.startswith('live-layer-') else RELIEF_REF if page.startswith('layer-') and page not in PATTERN else None
        ref_paths = refs.get((d['profile'], d['pass'], refname)) if refname else None
        d['layer'] = layer_info(d['_raw'], ref_paths if page not in (LIVE_REF, RELIEF_REF) else None, PATTERN.get(page), d['_probeMs']) if (refname or page in PATTERN) and page not in (LIVE_REF, RELIEF_REF) else None
        d['layerReference'] = refname if page not in (LIVE_REF, RELIEF_REF) else None
        d['layerVisibleDiff'] = None
        if page not in NO_VISIBLE_DIFF and refname and d.get('_final') is not None and (d['profile'], d['pass'], refname) in refimg:
            d['layerVisibleDiff'] = round(diff_frac(d['_final'], refimg[(d['profile'], d['pass'], refname)]), 3)
    # summary per (page, profile, pass)
    groups = {}
    for d in runs:
        groups.setdefault((d['page'], d['profile'], d['pass']), []).append(d)
    summary = []
    for (page, prof, pas), rs in groups.items():
        row = {'page': page, 'profile': prof, 'pass': pas, 'runs': len(rs), 'ok': sum(1 for r in rs if r.get('status') == 'ok'),
               'statuses': dict(Counter(r.get('status') for r in rs))}
        for m in ('firstFrameMs', 'fcpMs', 'paintedMs', 'briefShownMs', 'completeMs', 'usableMs', 'quietAfterPaintMs', 'tbtMs', 'responseMs', 'maxInputDelayMs',
                  'dutyCycle', 'scriptMs', 'windowMs', 'settledMs'):
            row[m] = med([r.get(m) for r in rs])
            row[m + '_all'] = [r.get(m) for r in rs]
        row['animated'] = sum(1 for r in rs if r.get('animated'))
        row['mapCovered'] = sum(1 for r in rs if r.get('mapCovered'))
        row['interactionFailed'] = sum(1 for r in rs if r.get('interactionFailed'))
        L = [r.get('layer') for r in rs]
        if any(L):
            row['layerDoneMs'] = med([x['doneMs'] if x else None for x in L])
            row['layerDoneMs_all'] = [x['doneMs'] if x else None for x in L]
            row['layerRequests'] = med([x['requests'] if x else 0 for x in L])
            row['layerBytes'] = med([x['bytes'] if x else 0 for x in L])
            row['layerFailed'] = sum(x['failed'] for x in L if x)
            row['layerExamples'] = next((x['examples'] for x in L if x), [])
            row['layerReference'] = rs[0].get('layerReference')
        v = [r.get('layerVisibleDiff') for r in rs if r.get('layerVisibleDiff') is not None]
        row['layerVisibleDiff'] = med(v) if v else None
        row['messages'] = sorted({m for r in rs for m in r.get('messages', [])})[:6]
        row['pageErrors'] = sorted({m for r in rs for m in r.get('pageErrors', [])})[:4]
        summary.append(row)
    for d in runs:
        for k in [k for k in d if k.startswith('_')]:
            del d[k]
    Path(out).write_text(json.dumps({'runs': runs, 'groups': summary}, indent=1))
    print(len(runs), 'runs;', len(summary), 'groups')


def main():
    cmd = sys.argv[1]
    if cmd == 'blank':
        d = Path(sys.argv[2]); meta = json.loads((d / 'blank.json').read_text())
        for f in meta['frames']:
            im = crop_of(d / f"{f['n']:04d}.jpg", meta['canvas'], meta['viewport'])
            print('blank frame', f['n'], 'painted=', painted(im))
    elif cmd == 'explore':
        doc = json.loads(Path(sys.argv[2]).read_text())
        run = next(r for r in doc['results'] if r['id'] == sys.argv[4])
        res = decide(run, sys.argv[3])
        res = {k: v for k, v in res.items() if not k.startswith('_')}
        print(json.dumps(res, indent=1))
    elif cmd == 'all':
        run_all(sys.argv[2], sys.argv[3], sys.argv[4:])


main()
