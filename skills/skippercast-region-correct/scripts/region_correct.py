#!/usr/bin/env python3
"""Region correct (EC stage): checked INTAKE.csv -> ec_detect -> ec_apply -> ec_verify per GeoTIFF row, at most three rows
per invocation and resumable, then EC.json, EC.md and INTAKE-EC.csv in the private run folder. Stdlib only; the EC tools
run as subprocesses of --python via an injectable runner. Never edits a grid, receipt or INTAKE.csv, never writes in the
repository, never downloads, never converts a datum. Machine-valid output (`EC OK`) is review-required, not acceptance."""
import argparse, csv, hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
from skippercast.platform.contracts import load_catalogs, load_region  # noqa: E402
from skippercast.platform.seafloor_ec import EC_VERSION, check_receipt  # noqa: E402

INTAKE = REPO / 'skills/skippercast-region-intake/scripts/region_intake.py'
TOOLS = {name: REPO / f'scripts/{name}.py' for name in ('ec_detect', 'ec_apply', 'ec_verify')}
RECEIPTS = {'EC-DETECT.json': 'ec-detect-v1', 'EC-APPLY.json': 'ec-apply-v1', 'verify/EC-VERIFY.json': 'ec-verify-v1'}
NEEDED = ('unresolved-hole', 'unresolved-conflict', 'unresolved-ring-range', 'measured-suspect-shoal')  # 40 41 42 11
EXTRA = ['ec_status', 'ec_path', 'provenance_path']

class CorrectError(Exception): pass
def default_run(cmd): return subprocess.run(cmd, capture_output=True, text=True)  # an EC tool exits non-zero: EC STOP
def default_loader(region_id): return load_region(region_id), load_catalogs()[1]
def canonical(value): return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
def files(base): return sorted(p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()) if base.is_dir() else []

def sha256(path):
    with open(path, 'rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()

def call(run, cmd, sid, tool):
    done = run([str(c) for c in cmd])
    if done.returncode != 0:
        tail = ' | '.join((done.stderr or '').strip().splitlines()[-3:])
        raise CorrectError(f'EC STOP {sid} {tool} exit {done.returncode}: {tail}')

def read_receipt(base, rel, sid, stop=''):
    """The checked receipt ec/<sid>/<rel>; a problem names the file (prefixed `EC STOP <id> <tool>` during a run)."""
    try:
        doc = json.loads((base / rel).read_text(encoding='utf-8'))
    except (OSError, ValueError) as err:
        raise CorrectError(f'{stop}ec/{sid}/{rel}: unreadable: {err}')
    problems = check_receipt(RECEIPTS[rel], doc) or ([] if doc['source_id'] == sid else ['source_id differs'])
    if problems:
        raise CorrectError(f'{stop}ec/{sid}/{rel}: {problems[0]}')
    return doc

def write_done(base):
    (base / 'DONE').write_bytes(canonical([[rel, sha256(base / rel)] for rel in files(base) if rel != 'DONE']))

def done_problem(base):
    """None when DONE lists files that all still hash the same, else the first problem, naming the file."""
    where = f'ec/{base.name}'
    try:
        pairs = json.loads((base / 'DONE').read_text())
    except (OSError, ValueError):
        return f'{where}/DONE: missing or unreadable'
    if not (isinstance(pairs, list) and pairs and all(isinstance(p, list) and len(p) == 2 and all(
            isinstance(x, str) for x in p) and not os.path.isabs(p[0]) and '..' not in Path(p[0]).parts for p in pairs)):
        return f'{where}/DONE: malformed'
    return next((f'{where}/{rel}: sha256 differs from DONE' for rel, digest in pairs
                 if not (base / rel).is_file() or sha256(base / rel) != digest), None)

def select(rows, sources):
    """(candidates, not_corrected) in INTAKE order: single-file geotiff rows with use publish or held."""
    not_corrected, usable = [], {}
    for row in rows:
        sid, adapter = row['source_id'], sources.get(row['source_id'], {}).get('adapter') or 'none'
        if row['use'] not in ('publish', 'held'):
            not_corrected.append({'source_id': sid, 'reason': f"use:{row['use']}"})
        elif adapter != 'geotiff':
            not_corrected.append({'source_id': sid, 'reason': f'unsupported-adapter:{adapter}'})
        else:
            usable.setdefault(sid, []).append(row)
    not_corrected += [{'source_id': s, 'reason': f'multi-file-source:{s}:{len(f)}'} for s, f in usable.items() if len(f) > 1]
    return [f[0] for f in usable.values() if len(f) == 1], not_corrected

def overlaps(a, b):
    """True unless both rows carry an INTAKE bbox (JSON [w, s, e, n]) and the boxes are disjoint."""
    p, q = (json.loads(r['bbox']) if (r.get('bbox') or '').strip() else None for r in (a, b))
    return p is None or q is None or not (p[2] < q[0] or q[2] < p[0] or p[3] < q[1] or q[3] < p[1])
def refusal(detect):
    sign = detect['sign']
    return f"sign-{sign['reason']}" if sign['refused'] else 'fixture-' + '+'.join(detect['fixture']['reasons'])
def words(counts):
    c = lambda *names: sum(counts.get(n, 0) for n in names)  # noqa: E731  unresolved = hole + ring-range + datum-suspect
    return (f"filled={c('filled-hole')} pit={c('filled-pit')} verified={c('verified')} conflict={c('unresolved-conflict')} "
            f"unresolved={c('unresolved-hole', 'unresolved-ring-range', 'unresolved-datum-suspect')}")

def managed_paths(folder):
    """Refuse linked managed paths before any cleanup or write, including dangling links."""
    for name in ('ec', 'EC.json', 'EC.json.tmp', 'EC.md', 'INTAKE-EC.csv'):
        root = folder / name
        for path in [root, *root.rglob('*')] if root.is_dir() and not root.is_symlink() else [root]:
            if path.is_symlink() or not path.resolve().is_relative_to(folder):
                raise CorrectError(f'{path}: managed path must be an unlinked descendant of run')


def input_identity(row, receipt=None, field=None):
    if sha256(row['local_path']) != row['sha256'] or (receipt is not None and receipt[field] != row['sha256']):
        raise CorrectError(f"{row['source_id']}: input/receipt sha256 differs from INTAKE.csv")


def completed_identity(folder, row):
    base, sid = folder / 'ec' / row['source_id'], row['source_id']
    detect = read_receipt(base, 'EC-DETECT.json', sid)
    input_identity(row, detect, 'path_sha256')
    if detect['disposition'] != 'REFUSED':
        input_identity(row, read_receipt(base, 'EC-APPLY.json', sid), 'input_sha256')


def treat(args, run, folder, row, others, sources):
    """detect -> apply -> verify for one row in a fresh ec/<id>/; DONE only after every step succeeded."""
    sid, path, py, base = row['source_id'], row['local_path'], args.python, folder / 'ec' / row['source_id']
    if base.exists():
        shutil.rmtree(base)  # an untreated partial row is redone from scratch; nothing else is ever deleted
    base.mkdir(parents=True)
    call(run, [py, TOOLS['ec_detect'], path, '--source-id', sid, '--receipt', base / 'EC-DETECT.json'], sid, 'ec_detect')
    detect = read_receipt(base, 'EC-DETECT.json', sid, f'EC STOP {sid} ec_detect ')
    input_identity(row, detect, 'path_sha256')
    if detect['disposition'] == 'REFUSED':
        write_done(base)
        return print(f'EC {sid} REFUSED {refusal(detect)}')
    call(run, [py, TOOLS['ec_apply'], path, '--detect', base / 'EC-DETECT.json', '--out-dir', base], sid, 'ec_apply')
    input_identity(row, read_receipt(base, 'EC-APPLY.json', sid, f'EC STOP {sid} ec_apply '), 'input_sha256')
    (base / 'ENTRIES.json').write_bytes(canonical({r['source_id']: sources[r['source_id']] for r in [row] + others}))
    cmd = [py, TOOLS['ec_verify'], '--a', base, '--a-source', sid, '--a-datum', row['vertical_datum']]
    for other in (o for o in others if overlaps(row, o)):
        cmd += ['--b', other['local_path'], '--b-source', other['source_id'], '--b-datum', other['vertical_datum']]
    call(run, cmd + ['--catalog-entries', base / 'ENTRIES.json', '--out-dir', base / 'verify'], sid, 'ec_verify')
    verify = read_receipt(base, 'verify/EC-VERIFY.json', sid, f'EC STOP {sid} ec_verify ')
    for candidate in [row] + others:
        input_identity(candidate)
    write_done(base)
    print(f"EC {sid} {verify['disposition']} {words(verify['counts'])}")

def source_record(folder, sid):
    """(EC.json source entry, operator asks) from the row's receipts."""
    base, receipts = folder / 'ec' / sid, {'detect': f'ec/{sid}/EC-DETECT.json'}
    detect = read_receipt(base, 'EC-DETECT.json', sid)
    if detect['disposition'] == 'REFUSED':
        return ({'source_id': sid, 'status': 'REFUSED', 'reason': refusal(detect), 'counts': detect['counts'],
                 'second_surveys': [], 'second_survey_needed_cells': 0, 'receipts': receipts}, [f'refused:{sid}:{refusal(detect)}'])
    verify = read_receipt(base, 'verify/EC-VERIFY.json', sid)
    pairs, needed = verify['pairs'], sum(verify['counts'].get(name, 0) for name in NEEDED)
    asks = [f'second-survey:{sid}:{needed}'] if needed and not any(p['independent'] and p['comparable'] for p in pairs) else []
    asks += [f"datum-suspect:{sid}:{p['second_source_id']}:{p['mean_signed_diff_m']}" for p in pairs if p['datum_suspect']]
    receipts.update(apply=f'ec/{sid}/EC-APPLY.json', verify=f'ec/{sid}/verify/EC-VERIFY.json')
    return ({'source_id': sid, 'status': verify['disposition'], 'counts': verify['counts'], 'second_survey_needed_cells': needed,
             'second_surveys': [{k: p[k] for k in ('second_source_id', 'independent', 'reason', 'comparable')} for p in pairs],
             'receipts': receipts}, asks)

def handoff(row, entry):
    extra = {'ec_status': 'not_corrected', 'ec_path': row['local_path'], 'provenance_path': ''}
    if entry and entry['status'] == 'REFUSED':
        extra.update(ec_status='REFUSED', use='skip', held_reason=f"ec-refused:{entry['reason']}")
    elif entry:
        sid = row['source_id']
        extra.update(ec_status=entry['status'], ec_path=f'ec/{sid}/corrected.tif', provenance_path=f'ec/{sid}/verify/provenance.tif')
    return {**row, **extra}


def finish(args, folder, header, rows, candidates, not_corrected, region):
    managed_paths(folder)
    for row in candidates:
        completed_identity(folder, row)
    done = [source_record(folder, row['source_id']) for row in candidates]
    entries, asks = [e for e, _ in done], [a for _, more in done for a in more]
    outputs = [{'path': f'ec/{rel}', 'sha256': sha256(folder / 'ec' / rel)} for rel in files(folder / 'ec')]
    record = {'schema': 'region-correct-v1', 'ec_version': EC_VERSION, 'region_id': region['id'],
              'run': {'author_runtime': args.author_runtime, 'author_family': args.author_family},
              'sources': entries, 'not_corrected': not_corrected, 'operator_asks': asks,
              'inputs': [{'source_id': r['source_id'], 'sha256': r['sha256']} for r in candidates],
              'outputs': outputs, 'ec_sha256': hashlib.sha256(canonical(outputs)).hexdigest()}
    if check_receipt('region-correct-v1', record):
        raise CorrectError(f"EC.json invalid: {check_receipt('region-correct-v1', record)[0]}")
    by_row = {id(r): e for r, e in zip(candidates, entries)}
    with open(folder / 'INTAKE-EC.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, header + EXTRA, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow(handoff(row, by_row.get(id(row))))
    lines = [f"# EC {region['id']}", '', 'Machine-valid output is review-required, not acceptance.', '', '## Sources', '']
    lines += [f"- {e['source_id']}: {e['status']} {e.get('reason') or words(e['counts'])}" for e in entries]
    lines += [f"- {n['source_id']}: not_corrected {n['reason']}" for n in not_corrected]
    lines += ['', '## Operator asks', ''] + ([f'- {a}' for a in asks] or ['- none'])
    (folder / 'EC.md').write_text('\n'.join(lines) + '\n')
    (folder / 'EC.json.tmp').write_bytes(canonical(record))
    (folder / 'EC.json.tmp').replace(folder / 'EC.json')  # last, so an interrupted finish is simply re-run
    print(f'EC ALL-DONE {len(entries)} rows')

def correct(args, run, loader):
    folder, repo = Path(os.path.realpath(args.run)), Path(os.path.realpath(REPO))
    if folder == repo or repo in folder.parents:
        raise CorrectError(f'--run must be outside the repository: {folder}')
    if not (folder / 'INTAKE.csv').is_file() or (folder / 'EC.json').exists():
        raise CorrectError(f'Need INTAKE.csv and no EC.json (never overwritten) in {folder}')
    if not (args.author_runtime or '').strip() or not re.fullmatch(r'[a-z][a-z0-9-]*', args.author_family or ''):
        raise CorrectError('--author-runtime must be non-empty and --author-family must match ^[a-z][a-z0-9-]*$')
    managed_paths(folder)
    call(run, [args.python, INTAKE, '--check', folder], '-', 'region_intake')
    with open(folder / 'INTAKE.csv', newline='') as handle:
        reader = csv.DictReader(handle)
        rows, header = list(reader), list(reader.fieldnames or [])
    region, sources = loader(args.region_id)
    candidates, not_corrected = select(rows, sources)
    for row in candidates:
        input_identity(row)
        if not done_problem(folder / 'ec' / row['source_id']):
            completed_identity(folder, row)
    batch, todo = max(1, min(3, args.batch)), [r for r in candidates if done_problem(folder / 'ec' / r['source_id'])]
    for row in todo[:batch]:
        treat(args, run, folder, row, [r for r in candidates if r is not row], sources)
    if todo[batch:]:
        return print(f'EC BATCH-DONE {len(candidates) - len(todo[batch:])}/{len(candidates)}')
    finish(args, folder, header, rows, candidates, not_corrected, region)

def check(args, run, loader):
    """Validate a finished run folder; writes nothing."""
    folder = Path(os.path.realpath(args.check))
    managed_paths(folder)
    call(run, [args.python, INTAKE, '--check', folder], '-', 'region_intake')
    try:
        record = json.loads((folder / 'EC.json').read_text())
    except (OSError, ValueError):
        raise CorrectError('EC.json: missing or unreadable')
    if check_receipt('region-correct-v1', record):
        raise CorrectError(f"EC.json: {check_receipt('region-correct-v1', record)[0]}")
    ec = folder / 'ec'
    for base in sorted(p for p in ec.iterdir() if p.is_dir()) if ec.is_dir() else []:
        problem = done_problem(base)
        if problem:
            raise CorrectError(problem)
        for rel in (r for r in RECEIPTS if (base / r).is_file()):
            read_receipt(base, rel, base.name)
    listed, present = {o['path']: o['sha256'] for o in record['outputs']}, {f'ec/{r}': sha256(ec / r) for r in files(ec)}
    for path in (p for p in sorted(set(listed) | set(present)) if listed.get(p) != present.get(p)):
        raise CorrectError(f'{path}: not as listed in EC.json outputs')
    if hashlib.sha256(canonical(record['outputs'])).hexdigest() != record['ec_sha256']:
        raise CorrectError('EC.json: ec_sha256 differs')
    with open(folder / 'INTAKE.csv', newline='') as a, open(folder / 'INTAKE-EC.csv', newline='') as b:
        old_reader, new_reader = csv.DictReader(a), csv.DictReader(b)
        old_rows, new_rows = list(old_reader), list(new_reader)
    if new_reader.fieldnames != list(old_reader.fieldnames or []) + EXTRA or len(old_rows) != len(new_rows):
        raise CorrectError('INTAKE-EC.csv: header or row count differs from INTAKE.csv')
    region, sources = loader(record['region_id'])
    candidates, not_corrected = select(old_rows, sources)
    for row in candidates:
        completed_identity(folder, row)
    expected = [source_record(folder, r['source_id']) for r in candidates]
    entries, asks = [e for e, _ in expected], [a for _, more in expected for a in more]
    inputs = [{'source_id': r['source_id'], 'sha256': r['sha256']} for r in candidates]
    if (record['sources'] != entries or record['inputs'] != inputs or record['not_corrected'] != not_corrected
            or record['operator_asks'] != asks or region['id'] != record['region_id']):
        raise CorrectError('EC.json: source/input coverage or receipt summary differs')
    if ({p.name for p in ec.iterdir()} if ec.is_dir() else set()) != {r['source_id'] for r in candidates}:
        raise CorrectError('EC.json: receipt directories differ from candidate coverage')
    by_row = {id(r): e for r, e in zip(candidates, entries)}
    for number, (old, new) in enumerate(zip(old_rows, new_rows), 1):
        if new != handoff(old, by_row.get(id(old))):
            raise CorrectError(f'INTAKE-EC.csv: row {number} differs from receipts or INTAKE.csv')
    print(f"EC OK {len(record['sources'])} rows")

def main(argv=None, run=default_run, loader=default_loader):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('region_id', '--run', '--author-runtime', '--author-family', '--check'):
        parser.add_argument(flag, **({'nargs': '?'} if flag == 'region_id' else {}))
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--batch', type=int, default=3, help='rows treated per invocation, clamped to 1-3')
    args = parser.parse_args(argv)
    try:
        if not args.check and not (args.region_id and args.run):
            raise CorrectError('need <region_id> --run <dir> --author-runtime <id> --author-family <f>, or --check <dir>')
        check(args, run, loader) if args.check else correct(args, run, loader)
    except (CorrectError, ValueError, KeyError, TypeError, OSError) as err:
        print(err if str(err).startswith('EC STOP') else f'region_correct: {err}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
