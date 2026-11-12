#!/usr/bin/env python3
"""MGL-03: offline private-run seafloor parity harness (standard library only).

Runs the reviewed `run --reach ID` once per reach through the fixed launcher
inside a prepared disposable private checkout and writes one JSON Lines row per
reach comparing six ledger measurements with an immutable baseline copy of the
committed ledger. See README.md beside this file for the row schema and exit codes.
Private, review-required evidence only: never proof of legal clearance or publication.
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = 1
PRIVATE_PARENT = Path(os.path.expanduser('~/agent-work/reports/seafloor-agg/private-runs'))
LAUNCHER = os.path.expanduser('~/agent-work/bin/seafloor-cli.py')
ROW_IDS = ('MGL-06', 'MGL-07', 'MGL-08', 'MGL-09')
FIELDS = ('tier1_km2', 'selected_valid_km2', 'tier2_km2', 'polygons_by_grade', 'habitat_count', 'held_by_reason')
AREAS = ('tier1_km2', 'selected_valid_km2', 'tier2_km2')
RUN_TIMEOUT = 1800
WHICH_TIMEOUT = 120
LEDGER_REL = 'dist/data/seafloor-ledger.json'
CATALOG_REL = 'catalog/reaches.json'
RECEIPT_OUTPUTS = ('cells.json', 'terrain.json', 'habitat.geojson', 'atlas-comparison.json',
                   'held.geojson', 'candidates.geojson', 'physical.json')
MUTABLE_LINK_CHECKS = ('dist', 'dist/data', LEDGER_REL, 'catalog', CATALOG_REL, 'var', 'var/seafloor',
                       'var/seafloor/reaches', 'var/seafloor/private-reaches')
HEX40 = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
REACH_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


class Preflight(Exception):
    """Invalid preparation: one named diagnostic, no child run, no output."""


class Evidence(Exception):
    def __init__(self, code, detail):
        super().__init__(f'{code}: {detail}')
        self.code, self.detail = code, detail


# ---------------------------------------------------------------- validation
def _number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise Evidence('invalid-area', f'{where} must be a finite nonnegative number')
    return value


def _count(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or value < 0 or value != int(value):
        raise Evidence('invalid-count', f'{where} must be a nonnegative integer')
    return int(value)


def _count_map(value, where, required=()):
    if not isinstance(value, dict):
        raise Evidence('invalid-map', f'{where} must be an object')
    out = {}
    for key, count in value.items():
        if not isinstance(key, str) or not key:
            raise Evidence('invalid-map', f'{where} has a non-text or empty key')
        out[key] = _count(count, f'{where}.{key}')
    for key in required:
        if key not in out:
            raise Evidence('invalid-map', f'{where} is missing {key}')
    return dict(sorted(out.items()))


def six_fields(row, where):
    if not isinstance(row, dict):
        raise Evidence('invalid-row', f'{where} is not an object')
    for field in FIELDS:
        if field not in row or row[field] is None:
            raise Evidence('missing-field', f'{where} is missing {field}')
    values = {f: _number(row[f], f'{where}.{f}') for f in AREAS}
    values['polygons_by_grade'] = _count_map(row['polygons_by_grade'], f'{where}.polygons_by_grade', 'ABC')
    values['habitat_count'] = _count(row['habitat_count'], f'{where}.habitat_count')
    values['held_by_reason'] = _count_map(row['held_by_reason'], f'{where}.held_by_reason')
    return {f: values[f] for f in FIELDS}


def ledger_rows(data, where):
    """Return {reach id: raw row}; duplicate ids, wrong schema or shape are errors."""
    if not isinstance(data, dict) or data.get('schema_version') != SCHEMA_VERSION \
            or isinstance(data.get('schema_version'), bool):
        raise Evidence('unsupported-schema', f'{where} schema_version is not {SCHEMA_VERSION}')
    reaches = data.get('reaches')
    if not isinstance(reaches, list):
        raise Evidence('invalid-ledger', f'{where} reaches is not an array')
    rows = {}
    for index, row in enumerate(reaches):
        ident = row.get('id') if isinstance(row, dict) else None
        if not isinstance(ident, str) or not ident:
            raise Evidence('invalid-ledger', f'{where} reach {index} has no id')
        if ident in rows:
            raise Evidence('duplicate-id', f'{where} repeats reach {ident}')
        rows[ident] = row
    return rows


def compare(baseline, actual):
    """Named leaf differences between two validated six-field dicts; no rounding."""
    diffs = []
    for field in FIELDS:
        b, a = baseline[field], actual[field]
        if isinstance(b, dict):
            for key in sorted(set(b) | set(a)):
                if key in b and key in a and b[key] == a[key]:
                    continue
                diffs.append({'path': f'{field}.{key}', 'baseline_present': key in b, 'actual_present': key in a,
                              'baseline': b.get(key), 'actual': a.get(key)})
        elif b != a:
            diffs.append({'path': field, 'baseline_present': True, 'actual_present': True,
                          'baseline': b, 'actual': a})
    return diffs


# ------------------------------------------------------------------- helpers
def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise Evidence('unreadable-json', f'{path}: {type(error).__name__}') from None


def git(repo, *args, binary=False):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    done = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, env=env, shell=False, timeout=120)
    if done.returncode != 0:
        raise Evidence('git-failed', f'git {args[0]} failed in {repo}')
    return done.stdout if binary else done.stdout.decode('utf-8', 'replace')


def default_runner(argv, cwd, timeout):
    """Return (returncode, stdout, stderr); returncode None means timeout."""
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired as error:
        out = error.stdout.decode('utf-8', 'replace') if isinstance(error.stdout, bytes) else (error.stdout or '')
        err = error.stderr.decode('utf-8', 'replace') if isinstance(error.stderr, bytes) else (error.stderr or '')
        return None, out, err
    except OSError as error:
        return 127, '', f'{type(error).__name__}: {error}'
    return done.returncode, done.stdout, done.stderr


def run_argv(python, checkout, reach_id):
    return [str(python), '-B', LAUNCHER, '--checkout', str(checkout), 'run', '--reach', reach_id]


def which_argv(python, checkout):
    return [str(python), '-B', LAUNCHER, '--checkout', str(checkout), '--which']


# ----------------------------------------------------------------- preflight
class Plan:
    pass


def _inside(child, parent):
    return child == parent or parent in child.parents


def _confined(arg, root_abs, root_real, name):
    absolute = Path(os.path.abspath(arg))
    if not _inside(absolute, root_abs):
        raise Preflight(f'{name} is outside the private row root')
    real = Path(os.path.realpath(absolute))
    if real != root_real / absolute.relative_to(root_abs):
        raise Preflight(f'{name} resolves through a symlink')
    return real


def admit(args, parent):
    plan = Plan()
    # The fixed private parent is the only trust anchor. The row root must be a real directory directly
    # under it: a symlinked row root is never adopted as the confinement root.
    parent_abs = Path(os.path.abspath(parent))
    parent_real = Path(os.path.realpath(parent_abs))
    root_abs = parent_abs / args.row_id
    root_real = parent_real / args.row_id
    if os.path.islink(root_abs) or not root_abs.is_dir():
        raise Preflight(f'row root {root_abs} does not exist or is a symlink')
    if Path(os.path.realpath(root_abs)) != root_real:
        raise Preflight('row root does not resolve directly under the fixed private-runs parent')
    plan.row_id, plan.root = args.row_id, root_real
    plan.checkout = _confined(args.checkout, root_abs, root_real, '--checkout')
    plan.baseline_dir = _confined(args.baseline_dir, root_abs, root_real, '--baseline-dir')
    plan.reaches_file = _confined(args.reaches_file, root_abs, root_real, '--reaches-file')
    plan.output = _confined(args.output, root_abs, root_real, '--output')
    plan.python = Path(args.python)
    if not plan.checkout.is_dir() or not plan.baseline_dir.is_dir() or not plan.reaches_file.is_file():
        raise Preflight('checkout, baseline directory or reaches file is missing')
    if not (plan.python.is_file() and os.access(plan.python, os.X_OK)):
        raise Preflight('--python is not an executable file')
    if _inside(plan.checkout, plan.baseline_dir) or _inside(plan.baseline_dir, plan.checkout):
        raise Preflight('checkout and baseline directory are not disjoint')
    if plan.output.exists() or os.path.lexists(plan.output):
        raise Preflight('output already exists; refusing to overwrite or append')
    if not plan.output.parent.is_dir():
        raise Preflight('output parent directory does not exist')
    for protected, name in ((plan.checkout, 'checkout'), (plan.baseline_dir, 'baseline directory')):
        if _inside(plan.output, protected):
            raise Preflight(f'output is inside the {name}')
    if plan.output == plan.reaches_file:
        raise Preflight('output aliases the reaches file')
    source = Path(os.path.realpath(args.source_checkout))
    if not source.is_dir():
        raise Preflight('--source-checkout is not a directory')
    if _inside(source, root_real) or _inside(root_real, source) or source == plan.checkout:
        raise Preflight('source checkout must be outside the row root and distinct from the execution checkout')
    plan.source = source
    for rel in MUTABLE_LINK_CHECKS:
        if os.path.islink(plan.checkout / rel):
            raise Preflight(f'{rel} in the checkout is a symlink')
    if not (plan.checkout / LEDGER_REL).is_file() or not (plan.checkout / CATALOG_REL).is_file():
        raise Preflight('checkout lacks its derived ledger or catalog')
    # Requested reaches.
    try:
        requested = json.loads(plan.reaches_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise Preflight('reaches file is not readable JSON') from None
    if not isinstance(requested, list) or not requested:
        raise Preflight('reaches file must be a nonempty JSON array')
    for ident in requested:
        if not isinstance(ident, str) or not REACH_ID.match(ident):
            raise Preflight('reaches file entries must be nonempty safe reach IDs')
    if len(set(requested)) != len(requested):
        raise Preflight('reaches file repeats a reach ID')
    plan.reaches = list(requested)
    try:
        _admit_baseline(plan)
    except Evidence as error:
        raise Preflight(str(error)) from None
    plan.logs_dir = plan.root / 'logs'
    if os.path.islink(plan.logs_dir):
        raise Preflight('logs directory is a symlink')
    stem = plan.output.name
    plan.log_paths = {r: (plan.logs_dir / f'{stem}.{r}.stdout.log', plan.logs_dir / f'{stem}.{r}.stderr.log')
                      for r in plan.reaches}
    if any(os.path.lexists(p) for pair in plan.log_paths.values() for p in pair):
        raise Preflight('a log destination already exists; refusing to truncate old evidence')
    plan.execution = _execution_identity(plan)
    return plan


def _admit_baseline(plan):
    manifest_path = plan.baseline_dir / 'manifest.json'
    ledger_path, reaches_path = plan.baseline_dir / 'seafloor-ledger.json', plan.baseline_dir / 'reaches.json'
    for path in (manifest_path, ledger_path, reaches_path):
        if os.path.islink(path) or not path.is_file():
            raise Evidence('baseline-missing', f'{path.name} is missing or a symlink')
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != {'source_commit', 'ledger_sha256', 'reaches_sha256'}:
        raise Evidence('baseline-manifest', 'manifest must have exactly source_commit, ledger_sha256, reaches_sha256')
    if not (isinstance(manifest['source_commit'], str) and HEX40.match(manifest['source_commit'])):
        raise Evidence('baseline-manifest', 'source_commit is not a full lowercase commit hash')
    for key, path in (('ledger_sha256', ledger_path), ('reaches_sha256', reaches_path)):
        if not (isinstance(manifest[key], str) and HEX64.match(manifest[key])) or manifest[key] != sha256_file(path):
            raise Evidence('baseline-hash', f'{key} does not match the saved baseline bytes')
    for rel, path in ((LEDGER_REL, ledger_path), (CATALOG_REL, reaches_path)):
        committed = git(plan.source, 'show', f'{manifest["source_commit"]}:{rel}', binary=True)
        if committed != path.read_bytes():
            raise Evidence('baseline-not-committed', f'{path.name} differs from git show of source_commit')
    plan.manifest = manifest
    plan.baseline_hashes = {'manifest.json': sha256_file(manifest_path), 'seafloor-ledger.json': manifest['ledger_sha256'],
                            'reaches.json': manifest['reaches_sha256']}
    baseline_rows = ledger_rows(read_json(ledger_path), 'baseline ledger')
    catalog_rows = _catalog_rows(read_json(reaches_path), 'baseline catalog')
    private_rows = _catalog_rows(read_json(plan.checkout / CATALOG_REL), 'private catalog')
    plan.baseline_values = {}
    for ident in plan.reaches:
        if ident not in baseline_rows:
            raise Evidence('unknown-reach', f'{ident} is not in the baseline ledger')
        if ident not in private_rows or ident not in catalog_rows:
            raise Evidence('unknown-reach', f'{ident} is not in the baseline and private catalogs')
        if private_rows[ident] != catalog_rows[ident]:
            raise Evidence('catalog-mismatch', f'{ident} differs between baseline and private catalog')
        plan.baseline_values[ident] = six_fields(baseline_rows[ident], f'baseline {ident}')


def _catalog_rows(data, where):
    rows = data.get('reaches') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise Evidence('invalid-catalog', f'{where} reaches is not an array')
    out = {}
    for row in rows:
        ident = row.get('id') if isinstance(row, dict) else None
        if not isinstance(ident, str) or not ident or ident in out:
            raise Evidence('invalid-catalog', f'{where} has a missing or duplicate reach id')
        out[ident] = row
    return out


def _execution_identity(plan):
    if (plan.checkout / '.git').exists():
        try:
            head = git(plan.checkout, 'rev-parse', 'HEAD').strip()
        except Evidence as error:
            raise Preflight(str(error)) from None
        mode = 'git'
    else:
        note = plan.root / 'checkout-commit.txt'
        if not note.is_file() or os.path.islink(note):
            raise Preflight('archive checkout needs checkout-commit.txt in the row root')
        head, mode = note.read_text(encoding='utf-8').strip(), 'declared'
    if not HEX40.match(head):
        raise Preflight('execution checkout commit is not a full lowercase hash')
    return head, mode


def source_snapshot(plan):
    return git(plan.source, 'rev-parse', 'HEAD').strip(), git(plan.source, 'status', '--porcelain')


def integrity(plan, snapshot):
    """(baseline_unchanged, source_checkout_unchanged); never repairs anything."""
    try:
        base = all(os.path.isfile(plan.baseline_dir / n) and not os.path.islink(plan.baseline_dir / n)
                   and sha256_file(plan.baseline_dir / n) == h for n, h in plan.baseline_hashes.items())
    except OSError:
        base = False
    try:
        src = source_snapshot(plan) == snapshot
    except (Evidence, subprocess.SubprocessError, OSError):
        src = False
    return base, src


# ------------------------------------------------------------------- one run
def evaluate(plan, reach_id, stdout):
    """Validate completed-run evidence; returns (actual, unchanged, findings, private)."""
    try:
        summary = json.loads(stdout)
    except ValueError:
        raise Evidence('malformed-stdout', 'run stdout is not JSON') from None
    if not isinstance(summary, dict) or not isinstance(summary.get('unchanged'), bool):
        raise Evidence('malformed-stdout', 'run stdout lacks a boolean unchanged')
    stdout_values = six_fields(summary, 'stdout summary')
    folders = [plan.checkout / 'var/seafloor/reaches' / reach_id, plan.checkout / 'var/seafloor/private-reaches' / reach_id]
    present = [f for f in folders if (f / 'run.json').is_file()]
    if len(present) > 1:
        # Hash-verified reuse does not rewrite a receipt, so mtime cannot say which one this run used.
        raise Evidence('receipt-ambiguous', 'both a public and a private run receipt exist for the reach; '
                       'cannot tell which this run used (remove the stale one in the disposable checkout)')
    if not present:
        raise Evidence('receipt-missing', 'no run receipt for the reach')
    folder = present[0]
    receipt_path = folder / 'run.json'
    receipt = read_json(receipt_path)
    rsum = receipt.get('ledger_summary') if isinstance(receipt, dict) else None
    if not isinstance(rsum, dict):
        raise Evidence('receipt-invalid', 'receipt has no ledger_summary')
    if summary.get('processing_incomplete') is not False or rsum.get('processing_incomplete') is not False \
            or 'pending' in str(summary.get('status')) or 'pending' in str(rsum.get('status')):
        raise Evidence('processing-incomplete', 'run reports incomplete or pending processing')
    outputs = receipt.get('outputs')
    if not isinstance(outputs, dict) or set(outputs) != set(RECEIPT_OUTPUTS):
        raise Evidence('receipt-invalid', 'receipt outputs are not the reviewed output set')
    for name, digest in outputs.items():
        target = folder / name
        if not target.is_file() or sha256_file(target) != digest:
            raise Evidence('receipt-hash', f'{name} is missing or fails its receipt hash')
    receipt_values = six_fields(rsum, 'receipt ledger_summary')
    if receipt_values != stdout_values:
        raise Evidence('evidence-disagree', 'stdout summary and receipt ledger_summary differ')
    private = folder.parent.name == 'private-reaches' or receipt.get('publication_prohibited') is not False
    findings = []
    if private:
        findings.append({'code': 'private-source-only',
                         'detail': 'receipt is private or publication_prohibited; not a publishable ledger result'})
    else:
        row = ledger_rows(read_json(plan.checkout / LEDGER_REL), 'derived ledger').get(reach_id)
        if row is None or six_fields(row, 'derived ledger row') != receipt_values:
            raise Evidence('evidence-disagree', 'derived ledger row and receipt ledger_summary differ')
    screen = rsum.get('screen')
    screen = screen if isinstance(screen, dict) else {}
    reasons = screen.get('reasons')
    status = screen.get('status')
    actual = {'checkout_commit': plan.execution[0], 'commit_verification': plan.execution[1],
              'ledger_sha256': sha256_file(plan.checkout / LEDGER_REL), 'receipt_sha256': sha256_file(receipt_path),
              'values': receipt_values, 'processing_status': str(rsum.get('status')),
              'screen_status': status if isinstance(status, str) else None,
              'screen_reasons': [r for r in reasons if isinstance(r, str)] if isinstance(reasons, list) else [],
              'publication_prohibited': bool(private)}
    if actual['screen_status'] != 'ready':
        findings.append({'code': 'screen-not-ready', 'detail': f'screen status is {actual["screen_status"]!r}; '
                         'measurements are recorded but this is not an exact success'})
    return actual, summary['unchanged'], findings, private


def make_row(plan, reach_id, status, **extra):
    row = {'schema_version': SCHEMA_VERSION, 'row_id': plan.row_id, 'reach_id': reach_id, 'status': status,
           'baseline': {**plan.manifest, 'values': plan.baseline_values[reach_id]}, 'actual': None,
           'command': run_argv(plan.python, plan.checkout, reach_id), 'returncode': None, 'unchanged': None,
           'differences': [], 'findings': [], 'logs': None,
           'integrity': {'baseline_unchanged': True, 'source_checkout_unchanged': True}}
    row.update(extra)
    return row


def write_log(path, text):
    path.parent.mkdir(exist_ok=True)
    with open(path, 'x', encoding='utf-8') as handle:
        handle.write(text)


def drive(plan, runner):
    snapshot = source_snapshot(plan)
    code, out, err = runner(which_argv(plan.python, plan.checkout), str(plan.checkout), WHICH_TIMEOUT)
    if code != 0 or 'resolved inside checkout: yes' not in (out or ''):
        raise Preflight('launcher --which does not resolve the package inside the execution checkout')
    rows, halted, ok_integrity = [], None, True
    for reach_id in plan.reaches:
        if halted:
            rows.append(make_row(plan, reach_id, 'not_run', findings=[{'code': 'not-run', 'detail': halted}]))
            continue
        row = make_row(plan, reach_id, 'error')
        rows.append(row)
        argv = row['command']
        stdout_log, stderr_log = plan.log_paths[reach_id]
        try:
            code, out, err = runner(argv, str(plan.checkout), RUN_TIMEOUT)
            row['returncode'] = code
            write_log(stdout_log, out or '')
            write_log(stderr_log, err or '')
            row['logs'] = {'stdout': str(stdout_log.relative_to(plan.root)),
                           'stderr': str(stderr_log.relative_to(plan.root))}
            if code is None:
                raise Evidence('timeout', f'run exceeded {RUN_TIMEOUT} seconds')
            if code != 0:
                raise Evidence('child-failed', f'run exited {code}; see the stderr log for the missing input or error')
            actual, unchanged, findings, private = evaluate(plan, reach_id, out)
            diffs = compare(plan.baseline_values[reach_id], actual['values'])
            row.update(actual=actual, unchanged=unchanged, differences=diffs, findings=findings)
            row['status'] = 'held' if findings else ('different' if diffs else 'exact')
        except Evidence as error:
            row['findings'].append({'code': error.code, 'detail': error.detail})
            halted = f'earlier reach {reach_id} stopped the run: {error.code}'
        except OSError as error:
            row['findings'].append({'code': 'log-write-failed', 'detail': type(error).__name__})
            halted = f'earlier reach {reach_id} stopped the run: log-write-failed'
        finally:
            base_ok, src_ok = integrity(plan, snapshot)
            row['integrity'] = {'baseline_unchanged': base_ok, 'source_checkout_unchanged': src_ok}
        if not (row['integrity']['baseline_unchanged'] and row['integrity']['source_checkout_unchanged']):
            ok_integrity = False
            row['status'] = 'error'
            row['findings'].append({'code': 'integrity-changed',
                                    'detail': 'baseline or source checkout changed during the run; nothing was repaired'})
            halted = f'integrity failed at reach {reach_id}'
    final = integrity(plan, snapshot)
    ok_integrity = ok_integrity and all(final)
    for row in rows:
        if row['status'] == 'not_run':
            row['integrity'] = {'baseline_unchanged': final[0], 'source_checkout_unchanged': final[1]}
    return rows, ok_integrity


def exit_code(rows, ok_integrity):
    if not ok_integrity or any(r['status'] in ('error', 'not_run') for r in rows):
        return 2
    return 0 if all(r['status'] == 'exact' for r in rows) else 1


# ----------------------------------------------------------------------- CLI
def parser():
    p = argparse.ArgumentParser(prog='run_parity.py', description=__doc__.split('\n\n')[0])
    p.add_argument('--row-id', required=True, choices=ROW_IDS, help='MGL row (06..09); selects the private row root')
    p.add_argument('--source-checkout', required=True, help='git checkout holding source_commit (read only)')
    p.add_argument('--checkout', required=True, help='prepared disposable private checkout under the row root')
    p.add_argument('--baseline-dir', required=True, help='row-root dir with manifest.json, seafloor-ledger.json, reaches.json')
    p.add_argument('--reaches-file', required=True, help='JSON array of unique reach IDs, in output order')
    p.add_argument('--output', required=True, help='new JSONL file under the row root (must not exist)')
    p.add_argument('--python', required=True, help='interpreter with the checkout seafloor dependencies')
    return p


def main(argv=None, *, runner=None, private_parent=None):
    args = parser().parse_args(argv)
    runner = runner or default_runner
    try:
        plan = admit(args, private_parent or PRIVATE_PARENT)
        rows, ok_integrity = drive(plan, runner)
    except Preflight as error:
        sys.stderr.write(f'run_parity: refused: {error}\n')
        return 2
    except Evidence as error:
        sys.stderr.write(f'run_parity: refused: {error}\n')
        return 2
    code = exit_code(rows, ok_integrity)
    try:
        with open(plan.output, 'x', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row) + '\n')
    except OSError as error:
        sys.stderr.write(f'run_parity: cannot create output: {type(error).__name__}\n')
        return 2
    counts = {}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    print(f'{plan.output} exit={code} ' + ' '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    return code


if __name__ == '__main__':
    sys.exit(main())
