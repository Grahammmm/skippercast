"""Private, expiring discovery decisions; never source qualification or coverage.

The checkpoint avoids repeating a completed source test on identical physical
inputs. Changed inputs, expiry or invalid evidence return a lead to the queue.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from skippercast.platform.contracts import atomic_json, read_json
from .io import sha256

RELATIVE = 'var/seafloor/source-review/checkpoint.json'
OUTCOMES = {'no-incremental-support', 'no-valid-shallow-support',
            'already-qualified', 'needs-original-input', 'access-failed'}
MAX_BYTES = 1_000_000
MAX_EVIDENCE_BYTES = 64_000
TTL = timedelta(days=7)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def context(root, manifest):
    """Conservative whole-catalog identity; legal-only refreshes do not reopen it."""
    root = Path(root)
    return digest({'surveys': manifest['surveys'], 'files': {
        name: sha256(root/name) for name in (
            'catalog/reaches.json', 'catalog/habitat-rules.json',
            'requirements-survey.txt', 'dist/data/atlas.json',
            'var/seafloor/reference/cells.json')},
        'method': {p.relative_to(Path(__file__).parent).as_posix(): sha256(p)
                   for p in sorted(Path(__file__).parent.rglob('*.py'))}})


def load(root):
    path = Path(root)/RELATIVE
    if not path.exists():
        return {'version': 1, 'reviews': []}
    if (path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve())
            or path.stat().st_size > MAX_BYTES):
        raise ValueError('Unsafe source-review checkpoint')
    data = read_json(path)
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('reviews'), list):
        raise ValueError('Invalid source-review checkpoint')
    return data


def record(root, manifest, source_id, reach_ids, outcome, evidence, *, now, note):
    root = Path(root).resolve()
    source = next((r for r in manifest['surveys'] if r['id'] == source_id), None)
    reaches = {r['id'] for r in read_json(root/'catalog/reaches.json')['reaches']}
    if (not source or source['status'] not in {'candidate', 'hold'}
            or not reach_ids or not set(reach_ids) <= reaches or outcome not in OUTCOMES
            or not isinstance(note, str) or not 1 <= len(note) <= 2000
            or now.tzinfo is None):
        raise ValueError('Invalid bounded source-review decision')
    relative = Path(evidence)
    path = root/relative
    if (relative.is_absolute() or '..' in relative.parts or path.is_symlink()
            or not relative.as_posix().startswith(('var/seafloor/', 'research/receipts/'))
            or not path.resolve().is_relative_to(root) or path.suffix != '.json'
            or path.stat().st_size > MAX_EVIDENCE_BYTES):
        raise ValueError('Unsafe source-review evidence')
    document = read_json(path)
    row = {'source_id': source_id, 'reach_ids': sorted(set(reach_ids)),
           'outcome': outcome, 'note': note, 'physical_context_sha256': context(root, manifest),
           'reviewed_at': now.isoformat(), 'expires_at': (now+TTL).isoformat(),
           'evidence': {'path': relative.as_posix(), 'raw_sha256': sha256(path),
                        'document_sha256': digest(document), 'document': document},
           'fishing_target': False, 'exportable': False, 'coverage_credit_km2': 0}
    state = load(root)
    state['reviews'] = [r for r in state['reviews'] if isinstance(r, dict)
                        and isinstance(r.get('source_id'), str)
                        and r['source_id'] != source_id] + [row]
    encoded = json.dumps(state, indent=2).encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError('Source-review checkpoint exceeds bounded size')
    if not (root/RELATIVE).resolve().is_relative_to(root):
        raise ValueError('Unsafe source-review checkpoint')
    atomic_json(root/RELATIVE, state, indent=2)
    return {key: row[key] for key in ('source_id', 'reach_ids', 'outcome', 'expires_at')}


def partition(root, manifest, queue, reach_ids, *, now=None):
    """Keep stale, incomplete or corrupt decisions actionable, without hiding them."""
    now = now or datetime.now(timezone.utc)
    try:
        state = load(root)
    except (ValueError, TypeError, OSError, json.JSONDecodeError):
        return queue, [], ['Invalid source-review checkpoint; all leads remain actionable.']
    if not state['reviews']:
        return queue, [], []
    current = context(root, manifest)
    reviews = {r['source_id']: r for r in state['reviews']
               if isinstance(r, dict) and isinstance(r.get('source_id'), str)}
    active, deferred = [], []
    for item in queue:
        row = reviews.get(item['id'], {})
        try:
            reviewed = datetime.fromisoformat(row['reviewed_at'])
            expires = datetime.fromisoformat(row['expires_at'])
            good = (row['outcome'] in OUTCOMES and reviewed <= now < expires
                    and expires-reviewed <= TTL
                    and row['physical_context_sha256'] == current
                    and set(reach_ids) <= set(row['reach_ids'])
                    and row['evidence']['document_sha256'] == digest(row['evidence']['document'])
                    and isinstance(row['note'], str) and 1 <= len(row['note']) <= 2000
                    and row['fishing_target'] is False and row['exportable'] is False
                    and row['coverage_credit_km2'] == 0)
        except (KeyError, ValueError, TypeError):
            good = False
        if good:
            deferred.append({**item, 'review_outcome': row['outcome'],
                             'review_note': row['note'], 'expires_at': row['expires_at']})
        else:
            active.append(item)
    return active, deferred, []
