#!/usr/bin/env python3
"""PERF-BASELINE-1b controls for analyse.py: a loading overlay over a map that has not drawn must never become a positive
painted / visually-complete reading, and overwritten frames must never be analysed.

Usage: python3 reports/perf/analyse.py controls <frames-dir>          (needs the retained frames of the real runs)
Built from REAL retained frames of desktop-map-home-returning-cold-1 (raw/ready-live-desktop-warm.json), nothing invented:
  U  = frame 4 (276 ms): page controls, legend and loading text over a map that has drawn nothing yet (checked by eye).
  A  every frame of the run is U, plus a large bright overlay panel with changing 'loading' text from 0.5 s on. The map never draws.
  B  frames before 4.0 s are U + the same changing overlay; from 4.0 s the real frames. The map draws late (4.0 s).
  C  the real run unchanged.
  D  the real wind-test run (phone): the loading text/legend is present from the first frame; this is the retained case that the
        first harness reported as painted at 0.85 s.
  E  frame-directory integrity: the original desktop-brief-cold-1 receipt (frames overwritten by a later batch) is rejected,
        the later receipt of the same id is accepted.
  F  the committed summary (raw/ready-summary.json) holds no painted / visually-complete / layer-visible-difference time.
Expected for A to D: painted and visually complete are null with evidence 'unmeasured' - the analysis makes no positive content
claim from pixels that include overlays (the measuring attempt that tried to tell map from overlay is described in A.1b).
Exit code 1 if any expectation fails.
"""
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

import analyse

RAW = Path(__file__).parent / 'raw'
UI_ONLY_FRAME = 4


def load(name, rid):
    doc = json.loads((RAW / name).read_text())
    return next(r for r in doc['results'] if r['id'] == rid)


def overlay(im, run, n, t_ms):
    """Draw a big bright panel over the left 40 % of the canvas with text that changes every frame."""
    c = run['canvas']
    s = im.width / run['viewport']['width']
    x0, y0 = int(c['x'] * s), int(c['y'] * s)
    x1, y1 = int((c['x'] + c['w'] * 0.4) * s), int((c['y'] + c['h'] * 0.7) * s)
    d = ImageDraw.Draw(im)
    d.rectangle([x0, y0, x1, y1], fill=(245, 245, 245))
    for i in range(6):
        d.text((x0 + 6, y0 + 6 + i * 14), f'Loading private field... {n} {int(t_ms) + i * 7}', fill=(20, 20, 20))
        d.rectangle([x0 + 6, y0 + 100 + i * 8, x0 + 6 + (n * 7 + i * 13) % 150, y0 + 104 + i * 8], fill=(200, 60, 60))
    return im


def build(run, src_dir, out_dir, replace_before_ms, with_overlay):
    """Copy the run's frames into out_dir/<id>; frames before replace_before_ms become U (+ overlay); overlay from 0.5 s on."""
    rid = run['id']
    dst = out_dir / rid
    dst.mkdir(parents=True)
    ms0 = run['wallStartMs']
    ui = Image.open(src_dir / rid / f'{UI_ONLY_FRAME:04d}.jpg').convert('RGB')
    for f in run['frames']:
        ms = f['t'] * 1000 - ms0
        if ms < replace_before_ms:
            im = ui.copy()
        else:
            im = Image.open(src_dir / rid / f"{f['n']:04d}.jpg").convert('RGB')
        if with_overlay and 500 <= ms < replace_before_ms:
            overlay(im, run, f['n'], ms)
        im.save(dst / f"{f['n']:04d}.jpg", quality=90)
    return run


def painted_of(run, fdir):
    r = analyse.decide(run, str(fdir))
    return {k: r.get(k) for k in ('evidence', 'paintedMs', 'completeMs', 'inputOkMs', 'status')}


def run(frames_dir):
    frames = Path(frames_dir)
    fails = []

    def expect(name, ok, detail):
        print(('PASS ' if ok else 'FAIL ') + name + ': ' + detail)
        if not ok:
            fails.append(name)

    def unmeasured(r):
        return r['evidence'] == 'unmeasured' and r['paintedMs'] is None and r['completeMs'] is None

    base = load('ready-live-desktop-warm.json', 'desktop-map-home-returning-cold-1')
    tmp = Path(tempfile.mkdtemp(prefix='perf-controls-'))
    try:
        expect('C real run', unmeasured(painted_of(base, frames)), json.dumps(painted_of(base, frames)))
        a_run = copy.deepcopy(base)
        build(a_run, frames, tmp / 'A', 1e12, True)
        a = painted_of(a_run, tmp / 'A')
        expect('A loading overlay, map never draws', unmeasured(a), json.dumps(a))
        b_run = copy.deepcopy(base)
        build(b_run, frames, tmp / 'B', 4000, True)
        b = painted_of(b_run, tmp / 'B')
        expect('B map delayed to 4.0 s behind a loading overlay', unmeasured(b), json.dumps(b))
        d_run = load('ready-layers-main-phone.json', 'phone-layer-wind-cold-1')
        d = painted_of(d_run, frames)
        expect('D wind test page (legend + loading text from the first frame)', unmeasured(d), json.dumps(d))
        orig = load('ready-live-desktop.json', 'desktop-brief-cold-1')
        later = load('ready-live-desktop-warm.json', 'desktop-brief-cold-1')
        eo, el = analyse.frame_integrity(orig, frames), analyse.frame_integrity(later, frames)
        expect('E overwritten original rejected, later intact accepted', eo is not None and el is None, f'original: {eo!r}; later: {el!r}')
        summ = json.loads((RAW / 'ready-summary.json').read_text())
        bad = [g['page'] for g in summ['groups'] if any(k in g for k in ('paintedMs', 'completeMs', 'layerVisibleDiff'))]
        bad += [r.get('id') for r in summ['runs'] if r.get('paintedMs') is not None or r.get('completeMs') is not None]
        expect('F summary holds no painted / complete / visible-difference time', not bad, f'{len(summ["runs"])} runs, offenders: {bad[:5]}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('controls:', 'ALL PASS' if not fails else 'FAILED ' + ', '.join(fails))
    if fails:
        sys.exit(1)


if __name__ == '__main__':
    run(sys.argv[1])
