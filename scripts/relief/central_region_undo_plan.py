#!/usr/bin/env python3
"""Per-region undo plan for the six Central Coast data PRs (Cdata1-6).

``plan`` reads the PRIOR state (exact bytes or absence) of the files one Central
region's data PR may own and records it. ``restore`` puts that state back into a
DISPOSABLE tree only. Neither command can touch a git checkout, a bucket, a
mount point, a symlinked path or any file outside the one region's exact set.

The owned set is fixed here, not read from the plan: a plan that names any other
path (a neighbor region, a traversal, an extra file) is refused. Restoring one
region leaves every other region's owned files byte-identical (checked before
and after). This tool never applies a release; it only describes how to undo one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

if __name__ == '__main__':
    sys.dont_write_bytecode = True

SCHEMA = 'central-region-undo-plan/1'
MARKER = '.central-undo-disposable'
MARKER_TEXT = 'central-region-undo-disposable/1'

# Same six regions as central_stage_handoff.CENTRAL_RELEASES; kept literal so this
# generator has no import side effects. A test pins the two lists together.
CONTOUR_REGIONS = (
    'big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon', 'point-arguello-conception',
)
TERRAIN_ONLY_REGIONS = ('monterey-point-sur', 'santa-cruz-monterey-bay')
REGIONS = CONTOUR_REGIONS + TERRAIN_ONLY_REGIONS


def owned_paths(region: str) -> tuple[str, ...]:
    """The exact repo-relative files one region's data PR may write (Cdata plan rows)."""
    if region in TERRAIN_ONLY_REGIONS:
        return (f'catalog/relief/{region}.json',)
    if region in CONTOUR_REGIONS:
        return (
            f'catalog/relief/{region}.json',
            f'catalog/depth-contours/{region}.geojson',
            f'dist/regions/{region}/depth-contours.geojson',
            f'dist/regions/{region}/depth-contours-overview.geojson',
        )
    raise ValueError(f'not a Central release region: {region!r}')


def kind(region: str) -> str:
    owned_paths(region)
    return 'terrain-only' if region in TERRAIN_ONLY_REGIONS else 'terrain+contours'


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(doc: dict) -> bytes:
    return (json.dumps(doc, indent=2, sort_keys=True) + '\n').encode('utf-8')


def _plan_digest(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != 'plan_sha256'}
    return _sha256(_canonical(body))


def _real_dir(path: Path, what: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f'{what} must be a real directory, not a symlink: {path}')
    return path.resolve()


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def _walk_safe(tree: Path, rel: str) -> Path:
    """Join ``rel`` under ``tree`` refusing traversal and any symlink on the way."""
    if not rel or rel.startswith('/') or '\\' in rel or any(p in ('', '.', '..') for p in rel.split('/')):
        raise ValueError(f'unsafe path: {rel!r}')
    cur = tree
    for part in rel.split('/'):
        cur = cur / part
        if cur.is_symlink():
            raise ValueError(f'symlink on owned path: {rel}')
    if cur.exists() and not cur.is_file():
        raise ValueError(f'owned path is not a regular file: {rel}')
    return cur


def _absent_parents(tree: Path, rel: str) -> list[str]:
    out, parts = [], rel.split('/')[:-1]
    for i in range(1, len(parts) + 1):
        if not (tree / '/'.join(parts[:i])).exists():
            out.append('/'.join(parts[:i]))
    return out


def make_plan(tree: Path, region: str, out: Path) -> dict:
    tree = _real_dir(tree, 'tree')
    out = out.absolute()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f'plan directory must be new or empty: {out}')
    if _inside(out.resolve(), tree):
        raise ValueError('plan directory must be outside the tree being described')
    rows, absent_dirs = [], set()
    out.mkdir(parents=True, exist_ok=True)
    for rel in owned_paths(region):
        src = _walk_safe(tree, rel)
        if src.exists():
            data = src.read_bytes()
            dst = out / 'prior' / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            rows.append(dict(path=rel, state='present', sha256=_sha256(data), bytes=len(data),
                             mode=format(src.stat().st_mode & 0o777, '04o'), prior=f'prior/{rel}'))
        else:
            rows.append(dict(path=rel, state='absent'))
            absent_dirs.update(_absent_parents(tree, rel))
    doc = dict(schema=SCHEMA, region=region, kind=kind(region), paths=rows,
               absent_parent_dirs=sorted(absent_dirs, key=lambda d: (-d.count('/'), d)))
    doc['plan_sha256'] = _plan_digest(doc)
    (out / 'undo-plan.json').write_bytes(_canonical(doc))
    return doc


def load_plan(plan_file: Path) -> tuple[dict, Path]:
    plan_file = plan_file.absolute()
    if plan_file.is_symlink() or not plan_file.is_file():
        raise ValueError('plan must be a regular file')
    try:
        doc = json.loads(plan_file.read_bytes())
    except ValueError as exc:
        raise ValueError(f'plan is not JSON: {exc}') from None
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        raise ValueError('not a central-region-undo-plan/1 document')
    region = doc.get('region')
    if not isinstance(region, str):
        raise ValueError('plan has no region')
    expected = owned_paths(region)  # raises for an unknown region
    if doc.get('kind') != kind(region):
        raise ValueError('plan kind does not match the region')
    if doc.get('plan_sha256') != _plan_digest(doc):
        raise ValueError('plan digest mismatch (edited plan)')
    rows = doc.get('paths')
    if not isinstance(rows, list) or tuple(r.get('path') for r in rows if isinstance(r, dict)) != expected \
            or len(rows) != len(expected):
        raise ValueError('plan paths are not exactly this region\'s owned set (neighbor or extra path refused)')
    base = plan_file.parent
    for row in rows:
        if row.get('state') == 'absent':
            if set(row) != {'path', 'state'}:
                raise ValueError(f'absent row carries extra fields: {row["path"]}')
        elif row.get('state') == 'present':
            if row.get('prior') != f'prior/{row["path"]}':
                raise ValueError(f'prior bytes path is not the canonical one: {row["path"]}')
            prior = base / row['prior']
            if prior.is_symlink() or not prior.is_file():
                raise ValueError(f'prior bytes missing: {row["path"]}')
            data = prior.read_bytes()
            if _sha256(data) != row.get('sha256') or len(data) != row.get('bytes'):
                raise ValueError(f'prior bytes do not match the plan: {row["path"]}')
            mode = row.get('mode')
            if not isinstance(mode, str) or len(mode) != 4 or mode[0] != '0' or any(c not in '01234567' for c in mode):
                raise ValueError(f'plan mode is not a plain permission value: {row["path"]}')
        else:
            raise ValueError(f'bad row state for {row.get("path")}')
    allowed_dirs = {d for rel in expected for i in range(1, rel.count('/') + 1)
                    for d in ['/'.join(rel.split('/')[:i])]}
    if not set(doc.get('absent_parent_dirs', [])) <= allowed_dirs:
        raise ValueError('absent_parent_dirs names a directory outside this region\'s paths')
    return doc, base


def _require_disposable(tree: Path) -> Path:
    tree = _real_dir(tree, 'tree')
    for folder in (tree, *tree.parents):  # the tree itself or any ancestor being a checkout is refused
        if os.path.lexists(folder / '.git'):  # lexists: a dangling .git link still marks a checkout
            raise ValueError('refusing a git checkout or a tree inside one: restore works on disposable trees only')
    if os.path.ismount(tree) or tree == Path(tree.anchor) or tree == Path.home():
        raise ValueError('refusing a mount point, filesystem root or home directory')
    marker = tree / MARKER
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding='utf-8').strip() != MARKER_TEXT:
        raise ValueError(f'tree is not marked disposable (create {MARKER} containing {MARKER_TEXT!r})')
    return tree


def _neighbors(tree: Path, region: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for other in REGIONS:
        if other == region:
            continue
        for rel in owned_paths(other):
            p = _walk_safe(tree, rel)
            snap[rel] = _sha256(p.read_bytes()) if p.exists() else None
    return snap


def restore(plan_file: Path, tree: Path, *, dry_run: bool = False) -> dict:
    doc, base = load_plan(plan_file)
    region = doc['region']
    tree = _require_disposable(tree)
    if _inside(base.resolve(), tree):
        raise ValueError('plan directory must be outside the tree being restored')
    before = _neighbors(tree, region)
    actions = []
    targets = []
    for row in doc['paths']:  # preflight everything before any write
        dst = _walk_safe(tree, row['path'])
        targets.append((row, dst))
    for row, dst in targets:
        if row['state'] == 'present':
            have = _sha256(dst.read_bytes()) if dst.exists() else None
            same = have == row['sha256'] and dst.stat().st_mode & 0o777 == int(row['mode'], 8)
            actions.append(dict(path=row['path'], action='unchanged' if same else 'rewrite'))
        else:
            actions.append(dict(path=row['path'], action='remove' if dst.exists() else 'unchanged'))
    if not dry_run:
        for row, dst in targets:
            if row['state'] == 'present':
                data = (base / row['prior']).read_bytes()
                mode = int(row['mode'], 8)
                if dst.exists() and dst.read_bytes() == data and dst.stat().st_mode & 0o777 == mode:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                # mkstemp creates a new file exclusively (O_EXCL) and never follows a pre-planted link.
                fd, name = tempfile.mkstemp(dir=dst.parent, prefix=f'.{dst.name}.undo-')
                try:
                    with os.fdopen(fd, 'wb') as handle:
                        handle.write(data)
                        os.fchmod(handle.fileno(), mode)
                    os.replace(name, dst)
                except BaseException:
                    if os.path.lexists(name):
                        os.unlink(name)
                    raise
            elif dst.exists():
                dst.unlink()
        for rel in doc['absent_parent_dirs']:  # deepest first; only directories this plan saw absent
            d = tree / rel
            if d.is_dir() and not d.is_symlink() and not any(d.iterdir()):
                d.rmdir()
        after = _neighbors(tree, region)
        if after != before:
            raise RuntimeError('neighbor region files changed during restore (should be impossible)')
        for row in doc['paths']:
            p = tree / row['path']
            if row['state'] == 'present':
                if not p.is_file() or _sha256(p.read_bytes()) != row['sha256'] or p.stat().st_mode & 0o777 != int(row['mode'], 8):
                    raise RuntimeError(f'restore did not reproduce prior bytes and mode: {row["path"]}')
            elif p.exists():
                raise RuntimeError(f'restore left a file that was absent before: {row["path"]}')
    return dict(region=region, kind=doc['kind'], dry_run=dry_run, actions=actions,
                neighbors_checked=len(before), neighbors_unchanged=True, plan_sha256=doc['plan_sha256'])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan', help='record prior bytes/absence of one region (read-only on the tree)')
    p.add_argument('--tree', required=True, type=Path)
    p.add_argument('--region', required=True)
    p.add_argument('--out', required=True, type=Path, help='new plan directory, outside the tree')
    r = sub.add_parser('restore', help='restore one region into a disposable tree')
    r.add_argument('--plan', required=True, type=Path, help='undo-plan.json')
    r.add_argument('--tree', required=True, type=Path)
    r.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'plan':
            doc = make_plan(args.tree, args.region, args.out)
            print(json.dumps(dict(region=doc['region'], kind=doc['kind'], plan_sha256=doc['plan_sha256'],
                                  present=sum(r['state'] == 'present' for r in doc['paths']),
                                  absent=sum(r['state'] == 'absent' for r in doc['paths'])), indent=2))
        else:
            print(json.dumps(restore(args.plan, args.tree, dry_run=args.dry_run), indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
