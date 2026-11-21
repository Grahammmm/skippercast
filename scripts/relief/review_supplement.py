#!/usr/bin/env python3
"""Show standalone depth coverage beside an R8 packet, not as release evidence."""
import argparse
import math
from pathlib import Path
import stat
import sys

if __name__ == '__main__' and not __package__:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
    from r8_packet import _current_envelope, _print_region
else:
    from .r8_packet import _current_envelope, _print_region

from skippercast.relief import envelope, package, receipts
from skippercast.util.units import FT_PER_M

_BANDS = ('0-66ft', '66-300ft', 'unknown-band')
_LABELS = ('measured', 'estimated', 'unsurveyed')


def _packaged_mosaic(region: receipts.Region) -> str | None:
    """Find mosaic lineage pinned by the package, not the live mosaic receipt."""
    try:
        review = _current_envelope(region.out_root, region.id)
        verified = envelope.verify_artifacts(review)
    except (OSError, ValueError, ImportError, KeyError, TypeError, RecursionError):
        return None

    pending = [('package', None, verified.generation)]
    seen = set()
    mosaics = set()
    while pending:
        stage, scope, generation = pending.pop()
        key = stage, scope, generation
        if key in seen or scope not in (None, 'public'):
            continue
        seen.add(key)
        if (stage, scope) == ('mosaic', 'public'):
            mosaics.add(generation)
            continue
        try:
            path = region.receipt_path(stage, scope).relative_to(region.dir)
            doc = package.decode_document(package.artifact_path(region.dir, path.as_posix()).read_bytes())
            if (receipts.validate_receipt(doc, region.id, stage, scope) or doc['status'] != 'ok'
                    or doc['generation'] != generation
                    or receipts.generation(doc['inputs'], doc['upstream'], doc['code']['stage_digest'],
                                           doc['params']) != generation):
                continue
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            continue
        pending.extend((u['stage'], u.get('scope'), u['generation']) for u in doc['upstream'])
    return next(iter(mosaics)) if len(mosaics) == 1 else None


def _number(value, reason: str) -> float:
    if type(value) not in (int, float) or value < 0 or not math.isfinite(value):
        raise ValueError(reason)
    return float(value)


def _coverage_rows(report: dict, region_id: str) -> list[tuple[str, str]]:
    if report.get('region', region_id) != region_id:
        raise ValueError('report region does not match')
    for key in ('mosaic_generation', 'coarse_sha256'):
        if report.get(key) is not None and not package.is_sha256(report[key]):
            raise ValueError(f'invalid {key}')
    reaches = report.get('reaches_300ft')
    if type(reaches) is not bool:
        raise ValueError('reaches_300ft must be a boolean')
    if 'deepest_m' not in report:
        raise ValueError('missing deepest_m')
    deepest = report['deepest_m']
    depth_error = 'deepest_m must be a finite nonnegative depth or null'
    feet = 'unknown'
    if deepest is not None:
        depth_ft = _number(deepest, depth_error) * FT_PER_M
        if not math.isfinite(depth_ft):
            raise ValueError(depth_error)
        feet = f'{depth_ft:.0f}'
    rows = [('depth', f'reaches_300ft={str(reaches).lower()} deepest_ft={feet}')]
    bands = report.get('bands')
    if not isinstance(bands, dict) or bands.keys() != set(_BANDS):
        raise ValueError('expected 0-66ft, 66-300ft and unknown-band in bands')
    for band in _BANDS:
        values = bands[band]
        area_error = f'{band} areas must be finite nonnegative numbers'
        if not isinstance(values, dict):
            raise ValueError(area_error)
        areas = [_number(values.get(f'{label}_m2'), area_error) for label in _LABELS]
        total = sum(areas)
        if not math.isfinite(total):
            raise ValueError(f'{band} total must be finite')
        shares = [f'{area / total * 100:.1f}%' if total else 'n/a' for area in areas]
        rows.append((f'depth {band}', ' '.join(f'{label}={share}' for label, share in zip(_LABELS, shares))))
    return rows


def _depth_rows(out: Path, region_id: str) -> list[tuple[str, str]]:
    try:
        region = receipts.Region(out, region_id)
        path = region.dir / 'coverage' / 'depth-coverage.json'
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('expected a file')
        report = package.decode_document(path.read_bytes())
        rows = _coverage_rows(report, region_id)
    except FileNotFoundError:
        return [('depth', 'not computed (run region.py depth-coverage)')]
    except (OSError, ValueError, OverflowError, RecursionError) as exc:
        reason = ' '.join(str(exc).splitlines())
        return [('depth', f'invalid report ({reason})')]

    reported = report.get('mosaic_generation')
    if reported is not None:
        packaged = _packaged_mosaic(region)
        if packaged is not None and reported != packaged:
            return [('depth', f'stale (mosaic {reported[:12]})')]
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='review_supplement.py', description=__doc__)
    parser.add_argument('--out', required=True, type=Path, metavar='OUT')
    parser.add_argument('--markdown', action='store_true', help='print one review table per region')
    parser.add_argument('regions', nargs='+', metavar='REGION')
    args = parser.parse_args(argv)
    if len(args.regions) > 3:
        parser.error('expected at most 3 regions')
    for region in args.regions:
        try:
            receipts.check_names('envelope', region=region)
        except receipts.ReceiptError as exc:
            parser.error(str(exc))
    for region in args.regions:
        _print_region(f'Depth coverage {region} (supplement only)', _depth_rows(args.out, region), args.markdown)
    return 0


if __name__ == '__main__':
    sys.exit(main())
