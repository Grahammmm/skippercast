#!/usr/bin/env python3
"""Region intake: bindings + catalog + private file list + existing screens -> INTAKE.csv/.md.
Stdlib only. Never downloads, re-screens, reads a raster or opens a restricted/unresolved-licence file."""
import argparse, contextlib, csv, hashlib, io, json, math, os, re, sys, tempfile
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
        bad = set(entry) - {'source_id', 'path', 'bbox', 'crs', 'screened_path'}
        listed = screened(entry)
        if bad or not {'source_id', 'path'} <= set(entry) or not os.path.isabs(entry['path']) or ('screened_path' in entry and not (
                isinstance(listed, list) and listed and all(isinstance(p, str) and os.path.isabs(p) for p in listed) and len(set(listed)) == len(listed))):
            raise IntakeError(f'Locations entry invalid ({sorted(bad) or entry.get("path")}): keys source_id, path, bbox, crs, screened_path; absolute path')
        box = entry.get('bbox')  # null/absent = not known; else four finite numbers, south <= north (west > east allowed)
        if box is not None and not (isinstance(box, list) and len(box) == 4 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box) and box[1] <= box[3]):
            raise IntakeError(f'Locations entry bbox invalid ({entry.get("path")}): need [west, south, east, north] finite numbers')
    return data['files']

def screened(entry):
    """The derived tile path(s) a verdict is keyed by: lookup keys only, never opened, stat-ed or hashed."""
    value = entry.get('screened_path')
    return [value] if isinstance(value, str) else value

def names(stem):
    return re.compile(f'(^|_){re.escape(stem)}(_|\\.)')

def read_screens(path, skip_raw):
    """Resolved tif -> (verdict, source); last row wins; never-read paths are not resolved.
    Also every FLAG row (tif, source) in TSV order, for the screened_path sibling-FLAG guard."""
    if not Path(path).is_file():
        raise IntakeError(f'Screens file not found: {path}')
    with open(path, newline='') as handle:
        table = [r for r in csv.DictReader(handle, delimiter='\t') if r['tif'] not in skip_raw]
    return ({os.path.realpath(r['tif']): (r['verdict'], r['source']) for r in table},
            [(r['tif'], r['source']) for r in table if r['verdict'] == 'FLAG'])

def joined(stem, listed, screens, flags):
    """screened_path join (M5a), top wins: any FLAG (listed or unlisted sibling) > any listed path absent > PASS-SPARSE > PASS."""
    keys = [os.path.realpath(p) for p in listed]
    hits = [screens.get(k) for k in keys]
    flags = [(os.path.realpath(t), s) for t, s in flags]  # every FLAG row, so a later PASS cannot hide a stale FLAG
    flagged = [s for k in keys for t, s in flags if t == k] + [
        s for t, s in flags if t not in keys and names(stem).search(os.path.basename(t))]
    if flagged:
        return 'FLAG', ';'.join(dict.fromkeys(flagged))
    if None in hits:
        return 'UNSCREENED', ''
    return 'PASS-SPARSE' if any(h[0] == 'PASS-SPARSE' for h in hits) else 'PASS', ';'.join(dict.fromkeys(h[1] for h in hits))

def build(region, sources, locations, screens, flags=()):
    rows, outside, joins = [], 0, 0
    for sid in region['source_bindings']['bathymetry']:
        if sid not in sources:
            raise IntakeError(f"Unknown source {sid} bound to {region['id']}")
    for sid in region['source_bindings']['bathymetry']:
        src, rights = sources[sid], sources[sid].get('rights') or {}
        base = dict.fromkeys(COLUMNS, '')
        base.update(source_id=sid, review_status=src.get('review_status', ''), licence=rights.get('license', ''),
                    commercial_use=rights.get('commercial_use', ''), crs='undeclared', screen='UNSCREENED',
                    native_cell_m='undeclared' if src.get('native_resolution_m') is None else src['native_resolution_m'], official_url=src.get('documentation_url', ''),
                    vertical_datum=src.get('vertical_datum') or 'undeclared')
        if never_read(src):
            rows.append({**base, 'use': 'skip', 'held_reason': 'none'})
            continue
        entries = [e for e in locations if e['source_id'] == sid]
        found, missing = [], not entries
        for e in entries:
            w, s, ee, n = region['bounds']
            if e.get('bbox') and (e['bbox'][2] < w or ee < e['bbox'][0] or e['bbox'][3] < s or n < e['bbox'][1]):
                outside += 1
                continue
            stem = Path(os.path.realpath(e['path'])).stem
            for p in screened(e) or []:
                if not names(stem).search(os.path.basename(p)):
                    raise IntakeError(f'screened_path {p} does not name {stem}')
            try:
                sha, size = file_identity(e['path'])
            except FileNotFoundError:
                missing = True
                continue
            except OSError as err:
                raise IntakeError(f"Cannot read {e['path']}: {err}") from err
            if size == 0:
                raise IntakeError(f"Empty data file: {e['path']}")
            path = os.path.realpath(e['path'])
            verdict, receipt = screens.get(path, ('UNSCREENED', '')) if not screened(e) else joined(stem, screened(e), screens, flags)
            joins += bool(screened(e))
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
        if missing:
            rows.append({**base, 'use': 'missing-file', 'held_reason': f'missing-file:{sid}'})
    return rows, outside, joins

def summary(region, rows, outside, sources, joins=None):
    def key(r):
        if r['use'] == 'skip':
            return 'never-read' if never_read(sources[r['source_id']]) else 'flag'
        return r['held_reason'].split(':')[0]
    gaps = list(dict.fromkeys((r['source_id'], key(r)) for r in rows if r['use'] != 'publish'))
    lines = [f"# INTAKE {region['id']}", '', 'Machine-valid output is review-required, not acceptance.', '',
             f"Region status: {region['status']}", '', 'Rows per use:']
    lines += [f"- {u}: {sum(r['use'] == u for r in rows)}" for u in USES]
    lines += [f'- out-of-bounds entries not listed: {outside}'] + ([] if joins is None else [f'- screens joined via screened_path: {joins} entries'])
    return '\n'.join(lines + ['', '## Gaps and next action', ''] +
                     [f'- {sid}: {GAPS[k]}' for sid, k in gaps]) + '\n'

def write_pair(run, texts):
    temps, placed = [], []  # both files or neither: UTF-8 temps in run, os.replace in order; a failure removes what was placed
    try:
        for text in texts.values():
            fd, tmp = tempfile.mkstemp(dir=run, prefix='.INTAKE.', suffix='.tmp')
            temps.append(tmp)
            with open(fd, 'w', encoding='utf-8', newline='') as handle:
                handle.write(text)
        for name, tmp in zip(texts, temps):
            os.replace(tmp, run / name)
            placed.append(run / name)
    except BaseException:
        for path in temps + placed:
            with contextlib.suppress(OSError):
                os.unlink(path)
        raise

def intake(args, loader):
    region, sources = loader(args.region_id)
    if os.path.islink(given := os.path.normpath(args.run)) or (os.path.lexists(given) and not os.path.isdir(given)):
        raise IntakeError('--run must be a real folder')  # the given path, before realpath
    run, repo = Path(os.path.realpath(args.run)), Path(os.path.realpath(REPO))
    if run == repo or repo in run.parents:
        raise IntakeError(f'--run must be outside the repository: {run}')
    if found := [n for n in ('INTAKE.csv', 'INTAKE.md') if os.path.lexists(run / n)]:  # also a dangling link or half pair
        raise IntakeError(f'Refusing to overwrite {found[0]} in {run}')
    locations = read_locations(args.locations)
    skip_raw = {p for e in locations if e['source_id'] in sources and never_read(sources[e['source_id']]) for p in [e['path']] + (screened(e) or [])}
    rows, outside, joins = build(region, sources, locations, *read_screens(os.path.expanduser(args.screens), skip_raw))
    writer = csv.DictWriter(table := io.StringIO(), COLUMNS, lineterminator='\n')  # render both in memory first
    writer.writeheader()
    writer.writerows(rows)
    texts = {'INTAKE.csv': table.getvalue(), 'INTAKE.md': summary(region, rows, outside, sources, joins if any(screened(e) for e in locations) else None)}
    run.mkdir(parents=True, exist_ok=True)
    write_pair(run, texts)
    print(f'INTAKE written {len(rows)} rows to {run}')

def check(folder, loader):
    try:
        title = (Path(folder) / 'INTAKE.md').read_text(encoding='utf-8').splitlines()[0]
        table = list(csv.reader(open(Path(folder) / 'INTAKE.csv', newline='', encoding='utf-8')))
    except (OSError, IndexError, UnicodeDecodeError) as err:
        raise IntakeError(f'Run folder unreadable: {err}')
    sources = loader(title.removeprefix('# INTAKE '))[1]
    if not table or table[0] != COLUMNS:
        raise IntakeError('Row 0: header differs')
    for number, values in enumerate(table[1:], 1):
        row = dict(zip(COLUMNS, values))
        src = sources.get(row['source_id'], {})
        data_row = row['use'] in ('publish', 'held')
        problems = [  # lazy, in order: a never-read source is rejected before any path is touched
            ('field count', lambda: len(values) != len(COLUMNS)),
            ('source_id', lambda: not src),
            ('use', lambda: row['use'] not in USES),
            ('review_status/licence', lambda: row['review_status'] != src.get('review_status') or row['licence'] != (src.get('rights') or {}).get('license', '')),
            ('use', lambda: data_row and never_read(src)),
            ('local_path/sha256', lambda: row['use'] == 'skip' and never_read(src) and bool(row['local_path'] or row['sha256'])),
            ('sha256', lambda: data_row and not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])),
            ('bytes', lambda: data_row and not row['bytes'].isdigit()),
            ('local_path', lambda: data_row and not (os.path.isfile(row['local_path']) and os.path.getsize(row['local_path']) == int(row['bytes']) > 0)),
            ('use', lambda: row['use'] == 'publish' and row['review_status'] != 'approved'),
            ('held_reason', lambda: row['held_reason'] not in ('none', 'region-draft', f"source-candidate:{row['source_id']}", f"missing-file:{row['source_id']}")),
        ]
        for field, bad in problems:
            if bad():
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
