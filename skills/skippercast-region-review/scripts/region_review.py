#!/usr/bin/env python3
"""Region review: deterministic checks on a region-build run -> <run>/REVIEW-PACKET/review.json (exit 0 all PASS, 1 any
FAIL, 2 refused); --check validates <run>/REVIEW.md and writes nothing. Stdlib plus skippercast.platform; no datum
conversion; reviewer independence comes from BUILD.json run metadata, never profile names. Machine-valid is not acceptance.
"""
import argparse, hashlib, json, math, os, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
from skippercast.platform import depth_contours as dc  # noqa: E402
from skippercast.platform.contracts import atomic_json, load_catalogs, load_region  # noqa: E402

BANNER = 'Machine-valid packet: review-required, not acceptance.'
MD_BANNER = 'Machine-valid ≠ accepted. Agent first review; human gates remain.'
CELL_DEG = 0.005
VERDICTS = {'PASS', 'RETURN'}
KEYS = ('region_id', 'build_sha256', 'run.author_runtime', 'run.author_family', 'inputs', 'outputs', 'supported_water_fraction')


def loader(region_id):
    return load_region(region_id), load_catalogs()[1]


def result(ident, bad, ok):
    """One check: PASS with `ok`, or FAIL with the count and up to 10 example locations."""
    detail = f'{len(bad)} problem(s): ' + '; '.join(bad[:10]) if bad else ok
    return {'id': ident, 'verdict': 'FAIL' if bad else 'PASS', 'detail': detail}


def read_build(folder):
    build = json.loads((folder / 'BUILD.json').read_text())
    for head, _, tail in (key.partition('.') for key in KEYS):
        if ((build.get(head) or {}).get(tail) if tail else build.get(head)) is None:
            raise ValueError(f"BUILD.json lacks {head}{'.' if tail else ''}{tail}")
    return build


def segments(outputs):
    """Every segment of every `contour` feature across all outputs, as (feature label, depth, ax, ay, bx, by)."""
    found = []
    for rel, collection in outputs:
        for i, feature in enumerate(collection.get('features') or []):
            p = feature.get('properties') or {}
            if p.get('kind') == 'contour':
                for line in dc.feature_lines(feature['geometry']):
                    found += [(f"{rel}#{feature.get('id', i)}", p.get('depth_ft'), *a[:2], *b[:2]) for a, b in zip(line, line[1:])]
    return found


def touches(s, t):
    """True when segments s and t properly cross or touch (orientation predicates on the raw floats)."""
    def orient(ax, ay, bx, by, cx, cy):
        v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        return (v > 0) - (v < 0)
    cases = ((s[2:], t[2:4]), (s[2:], t[4:]), (t[2:], s[2:4]), (t[2:], s[4:]))
    o = [orient(*seg, *pt) for seg, pt in cases]
    on = lambda px, py, qx, qy, rx, ry: min(px, qx) <= rx <= max(px, qx) and min(py, qy) <= ry <= max(py, qy)
    return (o[0] != o[1] and o[2] != o[3]) or any(o[i] == 0 and on(*seg, *pt) for i, (seg, pt) in enumerate(cases))


def crossings(segs):
    """Locations where contours of different depths cross or touch, via a uniform CELL_DEG bucket index."""
    cells, seen, bad = {}, set(), []
    for n, (_, _, ax, ay, bx, by) in enumerate(segs):
        for gx in range(math.floor(min(ax, bx) / CELL_DEG), math.floor(max(ax, bx) / CELL_DEG) + 1):
            for gy in range(math.floor(min(ay, by) / CELL_DEG), math.floor(max(ay, by) / CELL_DEG) + 1):
                cells.setdefault((gx, gy), []).append(n)
    for members in cells.values():
        for i, m in enumerate(members):
            for k in members[i + 1:]:
                s, t = segs[m], segs[k]
                if s[1] != t[1] and (m, k) not in seen:
                    seen.add((m, k))
                    if touches(s, t):
                        bad.append(f'{s[0]} ({s[1]} ft) x {t[0]} ({t[1]} ft) near {s[2]:.5f},{s[3]:.5f}')
    return bad


def check_output(folder, out, build, region, sources, bad):
    """Run the per-output checks on one BUILD.json output; returns (path, collection) or None."""
    rel, path = str(out.get('path')), (folder / str(out.get('path'))).resolve()
    if folder not in path.parents or not path.is_file():
        return bad['intact'].append(f'{rel}: outside the run folder or missing')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != out.get('sha256'):
        bad['intact'].append(f'{rel}: sha256 differs from BUILD.json')
    collection = json.loads(data)
    p, inputs = collection.get('provenance') or {}, {i.get('source_id'): i.get('sha256') for i in build['inputs']}
    listed = [s for s in p.get('sources') or [] if isinstance(s, dict)]
    if p.get('region_id') != build['region_id'] or p.get('units') != 'ft' or p.get('interval_ft') != dc.INTERVAL_FT \
            or not listed or not isinstance(p.get('sources_omitted'), list):
        bad['prov'].append(f'{rel}: region_id, units, interval_ft, sources or sources_omitted wrong')
    entries = {s.get('source_id'): s for s in listed}
    for sid, s in entries.items():
        if not dc.SHA256.fullmatch(str(s.get('sha256'))) or not dc.YEAR.fullmatch(str(s.get('survey_date'))) \
                or not s.get('vertical_datum') or s.get('sha256') != inputs.get(sid):
            bad['prov'].append(f'{rel}: source {sid} sha256, survey_date, datum or BUILD input sha')
        want = (sources.get(sid) or {}).get('vertical_datum') or dc.UNVERIFIED_DATUM
        if s.get('vertical_datum') != want:
            bad['datum'].append(f'{rel}: source {sid} datum {s.get("vertical_datum")!r} is not the catalog {want!r}')
    for i, f in enumerate(collection.get('features') or []):
        fp = f.get('properties') or {}
        source = entries.get(fp.get('source_id'))
        if source is None:
            bad['prov'].append(f"{rel}#{f.get('id', i)}: feature source {fp.get('source_id')!r} not listed in provenance.sources")
        mine = source.get('vertical_datum') if source is not None else None
        if not fp.get('vertical_datum') or fp['vertical_datum'] != mine:
            bad['datum'].append(f"{rel}#{f.get('id', i)}: feature datum missing or not its source entry's")
    try:
        if p.get('sources_omitted') != dc.omitted_sources(region, sources, list(entries)):
            bad['omit'].append(f'{rel}: sources_omitted misstated')
    except ValueError as err:
        bad['omit'].append(f'{rel}: {err}')
    try:
        light = json.dumps(dc.overview_contours(collection), ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
        if len(data) > dc.MAX_BYTES or len(light.encode()) > dc.OVERVIEW_MAX_BYTES:
            bad['size'].append(f'{rel}: over MAX_BYTES or the overview over OVERVIEW_MAX_BYTES')
    except (ValueError, KeyError, TypeError) as err:
        bad['size'].append(f'{rel}: overview not computable ({err})')
    # A held output is justified by a non-approved source or, as region_intake holds every row of one, a draft region.
    recomputed, held = dc.held_sources(collection, sources), p.get('publication_held') is True
    if not (held == (out.get('publication_held') is True) == (bool(recomputed) or region.get('status') == 'draft')) \
            or p.get('held_sources', []) != recomputed or held != (Path(rel).parts[:1] == ('held',)):
        bad['held'].append(f'{rel}: publication_held, held_sources or held/ location disagree')
    return rel, collection


def review(folder):
    build = read_build(folder)
    region, sources = loader(build['region_id'])
    bad = {k: [] for k in ('intact', 'prov', 'datum', 'omit', 'size', 'held')}
    loaded = [c for out in build['outputs'] if (c := check_output(folder, out, build, region, sources, bad))]
    if not build['outputs']:
        bad['intact'].append('BUILD.json lists no outputs')
    water = build['supported_water_fraction']
    water_ok = isinstance(water, (int, float)) and not isinstance(water, bool) and math.isfinite(water) and 0 <= water <= 1
    checks = [result('outputs-intact', bad['intact'], f"{len(build['outputs'])} output(s) present, sha256 match"),
              result('provenance-complete', bad['prov'], 'provenance complete; source sha256 equal BUILD inputs'),
              result('datum-verbatim', bad['datum'], 'datums equal the catalog verbatim'),
              result('omitted-stated', bad['omit'], 'sources_omitted equals the recomputed list'),
              result('no-depth-crossings', crossings(segments(loaded)), 'no contours of different depths cross or touch'),
              result('size-budget', bad['size'], 'within MAX_BYTES and OVERVIEW_MAX_BYTES'),
              result('held-flags', bad['held'], 'held flags, held_sources and locations agree'),
              result('supported-water', [] if water_ok else [f'supported_water_fraction {water!r} not in [0, 1]'],
                     f'supported_water_fraction {water} (coverage not judged here)')]
    candidates = [h['source_id'] for _, c in loaded for h in dc.held_sources(c, sources) if h['review_status'] == 'candidate']
    failed = [c['id'] for c in checks if c['verdict'] == 'FAIL']
    held_any = any(o.get('publication_held') is True for o in build['outputs'])
    publishable = not failed and not held_any and region.get('status') in ('active', 'preview')
    reason = 'none' if publishable else f'source-candidate:{candidates[0]}' if candidates else \
        'region-draft' if region.get('status') == 'draft' else f'check-failed:{failed[0]}' if failed else 'none'
    return {'schema': 'region-review-v1', 'banner': BANNER, 'region_id': build['region_id'],
            'build_sha256': build['build_sha256'], 'author_runtime': build['run']['author_runtime'],
            'author_family': build['run']['author_family'], 'checks': checks, 'publishable': publishable, 'held_reason': reason}


def check_md(folder):
    """(REVIEW.md problems as 'line <n>: ...', region_id, overall)."""
    build, packet = read_build(folder), json.loads((folder / 'REVIEW-PACKET/review.json').read_text())
    lines, errors, fields, rows, overall = (folder / 'REVIEW.md').read_text().splitlines(), [], {}, {}, None
    if MD_BANNER not in (line.strip() for line in lines):
        errors.append(f'line 2: missing banner {MD_BANNER!r}')
    machine = {c['id']: c['verdict'] for c in packet['checks']}
    for n, line in enumerate(lines, 1):
        if m := re.fullmatch(r'(Build-SHA256|Reviewer-Runtime|Reviewer-Family):(.*)', line):
            fields[m[1]] = (n, m[2].strip())
        elif m := re.fullmatch(r'Overall:\s*(\S*)\s*', line):
            overall = (n, m[1])
        elif line.startswith('|') and not re.match(r'\|\s*(check\s*\||-)', line):
            ident, verdict = ([c.strip() for c in line.strip().strip('|').split('|')] + [''])[:2]
            if ident in rows or (ident not in machine and ident != 'visual'):
                errors.append(f'line {n}: check id {ident!r} duplicated or unknown')
            elif verdict not in (VERDICTS | {'not-visually-inspected'} if ident == 'visual' else VERDICTS):
                errors.append(f'line {n}: verdict {verdict!r} not allowed')
            elif verdict == 'PASS' and machine.get(ident) == 'FAIL':
                errors.append(f'line {n}: {ident} PASS but review.json says FAIL')
            rows.setdefault(ident, verdict)
    errors += [f'line {len(lines)}: check {i} missing' for i in [*machine, 'visual'] if i not in rows]
    n, sha = fields.get('Build-SHA256', (0, ''))
    if sha != build['build_sha256'] or sha != packet['build_sha256']:
        errors.append(f'line {n}: Build-SHA256 differs from BUILD.json or review.json')
    n, family = fields.get('Reviewer-Family', (0, ''))
    if not family or family.lower() == str(build['run']['author_family']).strip().lower():
        errors.append(f'line {n}: Reviewer-Family empty or the builder family')
    n, runtime = fields.get('Reviewer-Runtime', (0, ''))
    if not runtime or runtime == str(build['run']['author_runtime']).strip():
        errors.append(f'line {n}: Reviewer-Runtime empty or the builder runtime')
    if overall is None or overall[1] not in VERDICTS:
        errors.append(f'line {overall[0] if overall else len(lines)}: Overall must be PASS or RETURN')
    elif overall[1] == 'PASS' and 'RETURN' in rows.values():
        errors.append(f'line {overall[0]}: Overall PASS with a RETURN row')
    return errors, build['region_id'], overall and overall[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--check', action='store_true', help='validate <run>/REVIEW.md; writes nothing')
    args = parser.parse_args(argv)
    folder, repo = Path(os.path.realpath(args.run)), Path(os.path.realpath(REPO))
    try:
        if folder == repo or repo in folder.parents:
            raise ValueError(f'run folder must be outside the repository: {folder}')
        if args.check:
            errors, region_id, overall = check_md(folder)
            for error in errors:
                print(f'REVIEW.md {error}', file=sys.stderr)
            if not errors:
                print(f'REVIEW OK {region_id} {overall}')
            return 1 if errors else 0
        target = folder / 'REVIEW-PACKET/review.json'
        if target.exists():
            raise ValueError(f'refusing to overwrite {target}')
        packet = review(folder)
        atomic_json(target, packet)
        for check in packet['checks']:
            print(f"{check['verdict']} {check['id']}: {check['detail']}")
        print(f"publishable {packet['publishable']} held_reason {packet['held_reason']}")
        return 1 if any(c['verdict'] == 'FAIL' for c in packet['checks']) else 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
        print(f'region_review: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
