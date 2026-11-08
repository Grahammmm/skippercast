#!/usr/bin/env python3
"""PERF-BASELINE-1 readiness analysis (round 1b): decides from screencast pixels, requests and the interaction probe
when the map is painted, visually complete, responsive and (for an enabled layer) when the layer's data arrived.

Usage:
  python3 reports/perf/analyse.py explore <ready.json> <frames-dir> <run-id>     # per-run decision for one run
  python3 reports/perf/analyse.py controls <frames-dir>                            # self-tests on synthetic loading-overlay / delayed-map controls
  python3 reports/perf/analyse.py all <frames-dir> <out.json> <ready.json>...      # per-run decisions -> out.json
Criteria (from the pixels of the largest canvas, cropped from the screencast frames; the screencast also contains the page's
own overlays, so a crop is NOT map evidence by itself):
  map content the pixels of the settled picture (last frame before the drag probe) that are textured, reappear shifted by
              one common ~60 px translation after the drag probe panned the map (rigid motion), and were stable before it. Overlays
              (legend, panels, loading text, attribution, controls) do not translate with a map drag and animated particles are
              unstable, so neither is ever map content. Needs >= 1 % of the canvas, else the
              run has NO map-content evidence: painted, complete and usable are then "not established", never a time.
  painted     the first frame in which >= 50 % of the map-content pixels already show their final value, for 3 frames in a row.
  complete    the first frame after which no frame differs from the final frame (before the interaction probe) in more than
              1% of the crop's pixels (per-pixel gray difference > 24/255); never earlier than painted. Animated layers never
              settle: reported as null with animated=true.
  responsive  the interaction probe: a 60 px drag after the load settled; the delay until the crop differs from the
              pre-drag frame in more than 0.5% of its pixels. No such frame within 5 s is a failure (null).
  layerDone   the time the last response arrived of the requests that the layer-off reference page does not make
              (live pages) or that match a per-page data pattern (test pages); a failed/4xx/5xx request is a failure.
Evidence integrity: a run is analysed only if its frame directory holds exactly its frames, written when the run recorded
them (file time within 5 s of the frame's receive time). A run whose frame directory was overwritten by a later acquisition
is reported as status=superseded-frames-overwritten and excluded from every median (its raw receipt is kept).
"""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from PIL import Image, ImageChops, ImageFilter

def crop_of(frame_path, canvas, viewport):
    im = Image.open(frame_path).convert('RGB')
    s = im.width / viewport['width']
    x0, y0 = max(0, int(canvas['x'] * s)), max(0, int(canvas['y'] * s))
    x1, y1 = min(im.width, int((canvas['x'] + canvas['w']) * s)), min(im.height, int((canvas['y'] + canvas['h']) * s))
    return im.crop((x0, y0, x1, y1))


def _gray(im):
    return im.convert('L')


def drag_mask(a, b, c, scale, thr=24, tex=12):
    """Pixels of frame `a` (the settled picture just before the drag probe) that are MAP, not overlaid page UI.

    The probe pans the map 60 CSS px to the right. A pixel is map content when (1) it is textured (not a flat fill),
    (2) the same picture value is found displaced to the right in `b` (the picture after the drag) by one common shift
    close to 60 px * scale (a rigid translation: only the map moves like that), (3) it differs from `b` at the same
    place (it really moved) and (4) it was stable before the drag (`c` = an earlier settled frame), so animated
    particles do not count. Overlays (legend, panels, loading text, attribution, controls) do not translate with a map
    drag and are never in the mask, however large or colourful they are. Returns (mask, fraction of the crop, shift in px)."""
    ga = _gray(a)
    gb = _gray(b.resize(a.size))
    unstable = ImageChops.difference(ga, _gray(c.resize(a.size))).point(lambda v: 0 if v > thr else 255)
    t = ImageChops.subtract(ga.filter(ImageFilter.MaxFilter(3)), ga.filter(ImageFilter.MinFilter(3))).point(lambda v: 255 if v > tex else 0)
    moved = ImageChops.difference(ga, gb).point(lambda v: 255 if v > thr else 0)
    base = ImageChops.multiply(ImageChops.multiply(t, unstable), moved)
    best = (0, None, 0)
    lo, hi = max(2, int(scale * 60 * 0.4)), int(scale * 60 * 2.5) + 1
    for dx in range(lo, hi):
        shifted = ImageChops.offset(gb, dx, 0)
        same = ImageChops.difference(ga, shifted).point(lambda v: 255 if v <= thr else 0)
        m = ImageChops.multiply(base, same)
        # the columns that wrapped around in the offset are not evidence
        m.paste(0, (0, 0, dx, a.height)); m.paste(0, (a.width - 1, 0, a.width, a.height))
        n = sum(m.histogram()[255:])
        if n > best[0]:
            best = (n, m, dx)
    if best[1] is None:
        return None, 0.0, 0
    return best[1], best[0] / max(1, a.width * a.height), best[2]


def mask_match(cur, final, mask, thr=24):
    """Share of the map-content pixels (mask) that already show their final value in frame `cur`."""
    same = ImageChops.difference(_gray(cur), _gray(final.resize(cur.size) if final.size != cur.size else final)).point(lambda v: 255 if v <= thr else 0)
    return sum(ImageChops.multiply(same, mask).histogram()[255:]) / max(1, sum(mask.histogram()[255:]))


MASK_MIN_FRAC = 0.01      # map content must cover >= 1 % of the canvas, else there is no evidence the map drew anything
PAINT_MATCH = 0.5         # painted = at least half of the map-content pixels show their final value, for 3 frames in a row


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
    # painted: from MAP pixels only. The map-content mask comes from the drag probe (what moved with the map), so legends, panels,
    # loading text and controls laid over the canvas can never make a blank map look painted.
    pt = None
    post = [c for ms, c in crops if probe_ms <= ms < probe_ms + 5000]
    res['evidence'] = None
    mask = None
    if pre and post and run['probe'].get('done'):
        final_ = pre[-1][1]
        early = [c for ms, c in pre if ms <= pre[-1][0] - 1500]
        mask, mfrac, dx = drag_mask(final_, post[-1], early[-1] if early else final_, final_.width / canvas['w'])
        res['mapContentFrac'] = round(mfrac, 3)
        res['dragShiftPx'] = dx
        res['evidence'] = 'map-content' if mfrac >= MASK_MIN_FRAC else 'none'
        if mfrac < MASK_MIN_FRAC:
            mask = None
    else:
        res['evidence'] = 'no-drag-probe'
    flags = {}
    def flag(i):
        if i not in flags:
            flags[i] = mask_match(pre[i][1], pre[-1][1], mask) >= PAINT_MATCH
        return flags[i]
    if mask is not None:
        for i, (ms, c) in enumerate(pre):
            if flag(i) and all(flag(j) for j in range(i, min(len(pre), i + 3))):
                pt = ms; break
    res['paintedMs'] = None if pt is None else round(pt)
    res['_final'] = pre[-1][1] if pre else None
    res['_probeMs'] = probe_ms
    # visually complete (relative to the last frame before the probe); only meaningful once map content was shown
    if pre and pt is not None:
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
        if res['completeMs'] is not None:
            res['completeMs'] = max(res['completeMs'], res['paintedMs'])
    else:
        res['animated'] = None
        res['completeMs'] = None
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
    # "usable" above is the FIRST moment the page answers input; it can fire before the heavy work starts (e.g. 1.2 s on one seafloor
    # run whose first 3.9 s freeze began at 2.2 s). freeFrom = painted, or the end of the last long task of 200 ms or more before the drag probe if later:
    # from then on no freeze of that length blocked the main thread in the observation window.
    pre_lt = [(s_, d) for s_, d in lt if s_ < probe_ms]
    last_end = max((s_ + d for s_, d in pre_lt if d >= 200), default=None)
    res['lastLongTaskEndMs'] = None if last_end is None else round(last_end)
    res['freeFromMs'] = None if pt is None else round(max(pt, last_end or 0))
    res['longTaskTotalMs'] = round(sum(d for _, d in pre_lt))
    res['briefShownMs'] = None if run['readyAt'] is None else round(run['readyAt'] + off)
    res['messages'] = run.get('messages', [])
    res['pageErrors'] = run.get('pageErrors', [])
    res['status'] = 'no-map-content-evidence' if res['evidence'] != 'map-content' else 'never-painted' if pt is None else 'not-responsive-within-window' if usable is None else 'interaction-failed' if res['interactionFailed'] else 'ok'
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


def frame_integrity(run, fdir):
    """None when the frames on disk are the ones this run recorded, else the reason they are not."""
    d = Path(fdir) / run['id']
    if not d.is_dir():
        return 'frame directory missing'
    n = len(list(d.glob('*.jpg')))
    if n != len(run['frames']):
        return f"{n} frames on disk, {len(run['frames'])} recorded"
    for f in (run['frames'][0], run['frames'][-1]):
        p = d / f"{f['n']:04d}.jpg"
        if not p.exists() or 'recv' not in f or abs(p.stat().st_mtime * 1000 - f['recv']) > 5000:
            return 'frame file written at a different time than recorded'
    return None


def run_all(fdir, out, paths):
    runs = []
    for path in paths:
        doc = json.loads(Path(path).read_text())
        for r in doc['results']:
            if 'error' in r:
                runs.append({'page': r['page'], 'profile': r['profile'], 'pass': r['pass'], 'run': r['run'], 'status': 'error', 'error': r['error']}); continue
            bad = frame_integrity(r, fdir) if r.get('frames') else None
            if bad:
                runs.append({'page': r['page'], 'profile': r['profile'], 'pass': r['pass'], 'run': r['run'], 'id': r['id'], 'status': 'superseded-frames-overwritten',
                             'reason': bad, 'receipt': Path(path).name, 'wallStartMs': r['wallStartMs']}); continue
            d = decide(r, fdir)
            d['id'] = r['id']
            d['_req'] = r.get('requests')
            d['_raw'] = r
            runs.append(d)
    seen = Counter(d['id'] for d in runs if d.get('id') and d.get('status') != 'superseded-frames-overwritten')
    dup = [k for k, v in seen.items() if v > 1]
    if dup:
        raise SystemExit(f'duplicate run ids with intact frames (ambiguous evidence): {dup}')
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
        if d.get('status') == 'superseded-frames-overwritten':
            continue
        groups.setdefault((d['page'], d['profile'], d['pass']), []).append(d)
    summary = []
    for (page, prof, pas), rs in groups.items():
        row = {'page': page, 'profile': prof, 'pass': pas, 'runs': len(rs), 'ok': sum(1 for r in rs if r.get('status') == 'ok'),
               'statuses': dict(Counter(r.get('status') for r in rs))}
        for m in ('firstFrameMs', 'fcpMs', 'paintedMs', 'briefShownMs', 'completeMs', 'usableMs', 'quietAfterPaintMs', 'tbtMs', 'responseMs', 'maxInputDelayMs',
                  'dutyCycle', 'scriptMs', 'windowMs', 'settledMs', 'freeFromMs', 'longTaskTotalMs'):
            row[m] = med([r.get(m) for r in rs])
            row[m + '_all'] = [r.get(m) for r in rs]
        row['evidence'] = sum(1 for r in rs if r.get('evidence') == 'map-content')
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
    if cmd == 'controls':
        import controls
        controls.run(sys.argv[2])
    elif cmd == 'explore':
        doc = json.loads(Path(sys.argv[2]).read_text())
        run = next(r for r in doc['results'] if r['id'] == sys.argv[4])
        res = decide(run, sys.argv[3])
        res = {k: v for k, v in res.items() if not k.startswith('_')}
        print(json.dumps(res, indent=1))
    elif cmd == 'all':
        run_all(sys.argv[2], sys.argv[3], sys.argv[4:])


if __name__ == '__main__':
    main()
