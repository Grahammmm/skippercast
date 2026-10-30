#!/usr/bin/env python3
"""Region publish: the five-point publish rule for a reviewed region-build run. A pass copies the candidate into a repo work tree,
proves `platform.build` reproduces itself and drafts PUBLISH.md; a failure writes the held reason to PUBLISH.md and LEDGER.csv and leaves
the work tree byte-unchanged. File edits only, no commits or deploys. Exit 0 ready, 1 held or refused, 2 not restored. Not acceptance.
"""
import argparse, csv, functools, hashlib, io, json, os, re, shutil, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
from skippercast.platform.contracts import load_catalogs, load_region  # noqa: E402

HEADER = ['region_id', 'stage', 'state', 'held_reason', 'last_run', 'build_sha256', 'review_verdict', 'reviewer_runtime', 'pr', 'published_at']
NEXT = {'source-candidate': 'noaa/source review owner', 'source-not-approved': 'source review owner', 'region-draft': 'PC-4b (t_6dd54ee3)',
        'review': 're-review by another family', 'no-publishable-output': 'see BUILD.json not_built'}
sha = lambda data: hashlib.sha256(data).hexdigest()
SKIP = {'.git', 'node_modules', '.venv', '__pycache__'}
default_run = functools.partial(subprocess.run, capture_output=True, text=True)
default_loader = lambda root, rid: (load_region(rid, root=root), load_catalogs(root)[1])

class Held(Exception): """A failed publish rule: args are (held_reason, detail)."""

class NotRestored(Exception): pass

def need(ok, reason, detail):
    if not ok:
        raise Held(reason, detail)

def snapshot(repo, keep=None):
    """sha256 of every work-tree file (not .git, caches, top-level var/); `keep` also collects the bytes of files outside dist/."""
    out = {}
    for top, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not (top == str(repo) and d == 'var'))
        for p in (Path(top, f) for f in sorted(files) if Path(top, f).is_file()):
            rel, data = str(p.relative_to(repo)), p.read_bytes()
            out[rel] = sha(data)
            if keep is not None and not rel.startswith('dist/'):
                keep[rel] = data
    return out

def put(dest, source=None, data=None):
    tmp = dest.with_name(dest.name + '.tmp')
    shutil.copyfile(source, tmp) if source else tmp.write_bytes(data)
    os.replace(tmp, dest)

def parse_review(folder):
    info = {}
    for line in (folder / 'REVIEW.md').read_text().splitlines() if (folder / 'REVIEW.md').is_file() else []:
        if m := re.fullmatch(r'(Build-SHA256|Reviewer-Runtime|Reviewer-Family):(.*)', line):
            info[m[1]] = m[2].strip()
        elif m := re.fullmatch(r'Overall:\s*(\S*)\s*', line):
            info['overall'] = m[1]
        elif line.startswith('|') and (cells := [c.strip() for c in line.strip().strip('|').split('|')] + [''])[0] == 'visual':
            info.setdefault('visual', cells[1])
    return info or None

def check(folder, build, review, region, sources, python, run):
    """The rules in order; raises Held for the first failure. Returns the candidate collection."""
    rid, rel = build['region_id'], f"candidate/{build['region_id']}.geojson"
    found = [o for o in build.get('outputs') or [] if o.get('path') == rel]
    need(len(found) == 1, 'no-publishable-output', f'BUILD.json lists {len(found)} outputs for {rel}')
    data = (folder / rel).read_bytes() if (folder / rel).is_file() else b''
    need(sha(data) == found[0].get('sha256'), 'build-output-changed', f'{rel} differs from the BUILD.json sha256')
    candidate = json.loads(data)
    prov, feats = candidate.get('provenance') or {}, candidate.get('features') or []
    need(not any(isinstance(p, dict) and 'publication_held' in p for p in [candidate, prov, *feats, *(f.get('properties') or {} for f in feats)]),
         'publication-held', 'the candidate carries a publication_held key')
    for s in prov.get('sources') or []:
        status = (sources.get(s.get('source_id')) or {}).get('review_status')
        need(status == 'approved', f"{'source-candidate' if status == 'candidate' else 'source-not-approved'}:{s.get('source_id')}", f'catalog status {status}')
    status = region.get('status')
    need(status in ('active', 'preview'), 'region-draft' if status == 'draft' else f'region-status:{status}', f'region status {status}')
    # Match region_build.py's identity over every output, not just the candidate.
    pairs = json.dumps(sorted([o['path'], o['sha256']] for o in build['outputs']), separators=(',', ':'))
    need(sha(pairs.encode()) == build['build_sha256'], 'build-sha-mismatch', 'BUILD.json build_sha256 differs from its canonical output identity')
    need(review is not None, 'review-missing', 'no REVIEW.md in the run folder')
    need(review.get('Build-SHA256') == build['build_sha256'], 'review-sha-mismatch', 'REVIEW.md Build-SHA256 differs from BUILD.json')
    need(review.get('Reviewer-Family', '').strip().casefold() != str(build['run']['author_family']).strip().casefold(), 'review-family',
         'the reviewer family equals the builder family')
    need(review.get('overall') == 'PASS' and review.get('visual') != 'RETURN', 'review-return', f"Overall {review.get('overall')}, visual {review.get('visual')}")
    done = run([python, str(REPO / 'skills/skippercast-region-review/scripts/region_review.py'), '--check', str(folder)])
    need(done.returncode == 0 and done.stdout.strip() == f'REVIEW OK {rid} PASS', 'review-invalid', 'region_review.py --check did not print REVIEW OK <id> PASS')
    return candidate

def reproduce(repo, rid, source, python, run):
    """Copy the candidate in and build twice; returns (tree before, tree after). On any failure restore the tree, then hold."""
    rel = f'catalog/depth-contours/{rid}.geojson'
    target, saved = repo / rel, {}
    before = snapshot(repo, saved)

    def build():
        done = run([python, '-m', 'skippercast.platform.build'], cwd=repo, env={**os.environ, 'PYTHONPATH': str(repo / 'src')})
        need(done.returncode == 0, 'build-not-reproducible', f'platform.build exited {done.returncode}')
        return snapshot(repo)
    try:
        put(target, source=source)
        first, second = build(), build()
        need(first == second and (repo / 'dist/regions' / rid / 'depth-contours.geojson').is_file(), 'build-not-reproducible',
             'two builds differ, or dist depth-contours.geojson is missing')
        touched = sorted(p for p in before.keys() | second.keys() if before.get(p) != second.get(p) and p != rel and not p.startswith('dist/'))
        need(not touched, f'build-touched:{touched[0] if touched else "-"}', 'platform.build changed a file outside the catalog file and dist')
    except BaseException:
        def restore():
            now = snapshot(repo)
            for p in now.keys() - before.keys():
                (repo / p).unlink()
            for p, data in saved.items():
                if now.get(p) != before[p]:
                    (repo / p).parent.mkdir(parents=True, exist_ok=True)
                    put(repo / p, data=data)
        try:
            restore()
            try:
                build()  # regenerate dist from the restored catalog; the builder may touch other files again, so restore once more
            except Held:
                pass
            restore()
            if snapshot(repo) != before:
                raise NotRestored()
        except OSError:
            raise NotRestored()
        raise
    return before, second

def update_ledger(ledger, rid, changes):
    """Check the plan header and the region's row; with `changes` rewrite only that row (atomic), other lines byte-identical."""
    lines = ledger.read_text().splitlines(keepends=True) if ledger.is_file() else []
    if not lines or next(csv.reader([lines[0]])) != HEADER:
        raise ValueError(f'LEDGER.csv missing or its header differs from the plan: {ledger.name}')
    n = next((i for i, line in enumerate(lines) if i and next(csv.reader([line]), [''])[0] == rid), None)
    if n is None:
        raise ValueError(f'missing LEDGER.csv row {rid} (operator step O5)')
    row, out = dict(zip(HEADER, next(csv.reader([lines[n]])) + [''] * len(HEADER))) | (changes or {}), io.StringIO()
    csv.writer(out, lineterminator=lines[n][len(lines[n].rstrip('\r\n')):]).writerow([row[k] for k in HEADER])
    lines[n] = out.getvalue()
    changes and put(ledger, data=''.join(lines).encode())

def pass_text(rid, name, build, candidate, region, sources, review, before, after, repo):
    prov, family, listed = candidate['provenance'], review['Reviewer-Family'], candidate['provenance']['sources']
    label = lambda s: sources[s['source_id']].get('name', s['source_id'])
    changed = [f'- {p} {after[p]}' for p in sorted(after) if before.get(p) != after[p]] + [f'- {p} deleted' for p in sorted(before) if p not in after]
    row = any(line.startswith('|') and region['name'] in line for line in (repo / 'README.md').read_text().splitlines())
    return '\n'.join([f'# PUBLISH {rid} {name}',
        "Machine-valid ≠ accepted. Merge only under G's standing approval (required CI green on the exact head + independent review).", '',
        '1. Sources: ' + ', '.join(f"{s['source_id']} (approved)" for s in listed), f"2. Region status: {region['status']}",
        f"3. REVIEW.md PASS by {family} ({review.get('Reviewer-Runtime', '')}); builder family {build['run']['author_family']}; Build-SHA256 {build['build_sha256']}",
        '4. publication_held: absent', f'5. platform.build run twice, same tree hash; dist/regions/{rid}/depth-contours.geojson present', '',
        'Files changed:', *(changed or ['- none (no change: the candidate equals the committed file)']), '', '## PR body',
        f"Depth contours for {region['name']} ({rid}), run {name}.",
        *[f"- {label(s)} (`{s['source_id']}`): sha256 {s['sha256']}, survey_date {s['survey_date']}, vertical_datum {s['vertical_datum']}" for s in listed],
        f"sources_omitted: {json.dumps(prov['sources_omitted'], separators=(',', ':'))}", f"build_sha256: {build['build_sha256']}",
        f"Reviewer: {review.get('Reviewer-Runtime', '')} ({family}); {'phone capture not visually inspected' if review.get('visual') == 'not-visually-inspected' else 'visual ' + review.get('visual')}.", 'Not for navigation.', '', '## CHANGELOG line',
        f"- Depth contours for {region['name']} now come from reviewed survey data ({', '.join(map(label, listed))}); each keeps its declared datum and is not for navigation.",
        '', 'README: no change (the package row exists)' if row else f"README: draft row | {region['name']} | `{region['status']}` |"]) + '\n'

def publish(args, run, loader):
    folder, repo, ledger = (Path(os.path.realpath(os.path.expanduser(p))) for p in (args.run, args.repo, args.ledger))
    if any(repo == p or repo in p.parents for p in (folder, ledger)):
        raise ValueError('the run folder and the ledger must be outside --repo')
    if not (repo / '.git').exists() or not (repo / 'src/skippercast/platform/build.py').is_file() or (folder / 'PUBLISH.md').exists():
        raise ValueError('--repo is not a SkipperCast work tree, or PUBLISH.md already exists (never overwritten)')
    build = json.loads((folder / 'BUILD.json').read_text())
    rid, name, review = build['region_id'], folder.name, parse_review(folder)
    update_ledger(ledger, rid, None)
    region, sources = loader(repo, rid)
    fields = {'last_run': name, 'build_sha256': build.get('build_sha256', ''), 'reviewer_runtime': (review or {}).get('Reviewer-Runtime', '')}
    try:
        candidate = check(folder, build, review, region, sources, args.python, run)
        before, after = reproduce(repo, rid, folder / f'candidate/{rid}.geojson', args.python, run)
        text = pass_text(rid, name, build, candidate, region, sources, review, before, after, repo)
        changes, code = {'stage': 'publish', 'state': 'reviewed', 'held_reason': 'none', 'review_verdict': 'PASS (visual not inspected)' if review.get('visual') == 'not-visually-inspected' else 'PASS', **fields}, 0
    except Held as held:
        reason, detail = held.args
        action = NEXT.get(reason.split(':')[0]) or NEXT.get(reason.split('-')[0]) or 'operator inspects the run folder'
        text = f'# PUBLISH {rid} {name}\nHELD: {reason}\n{detail}\nNext: {action}\n'
        changes, code = {'state': 'held', 'held_reason': reason, 'review_verdict': (review or {}).get('overall', ''), **fields}, 1
    (folder / 'PUBLISH.md').write_text(text)
    update_ledger(ledger, rid, changes)
    print(f"{'PUBLISH READY' if code == 0 else 'HELD ' + changes['held_reason']} {rid}")
    return code

def main(argv=None, run=default_run, loader=default_loader):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', nargs='?')
    parser.add_argument('--ledger', default='~/agent-work/skippercast/regions/LEDGER.csv')
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--record-pr', metavar='RUN', help='ledger only: set pr (and published when --published-at is given)')
    for flag in ('--repo', '--pr', '--published-at'):
        parser.add_argument(flag)
    args = parser.parse_args(argv)
    try:
        if args.record_pr and (args.pr or '').isdigit() and re.fullmatch(r'(\d{4}-\d{2}-\d{2})?', args.published_at or ''):
            rid = json.loads((Path(args.record_pr) / 'BUILD.json').read_text())['region_id']
            update_ledger(Path(os.path.expanduser(args.ledger)), rid, {'pr': args.pr, **({'state': 'published', 'published_at': args.published_at} if args.published_at else {'state': 'reviewed'})})
            return 0
        if args.run and args.repo and not args.record_pr:
            return publish(args, run, loader)
        raise ValueError('usage: <run> --repo <worktree>  |  --record-pr <run> --pr <number> [--published-at YYYY-MM-DD]')
    except NotRestored:
        print('region_publish: REPO NOT RESTORED (inspect the work tree)', file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as err:
        print(f'region_publish: {err}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
