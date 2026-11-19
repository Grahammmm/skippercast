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


# Review the Node TAP case roster and bump this version when it changes.
# Do not infer the expectation from the TAP summary being certified.
SUITE_VERSION = 1
REQUIRED_CASES = (
    'the committed Morro Bay contours pass the check: feet, a 30 ft interval, a survey, date and datum on every line',
    'past review_expires the contours are withheld; any gap in the file fails it whole',
    'the overview draws below the detail zoom; the full contours from it, and for the rest of the visit once loaded',
    'the overlay: a dashed survey edge, contours heavier at the index, a click target and labels in feet, from the palette',
    'the card names the depth, interval, survey date and datum, and no source name (MAP-SOURCES-PAGE-1); the edge says no reviewed grid continues',
    'the registry entry: always on, Chart only, every zoom; the basis says not for navigation, names the datum and where lines stop',
    'with diagnostics on, the host reports the contour click targets MapLibre drew at each idle; off, nothing is counted',
    'the Chart layer draws the overview under the protected areas, swaps in the full contours at the detail zoom and keeps them',
    'a region without contours draws none and shows no row; expired contours are withheld and say so',
    'the committed Morro Bay file names noaa-bag as an approved survey it does not trace, with no unreviewed note',
    'the file names the bound surveys it does not draw; the card and the drawn note say so in plain words',
    'a file without a well-formed omitted list fails; the note counts only unapproved surveys',
    'EC6: filled and verified runs and a conflict area draw; their cards say how each was made, keeping the basis',
    'EC6: any unknown kind, geometry, reason, hint or provenance still fails the whole file',
    'EC6: Polygon requires an exact geometry type or the whole file fails',
    'EC6: MultiPolygon requires an exact geometry type or the whole file fails',
    'EC6: the area draws muted and dashed at the bottom; filled runs dash and verified runs draw heavier; the area is clickable',
    'contour_expiry_rejects_impossible_calendar: an impossible date fails closed, never throws',
    'contour_expiry_valid_leap_and_utc_boundaries: real dates keep the inclusive last day and next-day withholding',
    'contour_invalid_expiry_never_draws: the layer shows failed with nothing drawn',
    'contour_invalid_expiry_never_exports: the trip export refuses the file, and a valid one still passes',
    'ft-v2 selects published depths and labels, replaces coarse runs at z14, and never exposes a hidden tap target',
    'ft-v2 refuses wrong region, units, expiry, unsupported detail, or wrong indices',
    'ft-v2 uses the shallow ink and halo through 100 ft, with independent index weights',
)


def passed(tap, counts, exit_code):
    """Require the reviewed flat suite, not merely a self-reported green count."""
    size = len(REQUIRED_CASES)
    if not (exit_code == 0 and counts['tests'] == counts['pass'] == size
            and counts['fail'] == counts['skipped'] == counts['cancelled'] == counts['todo'] == 0):
        return False
    body, *footer = re.split(r'^1\.\.(\d+)$', tap, flags=re.MULTILINE)
    if (not body.startswith('TAP version 13\n') or len(footer) != 2 or footer[0] != str(size)
            or not footer[1].startswith(f'\n# tests {size}\n') or re.search(r'^Bail out!', tap, re.MULTILINE)):
        return False
    # Node indents diagnostics. Only a top-level result can satisfy a required case.
    results = re.findall(r'^(ok|not ok) (\d+) - (.+)$', body, re.MULTILINE)
    return ([(status, number) for status, number, _ in results]
            == [('ok', str(i)) for i in range(1, size + 1)]
            and {name for _, _, name in results} == set(REQUIRED_CASES))


def create_receipt(root, tap, commit, node_version, ran_at, exit_code):
    root = Path(root)
    if type(exit_code) is not int:
        raise ValueError('invalid exit code')
    counts = {}
    for key in ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo'):
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
    receipt = {'schema_version': 3, 'suite_version': SUITE_VERSION, 'scope': 'morro-bay-depth-contours-test',
               'ran_at': ran_at, 'commit': commit, 'command': COMMAND,
               'node_version': node_version, 'exit_code': exit_code, **counts,
               'result': 'pass' if passed(tap, counts, exit_code) else 'fail',
               'files': files, 'review_expires': expiry}
    stamp = timestamp.strftime('%Y-%m-%dT%H%M%S.%fZ')
    output = root / 'research' / 'receipts' / f'morro-bay-depth-contours-test-{stamp}.json'
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
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        output = create_receipt(ROOT, run.stdout, commit, node_version, now, run.returncode)
        print(output.relative_to(ROOT))
        if json.loads(output.read_text(encoding='utf-8'))['result'] != 'pass':
            print('contour receipt: recorded result=fail', file=sys.stderr)
            return 1
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(f'contour receipt: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
