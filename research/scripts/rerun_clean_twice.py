"""Run a declared coastal pipeline twice from clean state and report COAST-PROD-01..06 (T15).

A JSON spec (schema ``coastal-clean-rerun-spec-v1``) lists the steps. Each
pass gets a brand-new, empty root under ``work_base`` (``pass-1``, ``pass-2``);
``work_base`` itself must not exist yet, so no earlier output can leak in.
Declared inputs are copied into each pass root and hash-checked. Every step
runs with ``HOME``, ``TMPDIR`` and ``XDG_CACHE_HOME`` inside its pass root and
``PYTHONDONTWRITEBYTECODE=1``. ``guard_paths`` (mission roots, canonical
stores, retained evidence) are hashed before and after every pass and must not
change.

After both passes the declared deterministic outputs are compared by sha256.
Each COAST-PROD id is PASS only when it maps to at least one step or cited
receipt, every mapped step passed in every pass (expected exit code, receipt
present, receipt checks hold), its deterministic outputs are identical across
passes, every cited receipt exists, matches its pinned sha256 and passes its
checks, and the guards are unchanged. An id with neither is NO_RECEIPT; a
declared hold is HELD; neither is ever PASS. The overall verdict is PASS only
when all six are.

Spec::

    {"schema": "coastal-clean-rerun-spec-v1", "name": "...",
     "work_base": "/abs/new/dir", "passes": 2, "stop_on_failure": true,
     "guard_paths": ["/abs/read-only/tree"],
     "stage_inputs": [{"from": "/abs/src", "to": "relative/in/pass/root"}],
     "env": {"PYTHONPATH": "/abs/src"},
     "steps": [{"id": "render", "argv": ["{python}", "-B", "-m", "..."],
                "cwd": "{root}", "timeout_s": 600, "expect_exit": [0],
                "deterministic_outputs": ["core-A/render/preview.png"],
                "receipt": "t13-receipt.json",
                "receipt_checks": [{"pointer": "/verdict", "equals": "PASS"}]}],
     "coast_prod": {"COAST-PROD-04": {"steps": ["render"], "description": "..."},
                    "COAST-PROD-03": {"evidence": [{"path": "/abs/earlier/receipt.json",
                                      "sha256": "<pin>", "receipt_checks": [...]}]},
                    "COAST-PROD-06": {"held": "GPU qualification held"}}}

Placeholders in argv, cwd and env values: ``{root}`` (this pass root),
``{pass}``, ``{python}`` (this interpreter), ``{spec_dir}``, ``{work_base}``.
Relative output and receipt paths are inside the pass root.

    python -B research/scripts/rerun_clean_twice.py --spec spec.json [--dry-run]

Exit codes: 0 PASS, 1 not PASS, 2 spec or usage error. Reports are written to
``work_base/report.json`` and ``work_base/report.md``.
"""
import argparse
from datetime import datetime, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SPEC_SCHEMA = 'coastal-clean-rerun-spec-v1'
REPORT_SCHEMA = 'coastal-clean-rerun-report-v1'
PROD_IDS = tuple(f'COAST-PROD-0{n}' for n in range(1, 7))
DEFAULT_GUARD_MAX_BYTES = 8 * 1024 ** 3
BASE_ENV_KEYS = ('PATH', 'LANG', 'LC_ALL', 'TZ')


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def tree_manifest(path, *, max_bytes=DEFAULT_GUARD_MAX_BYTES):
    """Path -> sha256/size (or link target) for every entry under a file or directory."""
    path = Path(path)
    entries, total = {}, 0
    if path.is_symlink():
        return {'.': dict(link=os.readlink(path))}
    if path.is_file():
        return {'.': dict(sha256=sha256_file(path), bytes=path.stat().st_size)}
    if not path.is_dir():
        return {'.': dict(missing=True)}
    for directory, dirs, files in os.walk(path, followlinks=False):
        dirs.sort()
        here = Path(directory)
        for name in sorted(dirs):
            if (here / name).is_symlink():
                entries[(here / name).relative_to(path).as_posix()] = dict(link=os.readlink(here / name))
        for name in sorted(files):
            item = here / name
            rel = item.relative_to(path).as_posix()
            if item.is_symlink():
                entries[rel] = dict(link=os.readlink(item))
                continue
            size = item.stat().st_size
            total += size
            if total > max_bytes:
                raise ValueError(f'guard_byte_bound_exceeded:{path}')
            entries[rel] = dict(sha256=sha256_file(item), bytes=size)
        if not files and not dirs:
            entries[here.relative_to(path).as_posix() + '/'] = dict(directory=True)
    return entries


def manifest_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def expand(value, mapping):
    if isinstance(value, str):
        for key, replacement in mapping.items():
            value = value.replace('{' + key + '}', replacement)
        return value
    if isinstance(value, list):
        return [expand(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, mapping) for k, v in value.items()}
    return value


def pointer_get(document, pointer):
    if pointer in ('', '/'):
        return document
    value = document
    for part in pointer.lstrip('/').split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            value = value[int(part)]
        else:
            value = value[part]
    return value


def confined_relative(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError(f'path must be relative inside the pass root: {relative}')
    return Path(root) / rel


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    problems = []
    if spec.get('schema') != SPEC_SCHEMA:
        problems.append(f'schema must be {SPEC_SCHEMA}')
    if not isinstance(spec.get('work_base'), str) or not Path(spec['work_base']).is_absolute():
        problems.append('work_base must be an absolute path')
    if spec.get('passes', 2) < 2:
        problems.append('passes must be >= 2')
    steps = spec.get('steps')
    if not isinstance(steps, list) or not steps:
        problems.append('steps must be a non-empty list')
        steps = []
    ids = [s.get('id') for s in steps]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        problems.append('step ids must be unique non-empty strings')
    for step in steps:
        if not isinstance(step.get('argv'), list) or not step['argv'] or not all(isinstance(a, str) for a in step['argv']):
            problems.append(f'step {step.get("id")}: argv must be a non-empty list of strings')
        for rel in [*step.get('deterministic_outputs', []), *([step['receipt']] if step.get('receipt') else [])]:
            try:
                confined_relative('/r', rel)
            except ValueError as error:
                problems.append(f'step {step.get("id")}: {error}')
        for check in step.get('receipt_checks', []):
            if 'pointer' not in check or not ({'equals', 'exists'} & set(check)):
                problems.append(f'step {step.get("id")}: receipt check needs pointer and equals/exists')
        if step.get('receipt_checks') and not step.get('receipt'):
            problems.append(f'step {step.get("id")}: receipt_checks need a receipt')
    prod = spec.get('coast_prod', {})
    unknown = sorted(set(prod) - set(PROD_IDS))
    if unknown:
        problems.append('unknown COAST-PROD ids: ' + ', '.join(unknown))
    for key, value in prod.items():
        if not isinstance(value, dict):
            problems.append(f'{key}: mapping must be an object')
            continue
        missing = sorted(set(value.get('steps', [])) - set(ids))
        if missing:
            problems.append(f'{key}: unknown steps {missing}')
        if value.get('held') and (value.get('steps') or value.get('evidence')):
            problems.append(f'{key}: a held id cannot also map steps or evidence')
        for item in value.get('evidence', []):
            if not isinstance(item, dict) or not Path(item.get('path', '')).is_absolute():
                problems.append(f'{key}: evidence needs an absolute path')
            elif any('pointer' not in c or not ({'equals', 'exists'} & set(c)) for c in item.get('receipt_checks', [])):
                problems.append(f'{key}: evidence check needs pointer and equals/exists')
    for item in spec.get('stage_inputs', []):
        if not Path(item.get('from', '')).is_absolute():
            problems.append('stage_inputs.from must be absolute')
        try:
            confined_relative('/r', item.get('to', ''))
        except ValueError as error:
            problems.append(f'stage_inputs.to: {error}')
    for guard in spec.get('guard_paths', []):
        if not Path(guard).is_absolute():
            problems.append(f'guard path must be absolute: {guard}')
        elif Path(spec.get('work_base', '/nonexistent')).resolve().is_relative_to(Path(guard).resolve()):
            problems.append(f'work_base must not be inside guard path {guard}')
    if problems:
        raise ValueError('; '.join(problems))
    return spec


def stage(spec, root):
    staged = []
    for item in spec.get('stage_inputs', []):
        source = Path(item['from'])
        target = confined_relative(root, item['to'])
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target)
        before, after = tree_manifest(source), tree_manifest(target)
        if before != after:
            raise ValueError(f'staged copy differs from source: {source}')
        staged.append(dict(source=str(source), target=item['to'], digest=manifest_digest(after), entries=len(after)))
    return staged


def step_env(spec, root, mapping):
    env = {k: os.environ[k] for k in BASE_ENV_KEYS if k in os.environ}
    home = Path(root) / '.home'
    tmp = Path(root) / '.tmp'
    home.mkdir(exist_ok=True)
    tmp.mkdir(exist_ok=True)
    env.update(HOME=str(home), TMPDIR=str(tmp), XDG_CACHE_HOME=str(home / '.cache'),
               PYTHONDONTWRITEBYTECODE='1', SKIPPERCAST_CLEAN_RERUN_PASS=mapping['pass'])
    env.update(expand(spec.get('env', {}), mapping))
    return env


def run_step(step, spec, root, mapping):
    argv = expand(step['argv'], mapping)
    cwd = expand(step.get('cwd', '{root}'), mapping)
    env = step_env(spec, root, mapping)
    env.update(expand(step.get('env', {}), mapping))
    started = time.monotonic()
    log_dir = Path(root) / '.rerun-logs'
    log_dir.mkdir(exist_ok=True)
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=step.get('timeout_s', 600), check=False)
        code, out, err = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as error:
        code, out, err = 'timeout', error.stdout or '', error.stderr or ''
    except OSError as error:
        code, out, err = 'launch_error', '', f'{type(error).__name__}: {error}'
    if isinstance(out, bytes):
        out = out.decode('utf-8', 'replace')
    if isinstance(err, bytes):
        err = err.decode('utf-8', 'replace')
    (log_dir / f'{step["id"]}.stdout').write_text(out or '')
    (log_dir / f'{step["id"]}.stderr').write_text(err or '')
    problems = []
    if code not in step.get('expect_exit', [0]):
        problems.append(f'exit {code} not in {step.get("expect_exit", [0])}')
    outputs = {}
    for pattern in step.get('deterministic_outputs', []):
        matches = sorted(glob.glob(str(confined_relative(root, pattern)), recursive=True))
        if not matches:
            problems.append(f'deterministic output missing: {pattern}')
        for match in matches:
            if Path(match).is_file():
                outputs[Path(match).relative_to(root).as_posix()] = sha256_file(match)
    receipt = None
    if step.get('receipt'):
        receipt, receipt_problems = check_receipt(confined_relative(root, step['receipt']),
                                                  step.get('receipt_checks', []), label=step['receipt'])
        problems.extend(receipt_problems)
    return dict(id=step['id'], argv=argv, cwd=cwd, exit_code=code, ok=not problems, problems=problems,
                wall_s=round(time.monotonic() - started, 3), outputs=outputs, receipt=receipt,
                stdout_tail=(out or '')[-800:], stderr_tail=(err or '')[-800:])


def check_receipt(path, checks, *, label, pin=None):
    """Hash a JSON receipt and apply pointer checks; returns (ref or None, problems)."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return None, [f'receipt missing: {label}']
    found = dict(path=label, sha256=sha256_file(path), bytes=path.stat().st_size)
    problems = []
    if pin and found['sha256'] != pin:
        problems.append(f'receipt {label} sha256 {found["sha256"]} != pinned {pin}')
    if not checks:
        return found, problems
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        return found, [*problems, f'receipt not JSON: {error}']
    for check in checks:
        try:
            value = pointer_get(document, check['pointer'])
        except (KeyError, IndexError, ValueError, TypeError):
            problems.append(f'receipt {label} {check["pointer"]} missing')
            continue
        if 'equals' in check and value != check['equals']:
            problems.append(f'receipt {label} {check["pointer"]} = {value!r}, expected {check["equals"]!r}')
    return found, problems


def run_pass(spec, number, work_base, spec_dir, guards_before):
    root = Path(work_base) / f'pass-{number}'
    root.mkdir()  # fails if it exists: every pass starts from nothing
    if any(root.iterdir()):
        raise RuntimeError('pass root not empty')
    mapping = {'root': str(root), 'pass': str(number), 'python': sys.executable,
               'spec_dir': str(spec_dir), 'work_base': str(work_base)}
    result = dict(number=number, root=str(root), started_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    try:
        result['staged'] = stage(spec, root)
    except (OSError, ValueError) as error:
        result.update(staged=[], stage_error=f'{type(error).__name__}: {error}', steps=[])
        return result
    steps, failed = [], False
    for step in spec['steps']:
        if failed and spec.get('stop_on_failure', True):
            steps.append(dict(id=step['id'], ok=False, problems=['not run: an earlier step failed'], outputs={}))
            continue
        outcome = run_step(step, spec, root, mapping)
        steps.append(outcome)
        failed = failed or not outcome['ok']
    result['steps'] = steps
    after = {g: manifest_digest(tree_manifest(g)) for g in spec.get('guard_paths', [])}
    result['guards_unchanged'] = after == guards_before
    result['guards_changed'] = sorted(g for g in after if after[g] != guards_before.get(g))
    result['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return result


def compare_passes(passes, spec):
    comparison = {}
    for step in spec['steps']:
        per_pass = [next((s for s in p['steps'] if s['id'] == step['id']), {}) for p in passes]
        outputs = [s.get('outputs', {}) for s in per_pass]
        keys = sorted(set().union(*outputs))
        differing = [k for k in keys if len({o.get(k) for o in outputs}) != 1]
        comparison[step['id']] = dict(compared=len(keys), differing=differing,
                                      identical=bool(keys) and not differing if step.get('deterministic_outputs') else None)
    return comparison


def evaluate(spec, passes, comparison):
    guards_ok = all(p.get('guards_unchanged', False) for p in passes)
    staged_ok = all('stage_error' not in p for p in passes)
    prod = {}
    for pid in PROD_IDS:
        entry = spec.get('coast_prod', {}).get(pid)
        if entry and entry.get('held'):
            prod[pid] = dict(status='HELD', reason=entry['held'], description=entry.get('description'))
            continue
        if not entry or not (entry.get('steps') or entry.get('evidence')):
            prod[pid] = dict(status='NO_RECEIPT', reason='no step or cited receipt mapped to this id in the spec')
            continue
        reasons = []
        for sid in entry.get('steps', []):
            for p in passes:
                outcome = next((s for s in p['steps'] if s['id'] == sid), None)
                if outcome is None or not outcome['ok']:
                    reasons.append(f'pass {p["number"]} step {sid}: ' +
                                   ('; '.join(outcome['problems']) if outcome else 'not run'))
            cmp = comparison.get(sid, {})
            if cmp.get('differing'):
                reasons.append(f'step {sid}: outputs differ across passes: {cmp["differing"]}')
        if entry.get('steps') and not guards_ok:
            reasons.append('guarded paths changed during a pass')
        if entry.get('steps') and not staged_ok:
            reasons.append('input staging failed')
        receipts = [dict(p=p['number'], step=s['id'], **s['receipt']) for p in passes for s in p['steps']
                    if s['id'] in entry.get('steps', []) and s.get('receipt')]
        for item in entry.get('evidence', []):
            found, problems = check_receipt(item['path'], item.get('receipt_checks', []), label=item['path'],
                                            pin=item.get('sha256'))
            reasons.extend(problems)
            if found:
                receipts.append(dict(cited=True, **found))
        prod[pid] = dict(status='FAIL' if reasons else 'PASS', reasons=reasons, steps=entry.get('steps', []),
                         description=entry.get('description'), receipts=receipts)
    verdict = 'PASS' if (all(v['status'] == 'PASS' for v in prod.values()) and guards_ok and staged_ok) else 'NOT_PASS'
    return verdict, prod, guards_ok


def markdown(report):
    lines = [f'# Clean rerun x{len(report["passes"])}: {report["name"]}', '',
             f'Verdict: **{report["verdict"]}** (PASS needs all six COAST-PROD ids PASS).', '',
             f'Spec sha256 `{report["spec_sha256"]}`; work base `{report["work_base"]}`.', '',
             '| id | status | detail |', '| --- | --- | --- |']
    for pid, value in report['coast_prod'].items():
        detail = value.get('reason') or '; '.join(value.get('reasons', [])) or ', '.join(value.get('steps', []))
        lines.append(f'| {pid} | {value["status"]} | {detail.replace("|", "/")} |')
    lines += ['', '| step | ' + ' | '.join(f'pass {p["number"]}' for p in report['passes']) + ' | identical |',
              '| --- |' + ' --- |' * (len(report['passes']) + 1)]
    for step in report['steps']:
        cells = []
        for p in report['passes']:
            outcome = next((s for s in p['steps'] if s['id'] == step), {})
            cells.append(('ok' if outcome.get('ok') else 'FAIL') + f' (exit {outcome.get("exit_code")})')
        same = report['comparison'][step]['identical']
        lines.append(f'| {step} | ' + ' | '.join(cells) + f' | {"-" if same is None else same} |')
    lines += ['', f'Guards unchanged: {report["guards_unchanged"]}.', '',
              'Machine-valid output is review-required, not semantic or publication acceptance.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true', help='validate the spec and print the plan only')
    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.spec)
    except (OSError, ValueError) as error:
        print(json.dumps(dict(error=str(error))))
        return 2
    spec_dir = args.spec.resolve().parent
    work_base = Path(spec['work_base'])
    if args.dry_run:
        plan = [dict(id=s['id'], argv=expand(s['argv'], {'root': '<pass-root>', 'pass': 'N', 'python': sys.executable,
                     'spec_dir': str(spec_dir), 'work_base': str(work_base)})) for s in spec['steps']]
        mapped = {pid: spec.get('coast_prod', {}).get(pid, {}) for pid in PROD_IDS}
        print(json.dumps(dict(work_base=str(work_base), exists=work_base.exists(), steps=plan, coast_prod=mapped), indent=1))
        return 0
    if work_base.exists():
        print(json.dumps(dict(error=f'work_base exists: {work_base}; clean state needs a new directory')))
        return 2
    work_base.mkdir(parents=True)
    guards_before = {g: manifest_digest(tree_manifest(g)) for g in spec.get('guard_paths', [])}
    passes = [run_pass(spec, n, work_base, spec_dir, guards_before) for n in range(1, spec.get('passes', 2) + 1)]
    comparison = compare_passes(passes, spec)
    verdict, prod, guards_ok = evaluate(spec, passes, comparison)
    report = dict(schema=REPORT_SCHEMA, name=spec.get('name', args.spec.stem), verdict=verdict,
                  created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  spec=str(args.spec.resolve()), spec_sha256=sha256_file(args.spec), work_base=str(work_base),
                  driver_sha256=sha256_file(__file__), guards=guards_before, guards_unchanged=guards_ok,
                  coast_prod=prod, steps=[s['id'] for s in spec['steps']], comparison=comparison, passes=passes,
                  limitations=['Machine-valid output is review-required, not semantic or publication acceptance.'])
    (work_base / 'report.json').write_text(json.dumps(report, sort_keys=True, indent=1) + '\n')
    (work_base / 'report.md').write_text(markdown(report))
    print(json.dumps(dict(verdict=verdict, report=str(work_base / 'report.json'),
                          report_sha256=sha256_file(work_base / 'report.json'),
                          coast_prod={k: v['status'] for k, v in prod.items()}), indent=1))
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
