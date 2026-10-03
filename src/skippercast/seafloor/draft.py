"""Repeatable discovery writes a draft; it cannot grant rights or promote coverage."""
from copy import deepcopy
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from skippercast.platform.contracts import REPO, ID, atomic_json, read_json
from .source_ingest import ingest
from .manifest import review_spacing


def add_survey(url, bounds, *, ident=None, format_name=None, member='unknown', local=None,
               fetch=False, root=REPO):
    root = Path(root)
    matches = [r for r in read_json(root / 'catalog/surveys.json')['surveys']
               if r['url'] == url and (not ident or r['id'] == ident)]
    if len(matches) > 1:
        raise ValueError('Select --id for a URL with multiple products')
    if matches:
        row = deepcopy(matches[0])
        if member != 'unknown':
            row['archive_member'] = member
    else:
        ident = ident or 'survey-' + hashlib.sha256(url.encode()).hexdigest()[:16]
        if not ID.fullmatch(ident):
            raise ValueError('Invalid survey ID')
        row = {key: 'unknown' for key in ('publisher', 'landing_page', 'year', 'resolution_m',
               'horizontal_crs', 'vertical_datum', 'license', 'sha256', 'bytes', 'hold_reason')}
        row.update(id=ident, title=Path(urlsplit(url).path).name, url=url,
                   format=format_name or ('bag' if url.lower().endswith('.bag') else 'usgs-geotiff'),
                   kind='bathymetry', derived_from=[], status='candidate', archive_member=member,
                   evidence=[], field_evidence={}, inspection_level='native', lineage_status='unknown',
                   notes='Private draft; metadata and rights require review before catalog inclusion.')
    saved, downloaded, unchanged = ingest(row, bounds, root=root, fetch=fetch, local=local)
    row.update(status='candidate', sha256=saved['source_sha256'], bytes=saved['source_bytes'],
               resolution_m=review_spacing(saved), horizontal_crs=saved['horizontal_crs'],
               vertical_datum=saved['vertical_datum'], hold_reason='unknown')
    destination = root / 'var/seafloor/drafts' / (row['id'] + '.json')
    atomic_json(destination, {'row': row, 'adapter_review': saved,
                              'downloaded': downloaded, 'normalization_reused': unchanged}, indent=2)
    return destination
