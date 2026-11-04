"""Offline shape and completeness check for a Morro Bay shore re-read dossier (SC1952-07, M1a).

    python scripts/check_shore_reread_dossier.py <receipt.json>

Checks the committed receipt only: identity sets, hash syntax, baseline references, explicit
changed / unchanged / unverifiable / failed states, and that nothing claims a renewal or approval
or carries raw inventory fields. It never fetches, needs no var/ file and certifies no evidence.
Exit 0 ok, 1 findings, 2 unreadable.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

STATES = {'changed', 'unchanged', 'unverifiable', 'failed'}
RUNS = {
    'hearst-memorial-beach': ['ccc-770'],
    'morro-strand': ['ccc-804', 'ccc-805'],
    'cayucos-beach': ['ccc-797', 'ccc-798'],
    'pismo-beach': ['ccc-868', 'ccc-870'],
    'oceano-beach': ['ccc-875'],
}
POINTS = {p: run for run, ids in RUNS.items() for p in ids}
M2 = {'ccc-792': 792, 'ccc-793': 793, 'ccc-794': 794, 'ccc-795': 795}
SOURCE_HOSTS = {'noaa': 'services2.arcgis.com', 'access': 'services9.arcgis.com', 'terms': 'www.arcgis.com',
                'cdfwRules': 'wildlife.ca.gov', 'noaaLayerMetadata': 'services2.arcgis.com'}
RAW_STATES = {'bytes-identical', 'bytes-differ', 'no-baseline', 'unverifiable'}
RULE_KEYS = ('publisherDate', 'surfperch', 'californiaHalibut', 'licenseScope', 'rawPage')
RUN_SOURCE_KEYS = ('objectClass', 'fullFeatureGeometry', 'selectedGeometry', 'priorGeometryHash', 'rawResponseChange')
# source id -> where its evidence is consumed (a failed or truncated source can never read as unchanged)
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEX40 = re.compile(r'^[0-9a-f]{40}$')
ISO_Z = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')
CLAIM = re.compile(r'\b(approved|renewed|renewal|certified|confirmed|auto-?renew\w*)\b', re.I)
PHONE = re.compile(r'\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b')
MAPS_URL = re.compile(r'(google\.[a-z.]+/maps|maps\.apple\.com|goo\.gl/maps)', re.I)
BAD_KEYS = {'reviewedat', 'expiresat', 'reviewexpiresat', 'accessreviewedat', 'accessreviewexpiresat', 'legalreviewedat',
            'legalreviewexpiresat', 'renewedat', 'approvedat', 'approvedby', 'renewal', 'autorenew', 'description', 'location',
            'globalid', 'thumbnail', 'phone_nmbr', 'phone', 'photo', 'photos'}
PROSE_PATHS = ('approval.statement', 'holds')


def _ok_hash(v):
    return isinstance(v, str) and bool(HEX64.match(v))


def _walk(node, path=''):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f'{path}.{k}' if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f'{path}[{i}]')


def _scan_privacy(doc, errors):
    for path, node in _walk(doc):
        if isinstance(node, dict):
            for k in node:
                low = str(k).lower()
                if low in BAD_KEYS or low.startswith(('photo', 'videourl', 'googlemaps', 'applemaps', 'phone')):
                    errors.append(f'{path or "root"}: field {k!r} is a review/renewal date or raw inventory field')
        elif isinstance(node, str):
            if MAPS_URL.search(node) or PHONE.search(node):
                errors.append(f'{path}: raw inventory link or phone value')
            if not path.startswith(PROSE_PATHS) and CLAIM.search(node):
                errors.append(f'{path}: approval or renewal wording')


def _finding(node, path, errors, need_basis=True):
    if not isinstance(node, dict) or node.get('state') not in STATES:
        errors.append(f'{path}: state must be one of {sorted(STATES)}')
        return None
    if need_basis and not (isinstance(node.get('basis'), str) and node['basis'].strip()):
        errors.append(f'{path}: basis missing')
    if 'old' in node and 'new' in node:
        if node['state'] == 'unchanged' and node['old'] != node['new']:
            errors.append(f'{path}: marked unchanged but old and new differ')
        if node['state'] == 'changed' and node['old'] == node['new']:
            errors.append(f'{path}: marked changed but old and new are equal')
    return node['state']


def _ids(items, key, expected, what, errors):
    seen = [i.get(key) if isinstance(i, dict) else None for i in items]
    dup = sorted({str(s) for s in seen if seen.count(s) > 1})
    if dup:
        errors.append(f'{what}: duplicate {dup}')
    missing, extra = sorted(set(expected) - set(seen)), sorted(str(s) for s in set(seen) - set(expected))
    if missing:
        errors.append(f'{what}: missing {missing}')
    if extra:
        errors.append(f'{what}: unexpected {extra}')


def _sources(doc, errors):
    failed = set()
    items = doc.get('sources')
    if not isinstance(items, list):
        errors.append('sources: must be a list')
        return failed
    _ids(items, 'id', SOURCE_HOSTS, 'sources', errors)
    for s in (i for i in items if isinstance(i, dict)):
        sid, where = s.get('id'), f'sources[{s.get("id")}]'
        acq = (s.get('acquisition') or {}).get('state')
        url, final = urlsplit(str(s.get('url'))), urlsplit(str(s.get('finalUrl')))
        if url.scheme != 'https' or url.netloc != SOURCE_HOSTS.get(sid) or final.netloc != url.netloc:
            errors.append(f'{where}: url must be https on {SOURCE_HOSTS.get(sid)} with no off-host redirect')
        if acq == 'acquired':
            if not (_ok_hash(s.get('sha256')) and isinstance(s.get('bytes'), int) and s['bytes'] > 0
                    and s.get('httpStatus') == 200 and ISO_Z.match(str(s.get('fetchedAt')))):
                errors.append(f'{where}: acquired needs sha256, positive bytes, HTTP 200 and a UTC fetchedAt')
        elif acq in ('failed', 'truncated'):
            failed.add(sid)
            if s.get('sha256') or s.get('bytes'):
                errors.append(f'{where}: a {acq} source cannot carry a hash or byte count as if acquired')
            if (s.get('rawComparison') or {}).get('state') != 'unverifiable':
                errors.append(f'{where}: a {acq} source must have rawComparison unverifiable')
        else:
            errors.append(f'{where}: acquisition.state must be acquired, failed or truncated')
        if (s.get('rawComparison') or {}).get('state') not in RAW_STATES:
            errors.append(f'{where}: rawComparison.state invalid')
        if not str(s.get('privatePath', '')).startswith('var/shore-review/SC1952-07/'):
            errors.append(f'{where}: privatePath must be under var/shore-review/SC1952-07/')
        for ref in s.get('baselineRefs') or []:
            if not (ref.get('path') and str(ref.get('pointer', '')).startswith('/') and _ok_hash(ref.get('sha256'))):
                errors.append(f'{where}: baseline reference needs path, JSON pointer and sha256')
    return failed


def _no_unchanged_when_failed(node, failed_ids, path, errors):
    if failed_ids and isinstance(node, dict) and node.get('state') == 'unchanged':
        errors.append(f'{path}: unchanged although source {sorted(failed_ids)} was not acquired')


def _runs(doc, failed, errors):
    runs = doc.get('runs')
    if not isinstance(runs, list):
        errors.append('runs: must be a list')
        return
    _ids(runs, 'id', RUNS, 'runs', errors)
    states = {}
    for r in (i for i in runs if isinstance(i, dict)):
        rid, where = r.get('id'), f'runs[{r.get("id")}]'
        if rid in RUNS and sorted(r.get('accessIds') or []) != sorted(RUNS[rid]):
            errors.append(f'{where}: accessIds must be {RUNS[rid]}')
        src = r.get('source') or {}
        for k in RUN_SOURCE_KEYS:
            _finding(src.get(k), f'{where}.source.{k}', errors)
        for k in ('objectClass', 'fullFeatureGeometry', 'selectedGeometry'):
            _no_unchanged_when_failed(src.get(k), failed & {'noaa'}, f'{where}.source.{k}', errors)
        if (src.get('rawResponseChange') or {}).get('state') not in (None, 'unverifiable'):
            errors.append(f'{where}.source.rawResponseChange: a raw response change is never a selected-run change')
        sel = src.get('selectedGeometry') or {}
        if sel.get('state') in ('changed', 'unchanged') and not (_ok_hash((sel.get('old') or {}).get('sha256')) and _ok_hash((sel.get('new') or {}).get('sha256'))):
            errors.append(f'{where}.source.selectedGeometry: needs old and new vertex sha256')
        _finding(r.get('access'), f'{where}.access', errors, need_basis=False)
        _finding(r.get('legal'), f'{where}.legal', errors)
        _no_unchanged_when_failed(r.get('access'), failed & {'access'}, f'{where}.access', errors)
        _no_unchanged_when_failed(r.get('legal'), failed & {'cdfwRules'}, f'{where}.legal', errors)
        states[rid] = r
    return states


def _points(doc, failed, runs_by_id, errors):
    pts = doc.get('accessPoints')
    if not isinstance(pts, list):
        errors.append('accessPoints: must be a list')
        return
    _ids(pts, 'id', POINTS, 'accessPoints', errors)
    for p in (i for i in pts if isinstance(i, dict)):
        pid, where = p.get('id'), f'accessPoints[{p.get("id")}]'
        if pid in POINTS and p.get('runId') != POINTS[pid]:
            errors.append(f'{where}: runId must be {POINTS[pid]}')
        if not isinstance(p.get('objectId'), int) or pid != f'ccc-{p.get("objectId")}':
            errors.append(f'{where}: objectId must match the id')
        fields = p.get('fields')
        if not isinstance(fields, dict) or not fields:
            errors.append(f'{where}: fields missing')
            continue
        states = [_finding(v, f'{where}.fields.{k}', errors, need_basis=False) for k, v in fields.items()]
        top = _finding(p, where, errors, need_basis=False)
        if top == 'unchanged' and any(s != 'unchanged' for s in states):
            errors.append(f'{where}: unchanged although a field is {sorted(set(states) - {"unchanged"})}')
        _no_unchanged_when_failed(p, failed & {'access'}, where, errors)
        run = runs_by_id.get(p.get('runId')) if runs_by_id else None
        if run and top != 'unchanged' and (run.get('access') or {}).get('state') == 'unchanged':
            errors.append(f'{where}: run {p.get("runId")} access rollup says unchanged')


def _m2(doc, failed, errors):
    pts = doc.get('m2Candidates')
    if not isinstance(pts, list):
        errors.append('m2Candidates: must be a list')
        return
    _ids(pts, 'id', M2, 'm2Candidates', errors)
    for p in (i for i in pts if isinstance(i, dict)):
        where = f'm2Candidates[{p.get("id")}]'
        if M2.get(p.get('id')) != p.get('objectId'):
            errors.append(f'{where}: objectId must match the id')
        if not (isinstance(p.get('coordinates'), list) and len(p['coordinates']) == 2 and p.get('name')):
            errors.append(f'{where}: name and coordinates required')
        _finding(p, where, errors)
        _no_unchanged_when_failed(p, failed & {'access'}, where, errors)
    est = doc.get('m2EsteroBluffs')
    if not isinstance(est, dict) or est.get('selectionState') not in ('unresolved', 'proposed'):
        errors.append('m2EsteroBluffs: selectionState must be unresolved or proposed')
        return
    for k in ('siteSelectionLimits', 'ownerUrl'):
        _finding(est.get(k), f'm2EsteroBluffs.{k}', errors)
    if est['selectionState'] == 'unresolved':
        if not str(est.get('dependentHold', '')).strip():
            errors.append('m2EsteroBluffs: an unresolved selection must state the held dependent work')
        return
    if 'noaa' in failed or 'noaaLayerMetadata' in failed:
        errors.append('m2EsteroBluffs: cannot be proposed when the NOAA layer or its legend was not acquired')
    for k in ('siteSelectionLimits', 'ownerUrl'):
        if (est.get(k) or {}).get('state') == 'unverifiable':
            errors.append(f'm2EsteroBluffs.{k}: unverifiable, selection must stay unresolved')
    cands = est.get('candidates')
    if not isinstance(cands, list) or not cands:
        errors.append('m2EsteroBluffs: proposed selection needs candidates')
        return
    for c in cands:
        legend = c.get('esiLegend') if isinstance(c, dict) else None
        if not (isinstance(c, dict) and isinstance(c.get('objectId'), int) and c.get('esi') and isinstance(legend, list) and legend
                and all(isinstance(x, dict) and x.get('code') and x.get('legend') for x in legend) and _ok_hash(c.get('coordinatesSha256'))
                and isinstance(c.get('vertices'), int) and c['vertices'] > 0):
            errors.append(f'm2EsteroBluffs: candidate {c.get("objectId") if isinstance(c, dict) else c!r} needs object id, ESI code with legend names, vertices and coordinate hash')


def check(doc):
    """Return a list of problems; empty means the dossier shape is complete."""
    errors = []
    if not isinstance(doc, dict):
        return ['dossier must be a JSON object']
    if doc.get('schemaVersion') != 1 or doc.get('kind') != 'shore-reread-dossier' or doc.get('stage') != 'M1a':
        errors.append('schemaVersion 1, kind shore-reread-dossier and stage M1a required')
    if doc.get('region') != 'morro-bay':
        errors.append('region must be morro-bay')
    if not HEX40.match(str(doc.get('inspectedGitSha'))):
        errors.append('inspectedGitSha must be a 40-hex commit')
    at = doc.get('acquiredAt') or {}
    if not (ISO_Z.match(str(at.get('first'))) and ISO_Z.match(str(at.get('last')))):
        errors.append('acquiredAt first and last must be UTC timestamps')
    if (doc.get('approval') or {}).get('status') != 'none':
        errors.append('approval.status must be none: acquisition is not approval or renewal')
    if not (isinstance(doc.get('commands'), list) and doc['commands'] and all(isinstance(c, dict) and c.get('command') for c in doc['commands'])):
        errors.append('commands: exact commands required')
    if not (isinstance(doc.get('holds'), list) and doc['holds']):
        errors.append('holds: required')
    bases = doc.get('baselines')
    if not (isinstance(bases, list) and bases and all(isinstance(b, dict) and b.get('path') and _ok_hash(b.get('sha256')) for b in bases)):
        errors.append('baselines: each needs a repository path and sha256')
    priv = doc.get('privateFiles')
    if not (isinstance(priv, list) and priv and all(isinstance(p, dict) and str(p.get('path', '')).startswith('var/shore-review/SC1952-07/') and _ok_hash(p.get('sha256')) for p in priv)):
        errors.append('privateFiles: relative var/shore-review/SC1952-07/ paths with sha256 required')
    failed = _sources(doc, errors)
    runs_by_id = _runs(doc, failed, errors)
    _points(doc, failed, runs_by_id, errors)
    terms = doc.get('terms') or {}
    for k in ('rawItem', 'licenseInfo'):
        _finding(terms.get(k), f'terms.{k}', errors)
    _no_unchanged_when_failed(terms.get('licenseInfo'), failed & {'terms'}, 'terms.licenseInfo', errors)
    rules = doc.get('rules') or {}
    for k in RULE_KEYS:
        _finding(rules.get(k), f'rules.{k}', errors)
        _no_unchanged_when_failed(rules.get(k), failed & {'cdfwRules'}, f'rules.{k}', errors)
    _m2(doc, failed, errors)
    _scan_privacy(doc, errors)
    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('usage: check_shore_reread_dossier.py <receipt.json>', file=sys.stderr)
        return 2
    try:
        doc = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        print(f'check_shore_reread_dossier: unreadable: {error}', file=sys.stderr)
        return 2
    errors = check(doc)
    for e in errors:
        print('FAIL ' + e)
    if not errors:
        print('OK shore re-read dossier complete: 5 runs, 8 access points, 4 M2 candidates (structure only, not approval)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
