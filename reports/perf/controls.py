#!/usr/bin/env python3
"""PERF-BASELINE-1b controls for analyse.py: a loading overlay over a map that has not drawn must never be 'painted'.

Usage: python3 reports/perf/analyse.py controls <frames-dir>          (needs the retained frames of the real runs)
Built from REAL retained frames of desktop-map-home-returning-cold-1 (raw/ready-live-desktop-warm.json), nothing invented:
  U  = frame 4 (276 ms): page controls, legend and loading text over a map that has drawn nothing yet (checked by eye and by the mask).
  A  every frame of the run is U, plus a large bright overlay panel with changing 'loading' text from 0.5 s on. The map never draws.
        expected: no map-content evidence, painted/complete/usable not established.
  B  frames before 4.0 s are U + the same changing overlay; from 4.0 s the real frames. The map draws late (4.0 s).
        expected: painted at the first real frame at or after 4.0 s (a static page sends no frames), within 1 s (never at the overlay, never at the 0.3 s legend frame).
  C  the real run unchanged (positive control): painted must be near the unchanged analysis (about 1.1 s), not at the first legend frame.
  D  the real wind-test run (phone): the loading text/legend is present from the first frame, the particles draw at about 6.7 s.
        expected: painted not before 6 s (this is the retained case that the first harness reported as painted at 0.85 s).
  E  frame-directory integrity: the original desktop-brief-cold-1 receipt (frames overwritten by a later batch) is rejected,
        the later receipt of the same id is accepted.
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
    return {k: r.get(k) for k in ('evidence', 'mapContentFrac', 'paintedMs', 'completeMs', 'usableMs', 'status')}


def run(frames_dir):
    frames = Path(frames_dir)
    fails = []

    def expect(name, ok, detail):
        print(('PASS ' if ok else 'FAIL ') + name + ': ' + detail)
        if not ok:
            fails.append(name)

    base = load('ready-live-desktop-warm.json', 'desktop-map-home-returning-cold-1')
    tmp = Path(tempfile.mkdtemp(prefix='perf-controls-'))
    try:
        # C: real run, unchanged
        c = painted_of(base, frames)
        expect('C real run', c['evidence'] == 'map-content' and c['paintedMs'] is not None and 800 <= c['paintedMs'] <= 1600, json.dumps(c))
        # A: overlay over a map that never draws (all frames U); the drag changes nothing but the overlay text
        a_run = copy.deepcopy(base)
        build(a_run, frames, tmp / 'A', 1e12, True)
        a = painted_of(a_run, tmp / 'A')
        expect('A loading overlay, map never draws', a['evidence'] != 'map-content' and a['paintedMs'] is None and a['completeMs'] is None and a['usableMs'] is None and a['status'] == 'no-map-content-evidence', json.dumps(a))
        # B: map draws late, at 4.0 s
        b_run = copy.deepcopy(base)
        build(b_run, frames, tmp / 'B', 4000, True)
        b = painted_of(b_run, tmp / 'B')
        first_real = min(f['t'] * 1000 - base['wallStartMs'] for f in base['frames'] if f['t'] * 1000 - base['wallStartMs'] >= 4000)   # a static page sends no frames
        expect('B delayed map (first real frame at %.0f ms) behind a loading overlay' % first_real, b['evidence'] == 'map-content' and b['paintedMs'] is not None and first_real - 1 <= b['paintedMs'] <= first_real + 1000, json.dumps(b))
        # D: real wind test page, retained
        d_run = load('ready-layers-main-phone.json', 'phone-layer-wind-cold-1')
        d = painted_of(d_run, frames)
        expect('D wind test page (legend + loading text from the first frame)', d['paintedMs'] is None or d['paintedMs'] >= 6000, json.dumps(d))
        # E: integrity of the frame directory
        orig = load('ready-live-desktop.json', 'desktop-brief-cold-1')
        later = load('ready-live-desktop-warm.json', 'desktop-brief-cold-1')
        eo, el = analyse.frame_integrity(orig, frames), analyse.frame_integrity(later, frames)
        expect('E overwritten original rejected, later intact accepted', eo is not None and el is None, f'original: {eo!r}; later: {el!r}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('controls:', 'ALL PASS' if not fails else 'FAILED ' + ', '.join(fails))
    if fails:
        sys.exit(1)


if __name__ == '__main__':
    run(sys.argv[1])
