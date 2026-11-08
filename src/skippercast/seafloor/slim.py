"""The brief's slim reef file (SC-PERF-REEFDIET-1).

The brief and its ranking read each reef's attributes and the publish-time protected-area verdict
(SC-PERF-PROTCHECK-1), not its outline, which is most of the 15 MB export. This writes those attributes alone,
gzip-compressed, beside the full export. The full export stays for the planner, the map and GPX export.

The browser uses the slim file only while its own boundary data hash to the export's `protected_screen.fingerprint`
and every reef carries a verdict; otherwise it loads the full export and runs the outline check (web/ranking.ts).
The property list is slim_fields.json, shared with tests/test_reef_slim.mjs.
"""
import gzip
import hashlib
import json
from pathlib import Path
import re

# Content-addressed name (habitat-slim-<first 16 hex of its sha256>.geojson.gz): a new file never overwrites the one a live
# manifest names, so it can be uploaded and read back before the manifest switches to it (publish.py publish_bundle).
SLIM_NAME = re.compile(r'habitat-slim-([a-f0-9]{16})\.geojson\.gz')


def slim_file(sha256_hex):
    return f'habitat-slim-{sha256_hex[:16]}.geojson.gz'


# Size budget for the slim file (gzip bytes). Real morro-bay export, 3064 reefs, when set: see docs/operations/perf-budget.md.
# Raise it in a pull request with a reason, like scripts/perf-budget.json.
SLIM_MAX_BYTES = 450_000
SLIM_FIELDS = tuple(json.loads((Path(__file__).with_name('slim_fields.json')).read_text())['properties'])


def slim_features(export_features):
    """The export's features without outline, with only the listed properties. Fails when a reef has no verdict."""
    out = []
    for f in export_features:
        p = f['properties']
        if not isinstance(p.get('protected_place'), dict):
            raise ValueError(f"slim reef file needs a protected-area verdict for every reef; missing for {p.get('id')}")
        props = {k: p[k] for k in SLIM_FIELDS if k in p}
        if isinstance(p.get('screen'), dict):   # the loader reads only screen.status
            props['screen'] = {'status': p['screen'].get('status')}
        out.append({'type': 'Feature', 'geometry': None, 'properties': props})
    return out


def write_slim(folder, *, region, expires_at, export_sha256, protected, export_features):
    """Write the slim file into `folder`; return its manifest fields (empty when there are no verdicts to carry)."""
    folder = Path(folder)
    for stale in folder.glob('habitat-slim*.geojson.gz'):   # a build without verdicts must not leave an earlier build's file
        stale.unlink()
    if not protected or not export_features:
        return {}
    data = {'type': 'FeatureCollection', 'schema_version': 1, 'region': region, 'expires_at': expires_at,
            'slim_of': export_sha256, 'protected_screen': protected, 'features': slim_features(export_features)}
    raw = json.dumps(data, separators=(',', ':'), ensure_ascii=False).encode()
    packed = gzip.compress(raw, mtime=0)
    if len(packed) > SLIM_MAX_BYTES:
        raise ValueError(f'Slim reef file is {len(packed)} bytes, over its {SLIM_MAX_BYTES} byte budget (slim.py SLIM_MAX_BYTES)')
    sha = hashlib.sha256(packed).hexdigest()
    (folder/slim_file(sha)).write_bytes(packed)
    return {'slim_file': slim_file(sha), 'slim_sha256': sha, 'slim_bytes': len(packed),
            'slim_decoded_bytes': len(raw)}
