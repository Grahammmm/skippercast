#!/usr/bin/env python3
"""Region intake: bindings + catalog + private file list + existing screens -> INTAKE.csv/.md.
Stdlib only. Never downloads, re-screens, reads a raster or opens a restricted/unresolved-licence file."""
import argparse, csv, hashlib, json, os, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
COLUMNS = ['source_id', 'review_status', 'licence', 'commercial_use', 'local_path', 'sha256', 'bytes', 'crs',
           'native_cell_m', 'vertical_datum', 'screen', 'screen_receipt', 'use', 'held_reason', 'official_url']
USES = ['publish', 'held', 'skip', 'missing-file']
GAPS = {'missing-file': 'operator: one G ask with host + URL (`allowed_hosts`)',
        'source-candidate': 'held until the source review (noaa-bag: M4b)',
        'region-draft': 'held until PC-4b (t_6dd54ee3) promotes the region',
        'flag': 'skip; second looks belong to the screening owner', 'never-read': 'never read'}

class IntakeError(Exception):
    pass

def file_identity(path):
    """The only function that touches a data file: (sha256, bytes), 1 MiB chunks."""
    digest, size = hashlib.sha256(), 0
    with open(path, 'rb') as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size

def default_loader(region_id):
    sys.path.insert(0, str(REPO / 'src'))
    from skippercast.platform import contracts
    return contracts.load_region(region_id, REPO), contracts.load_catalogs(REPO)[1]

def never_read(src):
    licence = (src.get('rights') or {}).get('license')
    return src.get('review_status') not in ('approved', 'candidate') or licence in (None, '', 'unresolved', 'dataset-review-needed')

def read_locations(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or set(data) != {'schema_version', 'files'} or data['schema_version'] != 1:
        raise IntakeError('Locations file needs exactly schema_version 1 and files')
    for entry in data['files']:
        bad = set(entry) - {'source_id', 'path', 'bbox', 'crs'}
        if bad or not {'source_id', 'path'} <= set(entry) or not os.path.isabs(entry['path']):
            raise IntakeError(f'Locations entry invalid ({sorted(bad) or entry.get("path")}): keys source_id, path, bbox, crs; absolute path')
    return data['files']

def read_screens(path, skip_raw):
    """Resolved tif -> (verdict, source); last row wins; never-read paths are not resolved."""
    if not Path(path).is_file():
        raise IntakeError(f'Screens file not found: {path}')
    with open(path, newline='') as handle:
        return {os.path.realpath(r['tif']): (r['verdict'], r['source'])
                for r in csv.DictReader(handle, delimiter='\t') if r['tif'] not in skip_raw}

def build(region, sources, locations, screens):
    rows, outside = [], 0
    for sid in region['source_bindings']['bathymetry']:
        if sid not in sources:
            raise IntakeError(f"Unknown source {sid} bound to {region['id']}")
    for sid in region['source_bindings']['bathymetry']:
        src, rights = sources[sid], sources[sid].get('rights') or {}
        base = dict.fromkeys(COLUMNS, '')
        base.update(source_id=sid, review_status=src.get('review_status', ''), licence=rights.get('license', ''),
                    commercial_use=rights.get('commercial_use', ''), crs='undeclared', screen='UNSCREENED',
                    native_cell_m=src.get('native_resolution_m', 'undeclared'), official_url=src.get('documentation_url', ''),
                    vertical_datum=src.get('vertical_datum') or 'undeclared')
        if never_read(src):
            rows.append({**base, 'use': 'skip', 'held_reason': 'none'})
            continue
        found, missing = [], False
        for e in (e for e in locations if e['source_id'] == sid):
            w, s, ee, n = region['bounds']
            if e.get('bbox') and (e['bbox'][2] < w or ee < e['bbox'][0] or e['bbox'][3] < s or n < e['bbox'][1]):
                outside += 1
                continue
            try:
                sha, size = file_identity(e['path'])
            except OSError:
                sha, size = '', 0
            if size == 0:
                missing = True
                continue
            path = os.path.realpath(e['path'])
            verdict, receipt = screens.get(path, ('UNSCREENED', ''))
            row = {**base, 'local_path': path, 'sha256': sha, 'bytes': size, 'crs': e.get('crs') or 'undeclared',
                   'screen': verdict, 'screen_receipt': receipt, 'use': 'publish', 'held_reason': 'none'}
            if verdict == 'FLAG':
                row['use'] = 'skip'
            elif src['review_status'] == 'candidate':
                row.update(use='held', held_reason=f'source-candidate:{sid}')
            elif region['status'] not in ('active', 'preview'):
                row.update(use='held', held_reason='region-draft')
            found.append(row)
        rows += sorted(found, key=lambda r: r['local_path'])
        if missing or not found:
            rows.append({**base, 'use': 'missing-file', 'held_reason': f'missing-file:{sid}'})
    return rows, outside

def summary(region, rows, outside, sources):
    def key(r):
        if r['use'] == 'skip':
            return 'never-read' if never_read(sources[r['source_id']]) else 'flag'
        return r['held_reason'].split(':')[0]
    gaps = list(dict.fromkeys((r['source_id'], key(r)) for r in rows if r['use'] != 'publish'))
    lines = [f"# INTAKE {region['id']}", '', 'Machine-valid output is review-required, not acceptance.', '',
             f"Region status: {region['status']}", '', 'Rows per use:']
    lines += [f"- {u}: {sum(r['use'] == u for r in rows)}" for u in USES]
    return '\n'.join(lines + [f'- out-of-bounds entries not listed: {outside}', '', '## Gaps and next action', ''] +
                     [f'- {sid}: {GAPS[k]}' for sid, k in gaps]) + '\n'

def intake(args, loader):
    region, sources = loader(args.region_id)
    run, repo = Path(os.path.realpath(args.run)), Path(os.path.realpath(REPO))
    if run == repo or repo in run.parents:
        raise IntakeError(f'--run must be outside the repository: {run}')
    if (run / 'INTAKE.csv').exists():
        raise IntakeError(f'Refusing to overwrite {run / "INTAKE.csv"}')
    locations = read_locations(args.locations)
    skip_raw = {e['path'] for e in locations if e['source_id'] in sources and never_read(sources[e['source_id']])}
    rows, outside = build(region, sources, locations, read_screens(os.path.expanduser(args.screens), skip_raw))
    run.mkdir(parents=True, exist_ok=True)
    with open(run / 'INTAKE.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    (run / 'INTAKE.md').write_text(summary(region, rows, outside, sources))
    print(f'INTAKE written {len(rows)} rows to {run}')

def check(folder, loader):
    try:
        title = (Path(folder) / 'INTAKE.md').read_text().splitlines()[0]
        table = list(csv.reader(open(Path(folder) / 'INTAKE.csv', newline='')))
    except (OSError, IndexError) as err:
        raise IntakeError(f'Run folder unreadable: {err}')
    sources = loader(title.removeprefix('# INTAKE '))[1]
    if not table or table[0] != COLUMNS:
        raise IntakeError('Row 0: header differs')
    for number, values in enumerate(table[1:], 1):
        row = dict(zip(COLUMNS, values))
        src = sources.get(row['source_id'], {})
        problems = [
            ('field count', len(values) != len(COLUMNS)),
            ('source_id', not src),
            ('use', row['use'] not in USES),
            ('review_status/licence', row['review_status'] != src.get('review_status') or row['licence'] != (src.get('rights') or {}).get('license', '')),
            ('sha256', row['use'] in ('publish', 'held') and not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])),
            ('bytes', row['use'] in ('publish', 'held') and not row['bytes'].isdigit()),
            ('local_path', row['use'] in ('publish', 'held') and not (row['bytes'].isdigit() and os.path.isfile(row['local_path'])
                                                                      and os.path.getsize(row['local_path']) == int(row['bytes']) > 0)),
            ('use', row['use'] == 'publish' and row['review_status'] != 'approved'),
            ('local_path/sha256', row['use'] == 'skip' and never_read(src) and bool(row['local_path'] or row['sha256'])),
            ('held_reason', not re.fullmatch(r'none|region-draft|source-candidate:.+|missing-file:.+', row['held_reason'])),
        ]
        for field, bad in problems:
            if bad:
                raise IntakeError(f'Row {number} field {field}')
    print(f'INTAKE OK {len(table) - 1} rows')

def main(argv=None, loader=default_loader):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('region_id', nargs='?')
    parser.add_argument('--run')
    parser.add_argument('--locations')
    parser.add_argument('--screens', default='~/agent-work/reports/MAP-VERDICTS.tsv')
    parser.add_argument('--check', metavar='DIR')
    args = parser.parse_args(argv)
    try:
        if args.check:
            check(args.check, loader)
        elif args.region_id and args.run and args.locations:
            intake(args, loader)
        else:
            raise IntakeError('need <region_id> --run <dir> --locations <json>, or --check <dir>')
    except (IntakeError, ValueError, KeyError, OSError) as err:
        print(f'region_intake: {err}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
