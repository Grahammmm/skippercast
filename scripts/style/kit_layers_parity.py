#!/usr/bin/env python3
"""AgentOrange only: compare production layer exports with verified private kit goldens."""

import argparse
from datetime import datetime, timedelta
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = Path.home() / 'agent-work/sc-style/layers-parity'
GUIDE = Path('layers-style-guide')
NEARSHORE = Path('nearshore-kit/style-guide')
TOKENS = {
    'layers-v1.0.0.json': GUIDE / 'layer-tokens.json',
    'stacking-v1.0.0.json': GUIDE / 'stacking.json',
    'nearshore-v1.0.0.json': NEARSHORE / 'style-tokens.json',
}
RENDERER_ONLY_KEYS = {
    '02-sst-breaks': {'n_iso_labels'},
    '07-currents': {'streamline_segments'},
    '11-wind': {'particle_segments'},
    '25-STACK-A': {'streamline_segments'},
    '26-NEAR-D': {'n_iso_labels'},
}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def run(*args, cwd=ROOT, env=None):
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def checked(*args, **kwargs):
    proc = run(*args, **kwargs)
    if proc.returncode:
        raise ValueError(f'{Path(args[0]).name} exited {proc.returncode}: {proc.stderr.strip()}')
    return proc.stdout.strip()


class Kit:
    def __init__(self, root):
        self.root = root.resolve(strict=True)
        self.manifest = self.root.parents[1] / 'kit.FILES.sha256'
        self.files = {}
        for line in self.manifest.read_text().splitlines():
            match = re.fullmatch(r'([0-9a-f]{64}) [ *]\./(.+)', line)
            if not match:
                raise ValueError('invalid kit file manifest row')
            digest, name = match.groups()
            rel = Path(name)
            if rel.is_absolute() or '..' in rel.parts or rel in self.files:
                raise ValueError('unsafe or duplicate kit manifest path')
            self.files[rel] = digest

    def verify(self):
        for name, rel in TOKENS.items():
            if sha(ROOT / 'style' / name) != self.files[rel]:
                raise ValueError(f'repository token bytes differ: {name}')

    def stage(self, target):
        # Only manifested files enter the subprocess/import tree. In particular,
        # never execute unmanifested bytecode left behind by another local run.
        for rel, digest in self.files.items():
            source, destination = self.root / rel, target / rel
            if source.resolve(strict=True) != source or not source.is_file():
                raise ValueError(f'kit input is not an ordinary file: {rel}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if sha(destination) != digest:
                raise ValueError(f'kit file mismatch: {rel}')
        self.root = target


def scope_golden(kit, case, target, only_keys):
    source = kit.root / GUIDE / 'golden' / case
    target.mkdir(parents=True)
    for image in ('field.png', 'base.png'):
        if not only_keys and (source / image).is_file():
            shutil.copyfile(source / image, target / image)
    metrics = json.loads((source / 'metrics.json').read_bytes())
    dropped = RENDERER_ONLY_KEYS.get(case, set())
    (target / 'metrics.json').write_bytes(json_bytes({
        key: val for key, val in metrics.items()
        if key not in dropped and (not only_keys or key in only_keys)
    }))


def adapter(path):
    spec = importlib.util.spec_from_file_location('layer_case', path)
    if spec is None or spec.loader is None:
        raise ValueError(f'cannot load adapter {path.name}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prepare


def hashes(path):
    return {p.relative_to(path).as_posix(): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def one_case(kit, path, target, options, env):
    from PIL import Image

    case = path.stem
    scoped, inputs, ours = (target / kind / case for kind in ('scoped', 'inputs', 'ours'))
    scope_golden(kit, case, scoped, options.only_keys)
    inputs.mkdir(parents=True)
    ours.mkdir(parents=True)
    adapter(path)(kit.root, inputs)
    cmd = ['node', str(HERE / 'export_layer_case.mjs'), '--case', case, '--in', str(inputs), '--out', str(ours)]
    if options.now:
        cmd += ['--now', options.now]
    if options.negative:
        cmd += ['--palette-override', '--skl-sst-fill-ramp-stops-4=#a0e05a']
    checked(*cmd, env=env)
    raw = ours / 'field.rgba'
    if raw.is_file():
        with (inputs / 'case.json').open() as stream:
            view = json.load(stream)['view_grid']
        pixels = raw.read_bytes()
        size = len(view['lon']), len(view['lat'])
        if len(pixels) != size[0] * size[1] * 4:
            raise ValueError(f'{case}: RGBA byte length does not match view grid')
        if not options.only_keys:
            Image.frombytes('RGBA', size, pixels).save(ours / 'field.png')
        raw.unlink()
    proc = run(sys.executable, kit.root / GUIDE / 'reference/compare.py', 'case', ours, scoped, env=env)
    verdict = json.loads(proc.stdout)
    if not isinstance(verdict.get('pass'), bool) or proc.returncode != int(not verdict['pass']):
        raise ValueError(f'{case}: invalid comparator result')
    print(json.dumps(verdict, sort_keys=True))
    return {'verdict': verdict, 'inputs': hashes(inputs), 'scoped': hashes(scoped), 'ours': hashes(ours)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--now')
    parser.add_argument('--negative', choices=['sst-ramp'])
    parser.add_argument('--only-keys')
    parser.add_argument('--stacking-only', action='store_true')
    args = parser.parse_args()
    if args.stacking_only:
        parser.error('--stacking-only requires the MSKL-3 stacking engine')
    args.only_keys = set(args.only_keys.split(',')) if args.only_keys else set()
    if args.now:
        clock = datetime.fromisoformat(args.now)
        if clock.utcoffset() != timedelta(0):
            raise ValueError('--now must be an ISO UTC timestamp')
    cases = sorted(set(args.cases.split(',')))
    if args.negative and (cases != ['01-sst-fill'] or args.only_keys or args.now):
        parser.error('--negative sst-ramp requires the unmodified 01-sst-fill clock and full comparison')
    adapters = {p.stem: p for p in (HERE / 'kit_cases').glob('*.py')}
    if not set(cases) <= adapters.keys():
        parser.error('unknown cases: ' + ', '.join(set(cases) - adapters.keys()))
    if checked('git', 'status', '--porcelain=v1', '--untracked-files=all'):
        raise ValueError('parity requires a clean worktree')
    out = args.out.resolve()
    if not out.is_relative_to(OUTPUT) or out.is_relative_to(ROOT):
        raise ValueError(f'outputs must stay under {OUTPUT}')
    kit = Kit(args.kit)
    kit.verify()

    identity = {
        'repo_head': checked('git', 'rev-parse', 'HEAD'),
        'kit_zip_sha256': json.loads((ROOT / 'style/index.json').read_text())['layers']['layers-v1.0.0']['kit_zip_sha256'],
        'kit_files_manifest_sha256': sha(kit.manifest),
        'venv': {'python': sys.version.split()[0], 'pins': sorted({
            line.strip() for path in (GUIDE, NEARSHORE)
            for line in (kit.root / path / 'reference/requirements.txt').read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        })},
        'cases': cases,
    }
    key = hashlib.sha256(json_bytes(identity).rstrip(b'\n')).hexdigest()
    key_dir = out / key
    key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = {'now': args.now, 'negative': args.negative, 'only_keys': sorted(args.only_keys)}
    variant = hashlib.sha256(json_bytes(mode)).hexdigest()[:12]
    report_dir = key_dir / 'variants' / variant if any(mode.values()) else key_dir
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    sys.dont_write_bytecode = True
    with (key_dir / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(dir=key_dir) as staging:
            target = Path(staging)
            kit.stage(target / 'kit')
            env['TMPDIR'] = staging
            env['MPLCONFIGDIR'] = str(target / 'mpl')
            oracle_log = key_dir / 'selftest.log'
            if not oracle_log.is_file() or 'SELFTEST OK' not in oracle_log.read_text():
                output = checked('bash', kit.root / 'selftest.sh', sys.executable, cwd=kit.root, env=env)
                if not any(line.startswith('SELFTEST OK') for line in output.splitlines()):
                    raise ValueError('kit oracle did not print SELFTEST OK')
                oracle_log.write_text('SELFTEST OK\n')
            results = {case: one_case(kit, adapters[case], target, args, env) for case in cases}
            report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            (target / 'parity.json').write_bytes(json_bytes({
                'key': key, 'identity': identity, 'mode': mode, 'cases': results,
                'selftest_sha256': sha(oracle_log),
            }))
            for part in ('scoped', 'inputs', 'ours', 'parity.json'):
                dest = report_dir / part
                if dest.is_dir():
                    shutil.rmtree(dest)
                (target / part).replace(dest)
    n = sum(r['verdict']['pass'] for r in results.values())
    print(f'LAYERS PARITY {"PASS" if n == len(cases) else "FAIL"} {n}/{len(cases)} key={key[:12]}')
    if args.negative:
        verdict = results[cases[0]]['verdict']
        return int(verdict.get('field.png', {}).get('pass') is not False
                   or verdict.get('metrics.json', {}).get('pass') is not True or n != 0)
    return int(n != len(cases))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as exc:
        sys.exit(f'LAYERS PARITY ERROR: {exc}')
