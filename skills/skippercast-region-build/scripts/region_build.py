#!/usr/bin/env python3
"""Region build: a checked INTAKE.csv -> preflight -> depth-contour builder -> BUILD.json, all in the private run folder.

Stdlib only. The preflight and the builder need the survey stack, so they run as subprocesses of --python. Never
passes a skip or missing-file row, never writes in the repository, never downloads, and has no terrain code.
"""
import argparse, csv, hashlib, json, math, os, re, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
from skippercast.platform.contracts import atomic_json, load_catalogs, load_region  # noqa: E402
from skippercast.platform.depth_contours import CELL_M  # noqa: E402

GRID_ADAPTERS = ('geotiff', 'bag')
INTAKE = REPO / 'skills/skippercast-region-intake/scripts/region_intake.py'
CORRECT = REPO / 'skills/skippercast-region-correct/scripts/region_correct.py'
PREFLIGHT, BUILDER = REPO / 'scripts/preflight_native_grid.py', REPO / 'scripts/build_depth_contours.py'
M_PER_DEG_LAT, M_PER_DEG_LON_EQ = 110_540, 111_320


class BuildError(Exception):
    pass


def default_run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def default_loader(region_id):
    return load_region(region_id), load_catalogs()[1]


def call(run, cmd):
    """Run one subprocess; on failure the message names the command (file names only) and its stderr tail."""
    done = run(cmd)
    if done.returncode != 0:
        short = ' '.join(Path(c).name if os.sep in c else c for c in (str(c) for c in cmd))
        tail = '\n'.join((done.stderr or '').strip().splitlines()[-5:])
        raise BuildError(f'command failed (exit {done.returncode}): {short}\n{tail}')
    return done.stdout


def survey_id(path):
    """BAG survey id from the file name: the prefix before the first '_' after an optional 'BAG__'."""
    name = Path(path).name.removeprefix('BAG__').split('_')[0]
    return name if re.fullmatch(r'[A-Z]\d{5}', name) else None


def select(rows, sources):
    """(approved rows, held rows, not_built) from INTAKE rows in INTAKE order; skip and missing-file never pass."""
    not_built, usable = [], {}
    for row in rows:
        sid = row['source_id']
        if row['use'] not in ('publish', 'held'):
            not_built.append({'source_id': sid, 'reason': row['held_reason'] if row['held_reason'] != 'none' else row['use']})
            continue
        adapter = sources.get(sid, {}).get('adapter') or 'none'
        if adapter not in GRID_ADAPTERS:
            not_built.append({'source_id': sid, 'reason': f'unsupported-adapter:{adapter}'})
            continue
        usable.setdefault(sid, []).append({**row, 'adapter': adapter})
    chosen = []
    for sid, found in usable.items():
        if len(found) > 1:
            not_built.append({'source_id': sid, 'reason': f'multi-file-source:{sid}:{len(found)}'})
        elif found[0]['adapter'] == 'bag' and not survey_id(found[0]['local_path']):
            not_built.append({'source_id': sid, 'reason': 'bag-survey-id-unknown'})
        else:
            chosen.append(found[0])
    return [r for r in chosen if r['use'] == 'publish'], [r for r in chosen if r['use'] == 'held'], not_built


def inside(folder, rel):
    """<run>/<rel> resolved; an empty, absolute or escaping path is refused (EC files live in the run folder)."""
    path = Path(os.path.realpath(folder / rel))
    if not rel or Path(rel).is_absolute() or folder not in path.parents:
        raise BuildError(f'EC path must stay inside the run folder: {rel!r}')
    return str(path)


def grid_paths(folder, row, ec):
    """Set row['grid'] (preflight and --grid) and row['provenance'] (--provenance, or ''). Without EC: local_path, ''.

    With INTAKE-EC.csv, a publish/held row uses <run>/<ec_path> unless its ec_status is not_corrected, plus
    <run>/<provenance_path> when non-empty. A REFUSED row must be skip, so it never reaches a command."""
    row['grid'], row['provenance'], row['ec_used'] = row['local_path'], '', False
    if not ec:
        return
    if row['ec_status'] == 'REFUSED' and row['use'] != 'skip':
        raise BuildError(f"INTAKE-EC.csv: REFUSED row {row['source_id']} has use {row['use']}, not skip")
    if row['use'] in ('publish', 'held'):
        if row['ec_status'] != 'not_corrected':
            row['grid'], row['ec_used'] = inside(folder, row['ec_path']), True
        if row['provenance_path']:
            row['provenance'] = inside(folder, row['provenance_path'])


def builder_cmd(python, region_id, flag, out, rows):
    cmd = [python, str(BUILDER), '--region', region_id, flag, str(out)]
    for row in rows:
        cmd += ['--grid', f"{row['source_id']}={row['grid']}"]
    for row in rows:
        if row['adapter'] == 'bag':
            cmd += ['--bag-survey', f"{row['source_id']}={survey_id(row['local_path'])}"]
    for row in rows:
        if row['provenance']:
            cmd += ['--provenance', f"{row['source_id']}={row['provenance']}"]
    return cmd


def ec_record(folder, run, python):
    """Run region_correct.py --check (non-zero stops the build) and copy the BUILD.json `ec` block from EC.json."""
    if not (folder / 'EC.json').is_file():
        raise BuildError('INTAKE-EC.csv without EC.json')
    call(run, [python, str(CORRECT), '--check', str(folder)])
    doc = json.loads((folder / 'EC.json').read_text())
    return {'ec_sha256': doc['ec_sha256'], 'ec_version': doc['ec_version'],
            'corrected': [s['source_id'] for s in doc['sources'] if s['status'] != 'REFUSED'],
            'not_corrected': [{'source_id': n['source_id'], 'reason': n['reason']} for n in doc['not_corrected']]}


def file_sha256(path):
    with open(path, 'rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def measure(collection, bounds):
    """(contours per depth, survey-edge metres, supported water fraction) under the bbox mid-latitude approximation."""
    west, south, east, north = bounds
    kx, ky = M_PER_DEG_LON_EQ * math.cos(math.radians((south + north) / 2)), M_PER_DEG_LAT
    area = (east - west) * kx * (north - south) * ky
    per_depth, edge = {}, 0.0
    for feature in collection['features']:
        lines, kind = feature['geometry']['coordinates'], feature['properties']['kind']
        if kind == 'contour':
            depth = feature['properties']['depth_ft']
            per_depth[depth] = per_depth.get(depth, 0) + len(lines)
        elif kind == 'survey-edge':
            edge += sum(math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * ky) for line in lines for a, b in zip(line, line[1:]))
    blocks = sum(s['supported_blocks'] for s in collection['provenance']['sources'])
    return ({str(d): per_depth[d] for d in sorted(per_depth)}, round(edge, 1),
            round(min(blocks * CELL_M ** 2 / area, 1.0), 6))


def planted(folder, names):
    """The first managed output name that is a symlink in the run folder (atomic_json and the builder follow links)."""
    return next((name for name in names if (folder / name).is_symlink()), None)


def build(args, run=default_run, loader=default_loader):
    folder, repo = Path(os.path.realpath(args.run)), Path(os.path.realpath(REPO))
    if folder == repo or repo in folder.parents:
        raise BuildError(f'--run must be outside the repository: {folder}')
    if name := planted(folder, ('BUILD.json', 'BUILD.json.tmp', 'candidate', 'held')):
        raise BuildError(f'refusing a symlinked {name} in the run folder')
    if not (folder / 'INTAKE.csv').is_file():
        raise BuildError(f'No INTAKE.csv in {folder}')
    if os.path.lexists(folder / 'BUILD.json'):
        raise BuildError(f'Refusing to overwrite {folder / "BUILD.json"}')
    if not (args.author_runtime or '').strip() or not re.fullmatch(r'[a-z][a-z0-9-]*', args.author_family or ''):
        raise BuildError('--author-runtime must be non-empty and --author-family must match ^[a-z][a-z0-9-]*$')
    call(run, [args.python, str(INTAKE), '--check', str(folder)])
    ec = ec_record(folder, run, args.python) if (folder / 'INTAKE-EC.csv').exists() else None
    with open(folder / ('INTAKE-EC.csv' if ec else 'INTAKE.csv'), newline='') as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        grid_paths(folder, row, ec)
    region, sources = loader(args.region_id)
    approved, held, not_built = select(rows, sources)
    preflight = []
    for row in approved + held:
        if row['adapter'] == 'geotiff':
            datum = row['vertical_datum'] or 'undeclared'
            out = call(run, [args.python, str(PREFLIGHT), row['grid'], '--vertical-datum', datum,
                             '--vertical-unit', 'metre', '--vertical-sign', 'elevation-up'])
            line = json.loads(out.strip().splitlines()[-1])
            preflight.append({k: v for k, v in line.items() if k not in ('path', 'local_path')})
    outputs = []
    for rel, flag, chosen in ((f'candidate/{region["id"]}.geojson', '--output', approved),
                              (f'held/{region["id"]}.geojson', '--held-output', held)):
        if not chosen:
            continue
        call(run, builder_cmd(args.python, region['id'], flag, folder / rel, chosen))
        data = (folder / rel).read_bytes()
        per_depth, edge, water = measure(json.loads(data), region['bounds'])
        reason = 'none' if flag == '--output' else next(
            (r['held_reason'] for r in chosen if r['held_reason'].startswith('source-candidate:')), chosen[0]['held_reason'])
        outputs.append({'path': rel, 'sha256': hashlib.sha256(data).hexdigest(), 'publication_held': flag != '--output',
                        'held_reason': reason, 'contours_per_depth': per_depth, 'survey_edge_m': edge,
                        'supported_water_fraction': water})
    pairs = json.dumps(sorted([o['path'], o['sha256']] for o in outputs), separators=(',', ':'))
    reasons = [o['held_reason'] for o in outputs if o['held_reason'] != 'none']
    record = {'schema': 'region-build-v1', 'region_id': region['id'],
              'build_sha256': hashlib.sha256(pairs.encode()).hexdigest(),
              'run': {'author_runtime': args.author_runtime, 'author_family': args.author_family, 'intake_rows': len(rows)},
              'inputs': [{'source_id': r['source_id'], 'sha256': r['sha256'],
                          **({'ec_sha256': file_sha256(r['grid'])} if r['ec_used'] else {})} for r in approved + held],
              'outputs': outputs, 'not_built': not_built, 'preflight': preflight,
              'supported_water_fraction': round(min(sum(o['supported_water_fraction'] for o in outputs), 1.0), 6),
              'supported_water_note': 'upper bound when outputs overlap',
              'held_reason': (reasons[0] if reasons else 'none') if outputs else 'no-buildable-input', 'ec': ec}
    atomic_json(folder / 'BUILD.json', record)
    print(f'BUILD written {len(outputs)} outputs, {len(not_built)} not built, to {folder}')


def main(argv=None, run=default_run, loader=default_loader):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('region_id')
    parser.add_argument('--run', required=True)
    parser.add_argument('--author-runtime', required=True)
    parser.add_argument('--author-family', required=True)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args(argv)
    try:
        build(args, run, loader)
    except (BuildError, ValueError, KeyError, OSError) as err:
        print(f'region_build: {err}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
