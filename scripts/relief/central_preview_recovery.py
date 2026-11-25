#!/usr/bin/env python3
"""Reversible regional upgrade rehearsal for the Central preview (C45), on a DISPOSABLE tree only.

``rehearse`` lays the six Central regions' owned files (C30 ``owned_paths``) into a new disposable tree from the
pinned six-region bundle (every byte checked against its pin; a file the bundle does not serve stays absent), then
for ONE region:

1. records its prior bytes or absence with the merged C30 undo plan;
2. for every interruption point (after 1 .. n-1 of the region's n owned files are written) starts from the prior
   state, writes the upgrade only that far, checks that the region reads as ``mixed`` (a mixed pair or a new pointer
   with an old pair can never pass the gate), restores it with the C30 plan and checks the region is back to its prior
   bytes or absence;
3. applies the whole upgrade, checks it reads as ``upgrade`` (passes), then restores and checks again;

and after every step checks that the five untouched regions are byte-identical to the start. The upgrade is either a
directory of the region's new owned files (repo layout; a missing file = removed by the upgrade) or, by default, a
clearly SYNTHETIC marker upgrade (each prior JSON gains ``"rehearsal_upgrade": "C45 synthetic"``) that is never served.
It never touches a git checkout, bucket, deploy or any real release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

try:
    from scripts.relief import central_region_undo_plan as undo
except ImportError:  # run as a script: the sibling module
    import central_region_undo_plan as undo

SCHEMA = 'central-preview-recovery/1'
SYNTHETIC_KEY = 'rehearsal_upgrade'
SYNTHETIC_VALUE = 'C45 synthetic'
# Served URL in the six-region bundle for each C30 owned repo path; catalog/depth-contours/* is not served.
SERVED = (
    ('catalog/relief/{r}.json', '/catalog/relief/{r}.json'),
    ('dist/regions/{r}/depth-contours.geojson', '/regions/{r}/depth-contours.geojson'),
    ('dist/regions/{r}/depth-contours-overview.geojson', '/regions/{r}/depth-contours-overview.geojson'),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _version(data: bytes | None) -> str | None:
    """sha256 of a file's bytes, None for absence."""
    return None if data is None else _sha(data)


def _write(tree: Path, rel: str, data: bytes | None) -> None:
    path = undo._walk_safe(tree, rel)
    if data is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.c45')
    tmp.write_bytes(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def snapshot(tree: Path) -> dict[str, str | None]:
    """sha256 (or None for absence) of every owned file of all six regions."""
    out: dict[str, str | None] = {}
    for region in undo.REGIONS:
        for rel in undo.owned_paths(region):
            p = undo._walk_safe(tree, rel)
            out[rel] = _sha(p.read_bytes()) if p.exists() else None
    return out


def region_state(tree: Path, region: str, prior: dict[str, str | None], upgrade: dict[str, bytes | None]) -> str:
    """'prior' or 'upgrade' when every owned file is one consistent version; 'mixed' when they disagree; 'unknown'
    when any file is neither version. Only 'prior' and 'upgrade' may pass."""
    seen = set()
    for rel in undo.owned_paths(region):
        p = undo._walk_safe(tree, rel)
        have = _sha(p.read_bytes()) if p.exists() else None
        new = _version(upgrade[rel])
        tags = {t for t, v in (('prior', prior[rel]), ('upgrade', new)) if have == v}
        if not tags:
            return 'unknown'
        seen.add(frozenset(tags))
    both = frozenset({'prior', 'upgrade'})
    strict = {t for s in seen if s != both for t in s}  # a file equal in both versions says nothing
    if len(strict) > 1:
        return 'mixed'
    return next(iter(strict)) if strict else 'prior'


def passes(state: str) -> bool:
    return state in ('prior', 'upgrade')


def _refuse_checkout_destination(dest: Path, what: str) -> Path:
    """Refuse a destination that is, or sits inside, a git checkout, BEFORE anything is created there.

    ``dest`` need not exist yet: symlinks in its existing prefix are resolved, then it and every ancestor is checked
    for a ``.git`` (lexists: a dangling link still marks a checkout)."""
    resolved = dest.absolute().resolve()
    for folder in (resolved, *resolved.parents):
        if os.path.lexists(folder / '.git'):
            raise ValueError(f'refusing a {what} inside a git checkout (nothing was written): {dest}')
    return resolved


def build_tree(bundle_path: Path, tree: Path) -> dict:
    """Lay the six regions' owned files from the pinned bundle into a NEW disposable tree."""
    raw = bundle_path.read_bytes()
    bundle = json.loads(raw)
    if sorted(bundle.get('regions', {})) != sorted(undo.REGIONS):
        raise ValueError('bundle is not the six Central regions')
    if tree.exists():
        raise ValueError(f'tree must be new: {tree}')
    _refuse_checkout_destination(tree, 'tree')  # before mkdir or the marker file: a checkout is never written to
    tree.mkdir(parents=True)
    (tree / undo.MARKER).write_text(undo.MARKER_TEXT + '\n', encoding='utf-8')
    undo._require_disposable(tree)  # refuses a tree inside a checkout before anything is laid down
    laid = 0
    for region in undo.REGIONS:
        served = bundle['regions'][region].get('served', {})
        for rel_t, url_t in SERVED:
            rel, url = rel_t.format(r=region), url_t.format(r=region)
            if rel not in undo.owned_paths(region):
                if url in served:
                    raise ValueError(f'bundle serves {url} for a region that cannot own it')
                continue
            pin = served.get(url)
            if pin is None:
                continue  # honest absence
            data = Path(pin['file']).read_bytes()
            if _sha(data) != pin['sha256']:
                raise ValueError(f'bundle bytes changed: {url}')
            _write(tree, rel, data)
            laid += 1
    return {'bundle_sha256': _sha(raw), 'files_laid': laid}


def synthetic_upgrade(tree: Path, region: str) -> dict[str, bytes | None]:
    """Marker upgrade: each present owned JSON gains a top-level synthetic key; absent files stay absent."""
    out: dict[str, bytes | None] = {}
    for rel in undo.owned_paths(region):
        p = undo._walk_safe(tree, rel)
        if not p.exists():
            out[rel] = None
            continue
        doc = json.loads(p.read_bytes())
        if not isinstance(doc, dict) or SYNTHETIC_KEY in doc:
            raise ValueError(f'cannot mark a synthetic upgrade on {rel}')
        doc[SYNTHETIC_KEY] = SYNTHETIC_VALUE
        out[rel] = (json.dumps(doc, separators=(',', ':')) + '\n').encode('utf-8')
    return out


def upgrade_from_dir(source: Path, region: str) -> dict[str, bytes | None]:
    source = undo._real_dir(source, 'upgrade directory')
    out: dict[str, bytes | None] = {}
    for rel in undo.owned_paths(region):
        p = undo._walk_safe(source, rel)
        out[rel] = p.read_bytes() if p.exists() else None
    extra = {q.relative_to(source).as_posix() for q in source.rglob('*') if q.is_file()} - set(undo.owned_paths(region))
    if extra:
        raise ValueError(f'upgrade directory names files this region cannot own: {sorted(extra)}')
    return out


def rehearse(tree: Path, region: str, plan_dir: Path, upgrade: dict[str, bytes | None]) -> dict:
    tree = undo._require_disposable(tree)
    owned = undo.owned_paths(region)
    start = snapshot(tree)
    prior = {rel: start[rel] for rel in owned}
    new = {rel: _version(upgrade[rel]) for rel in owned}
    changed = [rel for rel in owned if prior[rel] != new[rel]]
    if not changed:
        raise ValueError('the upgrade is identical to the prior state: nothing to rehearse')
    doc = undo.make_plan(tree, region, plan_dir)
    plan_file = plan_dir / 'undo-plan.json'
    others = [rel for rel in start if rel not in owned]
    steps: list[dict] = []

    def check(name: str, apply_n: int, expect: str) -> None:
        for rel in owned[:apply_n]:
            _write(tree, rel, upgrade[rel])
        state = region_state(tree, region, prior, upgrade)
        row = {'step': name, 'written': apply_n, 'state': state, 'passes': passes(state)}
        now = snapshot(tree)
        row['untouched_ok'] = all(now[rel] == start[rel] for rel in others)
        result = undo.restore(plan_file, tree)
        after = snapshot(tree)
        row['restored_state'] = region_state(tree, region, prior, upgrade)
        row['restored_exact'] = after == start
        row['restore_actions'] = [a['action'] for a in result['actions']]
        row['ok'] = (state == expect and row['untouched_ok'] and row['restored_exact']
                     and row['restored_state'] == 'prior')
        steps.append(row)

    for k in range(1, len(owned)):
        # An interruption is a distinct partial state only when it has written a changed file and left one unwritten.
        if not (set(changed) & set(owned[:k]) and set(changed) & set(owned[k:])):
            continue
        check(f'interrupted after {k}/{len(owned)}', k, 'mixed')
    check('complete upgrade', len(owned), 'upgrade')
    end = snapshot(tree)
    return {'schema': SCHEMA, 'region': region, 'kind': undo.kind(region), 'plan_sha256': doc['plan_sha256'],
            'prior': prior, 'upgrade': new,
            'untouched_regions': sorted({r for r in undo.REGIONS if r != region}), 'untouched_files': len(others),
            'steps': steps, 'final_exact': end == start,
            'ok': bool(steps) and all(s['ok'] for s in steps) and end == start}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bundle', required=True, type=Path, help='pinned six-region preview bundle (BUNDLE.json)')
    parser.add_argument('--region', required=True, choices=undo.REGIONS)
    parser.add_argument('--work', required=True, type=Path, help='new directory outside any git checkout')
    parser.add_argument('--upgrade', type=Path, help="directory of the region's new owned files (repo layout)")
    parser.add_argument('--receipt', type=Path, help='write the receipt JSON here (must be new)')
    args = parser.parse_args(argv)
    try:
        work = args.work.absolute()
        if work.exists():
            raise ValueError(f'work directory must be new: {work}')
        # Validate every destination before creating anything (work, tree, marker, receipt).
        _refuse_checkout_destination(work, 'work directory')
        if args.receipt:
            receipt_path = args.receipt.absolute()
            if os.path.lexists(receipt_path):
                raise ValueError(f'receipt must be new: {receipt_path}')
            _refuse_checkout_destination(receipt_path, 'receipt file')
            if not receipt_path.parent.is_dir():
                raise ValueError(f'receipt directory must already exist: {receipt_path.parent}')
        work.mkdir(parents=True)
        laid = build_tree(args.bundle, work / 'tree')
        tree = work / 'tree'
        upgrade = upgrade_from_dir(args.upgrade, args.region) if args.upgrade else synthetic_upgrade(tree, args.region)
        receipt = rehearse(tree, args.region, work / 'plan', upgrade)
        receipt.update(laid, synthetic_upgrade=args.upgrade is None,
                       scope='C45 local disposable rehearsal; not a deploy, bucket, checkout or release')
        blob = json.dumps(receipt, indent=2, sort_keys=True) + '\n'
        if args.receipt:
            with open(args.receipt, 'x', encoding='utf-8') as handle:
                handle.write(blob)
        print(blob, end='')
        print(f"{'PASS' if receipt['ok'] else 'HOLD'} {args.region} {len(receipt['steps'])} steps; "
              f"untouched {receipt['untouched_files']} files; receipt sha256 {_sha(blob.encode())}")
        return 0 if receipt['ok'] else 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
