"""Portable SC17C constructors for synthetic source-review checkpoints.

No product imports and no writes outside the root a caller passes in. Each
malformed variant is built from a genuine writer-shaped row, so ordinary
last-wins/non-finite JSON decoding would yield a deferring review. That makes
every variant a deciding case for the strict checkpoint decoder.
"""
import hashlib
import json
from pathlib import Path

MANIFEST = {'surveys': [{'id': 'tested', 'status': 'candidate'},
                        {'id': 'untested', 'status': 'candidate'}]}
QUEUE = ({'id': 'tested'}, {'id': 'untested'})
EVIDENCE = 'var/seafloor/tested/proof.json'
NOTE = 'Complete original grid compared against the current source set.'
OUTCOME = 'no-incremental-support'
WARNING = 'Invalid source-review checkpoint; all leads remain actionable.'

# name -> (kind, detail); see malformed() for how each is rendered.
MALFORMED = {
    'duplicate-reviews': ('top', '"version": 1, "reviews": [], "reviews": @ROWS@'),
    'duplicate-reviews-equal': ('top', '"version": 1, "reviews": @ROWS@, "reviews": @ROWS@'),
    'duplicate-reviews-escaped': ('top', '"version": 1, "reviews": [], "\\u0072eviews": @ROWS@'),
    'duplicate-version': ('top', '"version": 2, "version": 1, "reviews": @ROWS@'),
    'duplicate-outcome': ('row', ('"outcome": ', '"outcome": "approved", ')),
    'duplicate-outcome-equal': ('row', ('"outcome": ', '"outcome": "' + OUTCOME + '", ')),
    'duplicate-outcome-escaped': ('row', ('"outcome": ', '"\\u006futcome": "approved", ')),
    'duplicate-expiry': ('row', ('"expires_at": ', '"expires_at": "2000-01-01T00:00:00+00:00", ')),
    'duplicate-source-id': ('row', ('"source_id": ', '"source_id": "untested", ')),
    'duplicate-evidence-sha': ('row', ('"document_sha256": ', '"document_sha256": "stale", ')),
    'duplicate-evidence-sha-escaped': ('row', ('"document_sha256": ',
                                               '"document\\u005fsha256": "stale", ')),
    'duplicate-evidence-document': ('row', ('"document": {', '"document": {}, ')),
    'duplicate-document-field': ('row', ('"after_km2": ', '"after_km2": 2, ')),
    'nan': ('number', 'NaN'),
    'infinity': ('number', 'Infinity'),
    'negative-infinity': ('number', '-Infinity'),
    'overflow-positive': ('number', '1e999'),
    'overflow-negative': ('number', '-1e999'),
    'overflow-exponent': ('number', '12.5E+400'),
    'overflow-top-level': ('top', '"version": 1, "padding": 1e999, "reviews": @ROWS@'),
}
# Valid finite numbers in the private evidence document must still load.
FINITE = ('1.5', '-0.0', '1e300', '2.2250738585072014e-308', '123456789012345678901234567890')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def build_tree(root):
    """Writer-shaped synthetic catalog inputs, mirroring the original test setup."""
    root = Path(root)
    for name in ('catalog/habitat-rules.json', 'dist/data/atlas.json',
                 'var/seafloor/reference/cells.json'):
        write(root / name, json.dumps({'version': 1}))
    write(root / 'requirements-survey.txt', 'pinned science\n')
    write(root / 'catalog/reaches.json', json.dumps({'reaches': [{'id': 'r01'}, {'id': 'r02'}]}))
    write(root / EVIDENCE, json.dumps({'before_km2': 1, 'after_km2': 1, 'new_candidate_count': 0}))
    return root


def snapshot(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): (digest(p) if p.is_file() and not p.is_symlink()
                                             else ('link' if p.is_symlink() else 'dir'))
            for p in sorted(root.rglob('*'))}


def malformed(name, row, document_digest):
    """Raw checkpoint text for one variant built from a writer-produced row.

    document_digest is the product's own digest function, passed in so the
    marker in a number variant's document matches what partition recomputes.
    """
    kind, detail = MALFORMED[name]
    if kind == 'top':
        return '{' + detail.replace('@ROWS@', json.dumps([row])) + '}'
    if kind == 'row':
        anchor, extra = detail
        text = json.dumps(row)
        if text.count(anchor) != 1:
            raise ValueError(f'constructor anchor is not unique: {anchor}')
        return '{"version": 1, "reviews": [' + text.replace(anchor, extra + anchor, 1) + ']}'
    # A number marker in the document: ordinary decoding yields a non-finite
    # float, whose product digest matches the stored digest written here.
    value = {'NaN': float('nan'), 'Infinity': float('inf'),
             '-Infinity': float('-inf')}.get(detail, float(detail))
    changed = json.loads(json.dumps(row))
    changed['evidence']['document']['marker'] = value
    changed['evidence']['document_sha256'] = document_digest(changed['evidence']['document'])
    text = json.dumps(changed)
    native = json.dumps(value)
    if text.count('"marker": ' + native) != 1:
        raise ValueError('constructor marker is not unique')
    return '{"version": 1, "reviews": [' + text.replace('"marker": ' + native,
                                                       '"marker": ' + detail, 1) + ']}'


def finite(literal, row, document_digest):
    """A valid checkpoint whose evidence document carries one finite number literal."""
    changed = json.loads(json.dumps(row))
    value = json.loads(literal)
    changed['evidence']['document']['marker'] = value
    changed['evidence']['document_sha256'] = document_digest(changed['evidence']['document'])
    text = json.dumps(changed)
    native = '"marker": ' + json.dumps(value)
    if text.count(native) != 1:
        raise ValueError('constructor marker is not unique')
    return '{"version": 1, "reviews": [' + text.replace(native, '"marker": ' + literal, 1) + ']}'
