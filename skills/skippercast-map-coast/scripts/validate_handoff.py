#!/usr/bin/env python3
"""Validate a private v2 handoff and select completed slices; never execute its commands."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import jsonschema

SCHEMA = Path(__file__).resolve().parents[1] / 'assets/render-handoff-v2.schema.json'


def read_json(path):
    def reject(value):
        raise ValueError('Nonfinite JSON value: ' + value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def descriptors(value):
    if isinstance(value, dict):
        if {'path','sha256','bytes','format'} <= value.keys():
            yield value
        else:
            for child in value.values():
                yield from descriptors(child)
    elif isinstance(value,list):
        for child in value:
            yield from descriptors(child)


def check_file(item, root, max_bytes):
    rel = Path(item['path'])
    path = (root / rel).resolve()
    if rel.is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError('Artifact escapes the supplied root')
    if item['bytes'] > max_bytes:
        raise ValueError('Artifact exceeds verification byte allowance')
    if path.stat().st_size != item['bytes']:
        raise ValueError('Artifact size mismatch: ' + item['path'])
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    if h.hexdigest() != item['sha256']:
        raise ValueError('Artifact hash mismatch: ' + item['path'])
    return path


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError('Duplicate ' + label)
    return set(values)



def acceptance_context(data, slice_record):
    """Bind all interpretation/loader/source metadata, excluding the receipt itself."""
    payload = {
        'schema_version': data['schema_version'],
        'scope_id': data['scope_id'],
        'upstream_revision': data['upstream_revision'],
        'slice': {k:v for k,v in slice_record.items() if k != 'review_receipt'},
        'sources': sorted((source for source in data['sources']
                           if source['id'] in slice_record['source_ids']), key=lambda x:x['id']),
    }
    encoded = json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()

def validate(data, root, *, now=None, max_bytes=50_000_000):
    jsonschema.Draft202012Validator(read_json(SCHEMA),
        format_checker=jsonschema.FormatChecker()).validate(data)
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    source_ids = unique([s['id'] for s in data['sources']], 'source IDs')
    slice_ids = unique([s['id'] for s in data['slices']], 'slice IDs')
    manifest = data['coverage_manifest']
    added, updated, removed = [unique(manifest[k],k) for k in ('added','updated','removed')]
    if added & updated or removed & (added | updated) or added | updated != slice_ids or removed & slice_ids:
        raise ValueError('Incremental IDs must be disjoint; added/updated identify exactly the supplied slices')
    if (updated or removed) and manifest['previous_sha256'] is None:
        raise ValueError('Incremental updates/removals need the previous manifest hash')
    selected = []
    seen_files = {}
    for s in data['slices']:
        if not set(s['source_ids']) <= source_ids:
            raise ValueError('Unknown source ID')
        west,south,east,north = s['coverage']['bbox']
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError('Invalid CRS84 bounds; split dateline-crossing slices')
        if s['coverage']['support_area_m2'] > s['coverage']['window_area_m2']:
            raise ValueError('Support cannot exceed its window')
        if s['habitat']['status'] in {'unassessed','provisional','rejected'} and s['habitat']['claims']:
            raise ValueError('Unaccepted habitat cannot assert accepted habitat claims')
        if s['habitat']['status'] == 'accepted' and (
                not s['habitat']['artifact'] or not s['habitat']['review_receipt']):
            raise ValueError('Accepted habitat needs its own artifact and review')
        for item in descriptors(s):
            prior = seen_files.get(item['path'])
            identity = (item['sha256'],item['bytes'])
            if prior is not None and prior != identity:
                raise ValueError('One path has conflicting identities')
            seen_files[item['path']] = identity
        if s['status'] == 'blocked':
            if not s['holds']:
                raise ValueError('Blocked slices must retain explicit holds')
            continue  # Missing blocked inputs remain references; never selected for display.
        if s['holds'] or any(s[k] is None for k in ('terrain','imagery','support_mask','review_receipt','consumer')):
            raise ValueError('Accepted slices need complete terrain, imagery, mask, review and loader')
        if s['coverage']['support_area_m2'] <= 0:
            raise ValueError('Accepted slice requires positive valid support')
        if s['confidence'] in {'unknown','low'} and not s['limitations']:
            raise ValueError('Low/unknown confidence requires explicit limitations')
        files = list(descriptors(s))
        for item in files:
            check_file(item,root,max_bytes)
        if s['habitat']['status'] == 'accepted':
            hreview = read_json(root / s['habitat']['review_receipt']['path'])
            if (hreview.get('scope') != 'fishing-habitat' or hreview.get('decision') != 'accepted'
                    or hreview.get('artifact_sha256') != s['habitat']['artifact']['sha256']
                    or set(hreview.get('claims',[])) != set(s['habitat']['claims'])):
                raise ValueError('Habitat claims need their own bound acceptance receipt')
        review = read_json(root / s['review_receipt']['path'])
        expected = {item['sha256'] for item in files if item is not s['review_receipt']}
        if (review.get('scope') != 'website-display' or review.get('decision') != 'accepted'
                or not review.get('reviewer') or set(review.get('artifact_sha256s',[])) != expected
                or review.get('acceptance_context_sha256') != acceptance_context(data,s)
                or set(review.get('source_ids',[])) != set(s['source_ids'])
                or any(review.get(k) is not True for k in
                       ('rights_accepted','restrictions_accepted','loader_accepted'))):
            raise ValueError('Exact artifact/source website-display acceptance required')
        expiry = datetime.fromisoformat(review['valid_until'].replace('Z','+00:00'))
        if expiry.tzinfo is None or expiry <= now:
            raise ValueError('Display/restriction acceptance expired or timezone missing')
        # A manifest/receipt is an attestation, not a new scientific or legal review.
        selected.append(s['id'])
    expected_status = 'READY' if selected and len(selected) == len(data['slices']) and not data['deferred'] else 'PARTIAL' if selected else 'BLOCKED'
    if data['status'] != expected_status:
        raise ValueError('Overall status disagrees with accepted slices and deferred work')
    return {'schema_version':2,'status':expected_status,'selected_slice_ids':selected,
            'blocked_slice_ids':[s['id'] for s in data['slices'] if s['status']=='blocked'],
            'deferred':data['deferred'],'publication_or_fishing_approval':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--context-for', help='Print a proposed acceptance digest; grants no approval')
    parser.add_argument('--max-file-bytes',type=int,default=50_000_000)
    args = parser.parse_args()
    try:
        if args.max_file_bytes <= 0:
            raise ValueError('Positive byte allowance required')
        data = read_json(args.manifest)
        if args.context_for:
            jsonschema.Draft202012Validator(read_json(SCHEMA),
                format_checker=jsonschema.FormatChecker()).validate(data)
            records = [s for s in data['slices'] if s['id'] == args.context_for]
            if len(records) != 1:
                raise ValueError('Select exactly one slice for review')
            result = {'slice_id':args.context_for,
                      'acceptance_context_sha256':acceptance_context(data,records[0]),
                      'approval':False}
        else:
            result = validate(data,args.root,max_bytes=args.max_file_bytes)
        print(json.dumps(result,indent=2))
        return 0
    except (ValueError,KeyError,TypeError,OSError,jsonschema.ValidationError) as error:
        parser.exit(2,str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
