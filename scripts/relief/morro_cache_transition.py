#!/usr/bin/env python3
"""Cache-transition acceptance reader for a Morro update or rollback (M26).

Offline only: it reads saved observations and never dispatches, fetches, touches credentials or changes the
service worker. It answers one question for the release lead: after switching the served build from one
generation to another, does the saved evidence show a phone that is *fully* on the target generation?

M24 (local loopback, agent-work ``finish/morro/stage-update-session``) showed why this needs its own reader. A
phone that already had Morro open gets the new page shell and the new /sources credits at once (both are
``max-age=0``), while each contour file keeps its own HTTP-cache clock (``/regions/*`` ``max-age=120``,
``stale-while-revalidate=300``). So for minutes a warm phone shows the new shell and credits over the *old*
contour lines, and a z15 recovery does not prove z11. A reader that looks at the shell, the credits or one zoom
band alone would call such a phone "updated" (or "rolled back") too early.

ACCEPT requires all of:

* the last visit is on the target build and the /sources credits read after the switch are the target's;
* for BOTH zoom bands (``detail`` = ``depth-contours.geojson``, ``overview`` = ``depth-contours-overview.geojson``)
  the band's LAST visit is on the target build, received the target contour bytes, drew at least one line and
  saw the target pointer (HTTP 200 with the exact pointer bytes when the target has one; absent or 404 when it
  has none);
* the served readback (what a cold client gets from the origin after the switch) equals the target identity
  for pointer, detail, overview and /sources, so the phone matched what is actually served;
* no visit drew pointer-bound contour bytes (the generation that has a pointer, ft-v3 for Morro v2) without
  first receiving that exact pointer.

Anything else is REJECT with named reasons, e.g. ``stale-band:overview`` for the M24 rollback window where z15
had recovered and z11 still drew nothing from the cached v2 overview. Input problems (unknown schema, a target
identical to the previous generation in a band, so staleness would be undetectable) exit 2 without a verdict.

Exit status: 0 ACCEPT, 1 REJECT, 2 unusable input. The verdict is a reading of saved evidence, not an R8
verdict, a deployment record or release authority.

Usage:
  morro_cache_transition.py OBSERVATIONS.json            one transition (schema sc-morro-cache-observations/1)
  morro_cache_transition.py --m24 PHONE.json RECEIPT.json   every theme x {update, rollback} in an M24 run,
                                                          with the verdict after each visit (timeline)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCHEMA = 'sc-morro-cache-observations/1'
REGION = 'morro-bay'
POINTER_PATH = f'/catalog/relief/{REGION}.json'
BAND_PATHS = {
    'detail': f'/regions/{REGION}/depth-contours.geojson',
    'overview': f'/regions/{REGION}/depth-contours-overview.geojson',
}
BANDS = tuple(BAND_PATHS)
# web/map/depth-contours.ts DETAIL_ZOOM (12, MapLibre) + engine.ts ZOOM_OFFSET (1): the `?view=` zoom from which
# the Chart draws the full contours. Used only for a visit that fetched no contour file at all.
DETAIL_VIEW_ZOOM = 13
IDENTITY_KEYS = ('build', 'pointer', 'detail', 'overview', 'sources')


class Unusable(ValueError):
    """The observations cannot support any verdict (exit 2)."""


def _identity(raw, label):
    if not isinstance(raw, dict) or set(raw) != set(IDENTITY_KEYS):
        raise Unusable(f'{label}: identity needs exactly {", ".join(IDENTITY_KEYS)}')
    for key in IDENTITY_KEYS:
        if raw[key] is not None and not (isinstance(raw[key], str) and raw[key]):
            raise Unusable(f'{label}.{key}: expected a non-empty string or null')
    for key in ('build', 'detail', 'overview', 'sources'):
        if raw[key] is None:
            raise Unusable(f'{label}.{key}: required')
    return dict(raw)


def visit_band(visit):
    """The zoom band a visit observed: by the contour file it fetched, else by its `?view=` zoom."""
    paths = {f.get('path') for f in visit.get('fetches', [])}
    seen = [band for band, path in BAND_PATHS.items() if path in paths]
    if len(seen) == 1:
        return seen[0]
    if len(seen) > 1:
        return 'detail'  # the Chart keeps the full file for the rest of a visit once it loads
    zoom = visit.get('zoom')
    if not isinstance(zoom, (int, float)):
        return None
    return 'detail' if zoom >= DETAIL_VIEW_ZOOM else 'overview'


def _last(visit, path):
    hits = [f for f in visit.get('fetches', []) if f.get('path') == path]
    return hits[-1] if hits else None


def _drawn(visit):
    try:
        return int(visit.get('contours_drawn') or 0)
    except (TypeError, ValueError):
        return 0


def load(doc):
    """Validate one observations document; returns (target, previous, visits, sources, served)."""
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        raise Unusable(f'schema must be {SCHEMA}')
    if doc.get('direction') not in ('update', 'rollback'):
        raise Unusable('direction must be update or rollback')
    target = _identity(doc.get('target'), 'target')
    previous = _identity(doc.get('previous'), 'previous')
    for key in ('build',) + BANDS:
        if target[key] == previous[key]:
            raise Unusable(f'target and previous share {key}; a stale {key} could not be told apart')
    if (target['pointer'] is None) == (previous['pointer'] is None):
        raise Unusable('exactly one generation must carry the pointer (the pointer-bound contour generation)')
    visits = doc.get('visits')
    if not isinstance(visits, list) or not all(isinstance(v, dict) for v in visits):
        raise Unusable('visits must be a list of objects')
    served = doc.get('served')
    if served is not None:
        served = _identity(served, 'served')
    return target, previous, visits, doc.get('sources_sha256'), served


def _generation(sha, target, previous, band):
    if sha == target[band]:
        return 'target'
    if sha == previous[band]:
        return 'previous'
    return 'foreign'


def judge(doc):
    """Verdict for one transition: {'verdict': 'ACCEPT'|'REJECT', 'reasons': [...], 'bands': {...}}."""
    target, previous, visits, sources, served = load(doc)
    bound = target if target['pointer'] else previous  # the generation whose contours need the pointer
    reasons, bands = [], {}

    for visit in visits:  # safety: pointer-bound bytes drawn without the exact pointer, on any visit
        band = visit_band(visit)
        contour = _last(visit, BAND_PATHS[band]) if band else None
        pointer = _last(visit, POINTER_PATH)
        if (_drawn(visit) > 0 and contour and contour.get('sha256') == bound[band]
                and not (pointer and pointer.get('status') == 200 and pointer.get('sha256') == bound['pointer'])):
            reasons.append(f'unsafe:{visit.get("name", "?")}:pointer-bound-{band}-drawn-without-pointer')

    if not visits:
        reasons.append('no-visits')
    elif visits[-1].get('build') != target['build']:
        reasons.append('shell-not-target')
    if sources != target['sources']:
        reasons.append('sources-not-target' if sources else 'sources-not-read')

    for band in BANDS:
        last = [v for v in visits if visit_band(v) == band][-1:]
        if not last:
            bands[band] = 'not-observed'
            reasons.append(f'band-not-observed:{band}')
            continue
        visit = last[0]
        contour = _last(visit, BAND_PATHS[band])
        pointer = _last(visit, POINTER_PATH)
        gen = _generation(contour.get('sha256'), target, previous, band) if contour and contour.get('status') == 200 else 'missing'
        problems = []
        if visit.get('build') != target['build']:
            problems.append('shell')
        if gen == 'previous':
            problems.append('stale')
        elif gen in ('foreign', 'missing'):
            problems.append(gen)
        if target['pointer']:
            if not (pointer and pointer.get('status') == 200 and pointer.get('sha256') == target['pointer']):
                problems.append('pointer')
        elif pointer and pointer.get('status') == 200:
            problems.append('pointer')
        if _drawn(visit) <= 0:
            problems.append('not-drawn')
        bands[band] = {'visit': visit.get('name'), 'generation': gen, 'drawn': _drawn(visit),
                       'pointer': pointer.get('status') if pointer else None, 'problems': problems}
        reasons.extend(f'{p}-band:{band}' if p != 'stale' else f'stale-band:{band}' for p in problems)

    if served is None:
        reasons.append('served-not-read')
    else:
        reasons.extend(f'served-mismatch:{k}' for k in IDENTITY_KEYS if served[k] != target[k])

    return {'direction': doc['direction'], 'verdict': 'REJECT' if reasons else 'ACCEPT', 'reasons': reasons, 'bands': bands}


def timeline(doc):
    """The verdict after each visit in order; the first ACCEPT is when the saved evidence first proves the switch."""
    rows = []
    for n in range(1, len(doc['visits']) + 1):
        result = judge(dict(doc, visits=doc['visits'][:n]))
        visit = doc['visits'][n - 1]
        rows.append({'visit': visit.get('name'), 't_after_switch_s': visit.get('t_after_switch_s'),
                     'verdict': result['verdict'], 'reasons': result['reasons']})
    return rows


def from_m24(row, receipt):
    """Two observation documents (update, rollback) from one theme row of an M24 phone.json and its receipt."""
    builds, want, sources = receipt['builds'], receipt['want'], receipt['want_sources']
    ident = {k: {'build': builds[k], 'pointer': want[k]['pointer'], 'detail': want[k]['detail'],
                 'overview': want[k]['overview'], 'sources': sources[k]} for k in ('v1', 'v2')}
    ref, session = row['ref'], row['session']

    def served(gen):
        z15, z11 = ref[f'{gen}_z15'], ref[f'{gen}_z11']
        ptr = _last(z15, POINTER_PATH)
        detail, overview = _last(z15, BAND_PATHS['detail']), _last(z11, BAND_PATHS['overview'])
        return {'build': z15.get('build'), 'pointer': ptr['sha256'] if ptr and ptr.get('status') == 200 else None,
                'detail': detail and detail.get('sha256'), 'overview': overview and overview.get('sha256'),
                'sources': (z15.get('sources') or {}).get('sha256')}

    docs = []
    for direction, prefix, switch, old, new, key in (('update', 'up', 'switch_up_ms', 'v1', 'v2', 'up'),
                                                     ('rollback', 'back', 'switch_back_ms', 'v2', 'v1', 'back')):
        visits = []
        for name, v in session['visits'].items():
            if name.startswith(prefix):
                visits.append(dict(v, name=name, t_after_switch_s=round((v['at_ms'] - session[switch]) / 1000)))
        docs.append({'schema': SCHEMA, 'direction': direction, 'label': f"{row['theme']}-{direction}",
                     'target': ident[new], 'previous': ident[old], 'visits': visits,
                     'sources_sha256': (session['sources'].get(key) or {}).get('sha256'), 'served': served(new)})
    return docs


def main(argv=None):
    parser = argparse.ArgumentParser(description='Morro cache-transition acceptance reader (M26); offline only.')
    parser.add_argument('observations', type=Path, help='observations JSON, or M24 phone.json with --m24')
    parser.add_argument('--m24', type=Path, metavar='RECEIPT', help='read an M24 phone.json with its receipt.json')
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.observations.read_bytes())
        if args.m24:
            receipt = json.loads(args.m24.read_bytes())
            docs = [d for row in raw for d in from_m24(row, receipt)]
            out = [{'label': d['label'], 'final': judge(d), 'timeline': timeline(d)} for d in docs]
            ok = all(r['final']['verdict'] == 'ACCEPT' for r in out)
        else:
            result = judge(raw)
            out, ok = result, result['verdict'] == 'ACCEPT'
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'UNUSABLE: {error}', file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
