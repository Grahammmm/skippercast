"""Plan measured-survey work from the reference grid, without granting coverage.

Only reviewed native windows make a reach runnable. Envelope intersection is a
work estimate; run.py still opens the pixels before it credits any area.
"""
from collections import Counter
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform, unary_union

from skippercast.platform.contracts import REPO, read_json
from .coverage import cell_geometry
from .io import sha256
from .manifest import load_manifest, physical_source
from .source_scope import scoped_manifest


def private_progress(root, ledger, manifest):
    """Schedule beyond completed private batches without crediting public area."""
    root = Path(root)
    current = {r['id']: r for r in manifest['surveys']}
    result = {}
    for path in (root/'var/seafloor/private-reaches').glob('*/run.json'):
        receipt = read_json(path)
        inputs = receipt.get('inputs', {})
        if (receipt.get('publication_prohibited') is not True
                or inputs.get('reference_cells_sha256') != ledger['reference_cells_sha256']
                or not inputs.get('sources')
                or any(current.get(r['id']) != r for r in inputs['sources'])):
            continue
        outputs = receipt.get('outputs', {})
        if not outputs:
            continue
        for name, expected in outputs.items():
            if (Path(name).name != name or not (path.parent/name).is_file()
                    or sha256(path.parent/name) != expected):
                raise ValueError('Private progress output checksum mismatch')
        if receipt['ledger_summary'].get('processing_incomplete') is False:
            result[path.parent.name] = receipt['ledger_summary']
    return result


def plan(root=REPO, region=None, max_new=3, *, progress=None, physical_only=False):
    root = Path(root)
    ledger = read_json(root/'dist/data/seafloor-ledger.json')
    if not 0 <= max_new <= len(ledger['reaches']):
        raise ValueError('max_new must be between 0 and the number of catalog reaches')
    regions = {r['region'] for r in ledger['reaches']}
    if region and region not in regions and region != ledger['scope']:
        raise ValueError('Unknown seafloor region')
    manifest, source_scope = scoped_manifest(root, load_manifest(root))
    if physical_only and progress is None:
        progress = private_progress(root, ledger, manifest)
    reference = root/'var/seafloor/reference/cells.json'
    if not reference.exists() or sha256(reference) != ledger['reference_cells_sha256']:
        raise ValueError('Restore the verified reference first: python -m skippercast.seafloor restore-reference --fetch')
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    sources = [(r['id'], transform(project, box(*r['adapter_review']['requested_bounds_wgs84'])))
               for r in manifest['surveys'] if physical_source(r, physical_only=physical_only)]
    cells = {}
    for c in read_json(reference)['cells']:
        cells.setdefault(c['reach'], []).append(c)
    rows = []
    reviewed = set(read_json(root/'catalog/seafloor-screen.json')['reviewed_reaches'])
    for r in ledger['reaches']:
        if region and region != ledger['scope'] and r['region'] != region:
            continue
        reach_cells = cells.get(r['id'], [])
        scope = unary_union([cell_geometry(c) for c in reach_cells])
        matching = [(ident, geometry) for ident, geometry in sources if geometry.intersects(scope)]
        envelope = unary_union([g for _, g in matching])
        estimate = sum(c['band_area_m2'] for c in reach_cells if envelope.intersects(cell_geometry(c)))/1e6
        private_complete = r['id'] in (progress or {})
        processed = r['status'] != 'unassessed' or private_complete
        rows.append({'reach': r['id'], 'region': r['region'], 'processed': processed,
            'pending_ledger_merge': private_complete and r['status'] == 'unassessed',
            'action': 'refresh' if processed else 'compute' if matching else 'qualify-source',
            'survey_ids': [i for i, _ in matching], 'reviewed_window_band_estimate_km2': round(estimate, 6),
            'tier1_km2': r['tier1_km2'], 'tier2_km2': r['tier2_km2'],
            'screen_reviewed': r['id'] in reviewed,
            'next_step': 'Run measured habitat; screen at publication' if matching else
                         'Inspect original source, review metadata/rights, promote manifest row'})
    new = sorted([r for r in rows if r['action'] == 'compute'],
                 key=lambda r: (-r['reviewed_window_band_estimate_km2'], r['reach']))[:max_new]
    selected = [r for r in rows if r['processed']] + new
    return {'version': 1, 'scope': region or ledger['scope'], 'physical_only': physical_only,
        **({'source_scope': source_scope} if source_scope is not None else {}),
        'survey_status_counts': dict(Counter(r['status'] for r in manifest['surveys'])),
        'totals': ledger['totals'], 'reaches': rows,
        'selected': [{'reach': r['reach'], 'region': r['region']} for r in selected],
        'new_reaches': [r['reach'] for r in new],
        'source_review_queue': [{'id': r['id'], 'publisher': r['publisher'], 'title': r['title'],
                                'status': r['status'], 'url': r['url'], 'hold_reason': r['hold_reason']}
                               for r in manifest['surveys'] if r['status'] in ('candidate', 'hold')
                               and r['kind'] == 'bathymetry'],
        'notice': 'Window overlap estimates schedule work only. Actual valid pixels establish coverage. '
                  'Source-review queue has no verified regional footprint; never auto-promote by title or envelope.'}


def report(document):
    lines = ['# Seafloor rollout', '', document['notice'], '',
             '| Reach | Next action | Mapped km² | Published habitat km² | Screen reviewed |',
             '| --- | --- | ---: | ---: | --- |']
    for r in document['reaches']:
        lines.append(f"| {r['reach']} | {r['action']} | {r['tier1_km2']:.3f} | {r['tier2_km2']:.3f} | {r['screen_reviewed']} |")
    lines += ['', 'Next new batch: '+(', '.join(document['new_reaches']) or 'none'),
              'Survey states: '+str(document['survey_status_counts']),
              'Completed privately, awaiting ledger merge: '+str(sum(r['pending_ledger_merge'] for r in document['reaches'])),
              'Qualify-source means research remains; it does not mean the seafloor is unmapped by its publisher.']
    return '\n'.join(lines)+'\n'
