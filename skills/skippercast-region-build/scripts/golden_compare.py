#!/usr/bin/env python3
"""Golden case: compare a run's candidate/<id>.geojson with the committed catalog file, features and provenance.

Stdlib only and read-only. Prints one JSON line (key names, counts and hashes, never values). Exit 0 only for
verdict `equal`, 1 for any difference, 2 on refusal (one `golden_compare: <reason>` line on stderr).
"""
import argparse, hashlib, json, os, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SLUG = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')


class Refused(Exception):
    pass


def load(path, label):
    raw = path.read_bytes()
    try:
        obj = json.loads(raw)
    except ValueError:
        raise Refused(f'{label} is not valid JSON') from None
    if not isinstance(obj, dict) or not isinstance(obj.get('features'), list):
        raise Refused(f'{label} is not a JSON object with a features list')
    return raw, obj


def compare(region_id, run, catalog_root):
    if not SLUG.fullmatch(region_id or ''):
        raise Refused(f'region id must match ^[a-z0-9]+(-[a-z0-9]+)*$: {region_id!r}')
    folder, repo = Path(os.path.realpath(run)), Path(os.path.realpath(REPO))
    if folder == repo or repo in folder.parents:
        raise Refused(f'--run must be outside the repository: {folder}')
    candidate = folder / 'candidate' / f'{region_id}.geojson'
    if not candidate.is_file():
        raise Refused('no candidate output (held or unbuilt run)')
    if folder not in Path(os.path.realpath(candidate)).parents:
        raise Refused('candidate resolves outside the run folder')
    catalog = Path(catalog_root) / f'{region_id}.geojson'
    if not catalog.is_file():
        raise Refused(f'catalog file missing: {catalog.name}')
    cand_raw, cand = load(candidate, 'candidate')
    cat_raw, cat = load(catalog, 'catalog')
    cp, kp = (o.get('provenance') if isinstance(o.get('provenance'), dict) else {} for o in (cand, cat))
    prov = {'added': sorted(set(cp) - set(kp)), 'removed': sorted(set(kp) - set(cp)),
            'changed': sorted(k for k in set(cp) & set(kp) if cp[k] != kp[k])}
    top = sorted(k for k in (set(cand) | set(cat)) - {'features', 'provenance'}
                 if k not in cand or k not in cat or cand[k] != cat[k])
    hashes = {name: hashlib.sha256(json.dumps(o['features'], separators=(',', ':')).encode()).hexdigest()
              for name, o in (('candidate', cand), ('catalog', cat))}
    features_equal = hashes['candidate'] == hashes['catalog']
    verdict = 'features-differ' if not features_equal else 'provenance-only' if any(prov.values()) or top else 'equal'
    return {'region_id': region_id, 'verdict': verdict, 'bytes_equal': cand_raw == cat_raw,
            'features_equal': features_equal, 'feature_counts': [len(cand['features']), len(cat['features'])],
            'features_sha256': hashes, 'provenance': prov, 'top_level_changed': top}


def main(argv=None, catalog_root=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('region_id')
    parser.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    try:
        report = compare(args.region_id, args.run, catalog_root or REPO / 'catalog/depth-contours')
    except (Refused, OSError) as exc:
        print(f'golden_compare: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report['verdict'] == 'equal' else 1


if __name__ == '__main__':
    sys.exit(main())
