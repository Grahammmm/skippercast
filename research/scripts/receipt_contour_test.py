"""Record a Morro Bay contour test run without embedding its TAP output."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COMMAND = 'node --test --test-reporter=tap tests/test_depth_contours.mjs'
FILES = ('dist/regions/morro-bay/depth-contours.geojson',
         'dist/regions/morro-bay/depth-contours-overview.geojson')


def create_receipt(root, tap, commit, node_version, ran_at):
    root = Path(root)
    counts = {}
    for key in ('tests', 'pass', 'fail', 'skipped'):
        values = re.findall(rf'^# {key} (\S+)\s*$', tap, re.MULTILINE)
        if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
            raise ValueError(f'invalid TAP {key} summary')
        counts[key] = int(values[0])
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('invalid commit')
    timestamp = dt.datetime.fromisoformat(ran_at.replace('Z', '+00:00'))
    if timestamp.utcoffset() != dt.timedelta(0):
        raise ValueError('timestamp must be UTC')
    files = []
    expiry = None
    for name in FILES:
        path = root
        for part in Path(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f'symlink in contour path: {name}')
        data = path.read_bytes()
        value = json.loads(data)['provenance']['review_expires']
        if expiry is not None and value != expiry:
            raise ValueError('contour review expiry mismatch')
        expiry = value
        files.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
    receipt = {'schema_version': 1, 'scope': 'morro-bay-depth-contours-test',
               'ran_at': ran_at, 'commit': commit, 'command': COMMAND,
               'node_version': node_version, **counts,
               'result': 'pass' if counts['fail'] == 0 and counts['tests'] == 16 else 'fail',
               'files': files, 'review_expires': expiry}
    output = root / 'research' / 'receipts' / f'morro-bay-depth-contours-test-{timestamp.date()}.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    return output


def main():
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        node_version = subprocess.check_output(['node', '--version'], cwd=ROOT, text=True).strip()
        run = subprocess.run(COMMAND.split(), cwd=ROOT, text=True, capture_output=True, check=False)
        if run.returncode not in (0, 1):
            raise ValueError(f'node test exited unexpectedly: {run.returncode}')
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        print(create_receipt(ROOT, run.stdout, commit, node_version, now).relative_to(ROOT))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(f'contour receipt: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
