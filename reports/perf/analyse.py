#!/usr/bin/env python3
"""PERF-BASELINE-1 readiness analysis (round 1b): decides from screencast pixels, requests and the interaction probe
when the map is painted, visually complete, responsive and (for an enabled layer) when the layer's data arrived.

Usage:
  python3 reports/perf/analyse.py explore <ready.json> <frames-dir> <run-id>     # per-run decision for one run
  python3 reports/perf/analyse.py controls <frames-dir>                            # self-tests on synthetic loading-overlay / delayed-map controls
  python3 reports/perf/analyse.py all <frames-dir> <out.json> <ready.json>...      # per-run decisions -> out.json
Criteria. Map CONTENT readiness (painted, visually complete) is UNMEASURED and is never reported as a time:
  the screencast frame holds the page's own overlays (legend, panels, loading text, controls) as well as the map canvas, so a
  crop of the canvas rectangle is not map evidence, and the one attempt to separate the two (a rigid-translation mask from the
  drag probe) gave shifts that disagree between runs of the same page (A.1b), so it was dropped. paintedMs, completeMs and
  layerVisibleDiff are therefore always null here.
  FCP        the browser's own first contentful paint (any content, not the map).
  inputOk    the first time at or after FCP (first frame if no FCP) that two consecutive input-probe events (1 per second) both
              waited <= 200 ms behind the main thread. It says the page answers input; it does NOT say the map is drawn.
  freeFrom   the HEADLINE: inputOk, or the end of the last long task of 200 ms or more before the drag probe if later: from then on no
              freeze of that length blocked the main thread inside the observation window. inputOk alone can be early (before heavy
              work starts); the median of 3 is quoted.
  response   the interaction probe: a 60 px drag after the load settled; the delay until the canvas rectangle differs from the
              pre-drag frame in more than 0.5% of its pixels (any repaint, including overlays). None within 5 s is a failure.
  layerDone  the time the last response arrived of the requests that the layer-off reference page does not make
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
    # content readiness is NOT measured (see the module docstring): never a time from crop pixels
    res['evidence'] = 'unmeasured'
    res['paintedMs'] = None
    res['completeMs'] = None
    res['animated'] = None
    res['_final'] = pre[-1][1] if pre else None
    res['_probeMs'] = probe_ms
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
    fcp = None if run['fcp'] is None else run['fcp'] + off
    res['fcpMs'] = None if fcp is None else round(fcp)
    gate = fcp if fcp is not None else frames[0]['ms']
    # inputOk = the page answers input: two consecutive probe events (1 per second) both wait <= 200 ms behind the main thread
    lt = sorted((s_ + off, d) for s_, d in run['longtasks'])
    delays = sorted((t + off, d) for t, d in run.get('inputDelays', []))
    ok = None
    for i in range(len(delays) - 1):
        if delays[i][0] >= gate and delays[i][1] <= 200 and delays[i + 1][1] <= 200:
            ok = delays[i][0]; break
    res['inputOkMs'] = None if ok is None else round(ok)
    res['maxInputDelayMs'] = round(max((d for _, d in delays), default=0))
    res['inputProbes'] = len(delays)
    # inputOk can fire before the heavy work starts (e.g. 1.2 s on one seafloor run whose first 3.9 s freeze began at 2.2 s).
    # freeFrom = inputOk, or the end of the last long task of 200 ms or more before the drag probe if later.
    pre_lt = [(s_, d) for s_, d in lt if s_ < probe_ms]
    last_end = max((s_ + d for s_, d in pre_lt if d >= 200), default=None)
    res['lastLongTaskEndMs'] = None if last_end is None else round(last_end)
    res['freeFromMs'] = None if ok is None else round(max(ok, last_end or 0))
    # TBT (long-task time over 50 ms) from FCP up to freeFrom (up to the end of the observation window when the page never answered)
    tbt_end = max(ok, last_end or 0) if ok is not None else run['settledMs']
    res['tbtMs'] = None if fcp is None else round(sum(max(0, d - 50) for s_, d in lt if s_ >= fcp and s_ < tbt_end))
    res['tbtWindowOpen'] = ok is None
    res['longTaskTotalMs'] = round(sum(d for _, d in pre_lt))
    res['briefShownMs'] = None if run['readyAt'] is None else round(run['readyAt'] + off)
    res['messages'] = run.get('messages', [])
    res['pageErrors'] = run.get('pageErrors', [])
    res['status'] = 'not-responsive-within-window' if ok is None else 'interaction-failed' if res['interactionFailed'] else 'ok'
    c = run.get('cpu') or {}
    res['dutyCycle'] = None if not c.get('windowS') else round(c['scriptS'] / c['windowS'], 3)
    res['scriptMs'] = round(c.get('scriptS', 0) * 1000)
    res['windowMs'] = round(c.get('windowS', 0) * 1000)
    return res


LIVE_REF = 'live-layer-none'
RELIEF_REF = 'layer-base-medium'
PATTERN = {'layer-wind': r'maplayer-wind-1', 'layer-sst': r'maplayer-sst-1'}


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
    for d in runs:
        if '_raw' not in d:
            continue
        if d['page'] in (LIVE_REF, RELIEF_REF):
            refs.setdefault((d['profile'], d['pass'], d['page']), set()).update(path_of(q['url']) for q in d['_req'] if not q.get('data'))
    for d in runs:
        if '_raw' not in d:
            continue
        page = d['page']
        refname = LIVE_REF if page.startswith('live-layer-') else RELIEF_REF if page.startswith('layer-') and page not in PATTERN else None
        ref_paths = refs.get((d['profile'], d['pass'], refname)) if refname else None
        d['layer'] = layer_info(d['_raw'], ref_paths if page not in (LIVE_REF, RELIEF_REF) else None, PATTERN.get(page), d['_probeMs']) if (refname or page in PATTERN) and page not in (LIVE_REF, RELIEF_REF) else None
        d['layerReference'] = refname if page not in (LIVE_REF, RELIEF_REF) else None
        d['layerVisibleDiff'] = None            # UNMEASURED: a pixel comparison of two crops would include overlay differences
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
        for m in ('firstFrameMs', 'fcpMs', 'briefShownMs', 'inputOkMs', 'tbtMs', 'responseMs', 'maxInputDelayMs',
                  'dutyCycle', 'scriptMs', 'windowMs', 'settledMs', 'freeFromMs', 'longTaskTotalMs'):
            row[m] = med([r.get(m) for r in rs])
            row[m + '_all'] = [r.get(m) for r in rs]
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
