"""Offline controls for original-product redistribution evidence in DS 781."""
import hashlib
import json
from xml.sax.saxutils import escape

import pytest

from research.scripts import audit_usgs_ds781_metadata as fgdc
from research.scripts.audit_usgs_character_semantics import audit as audit_classes
from research.scripts.audit_usgs_ds781_native_character import audit as audit_native

ARCHIVE = 'https://pubs.usgs.gov/ds/781/synthetic-class.zip'
CATALOG_METADATA = 'https://pubs.usgs.gov/ds/781/synthetic-class.txt'
XML = 'https://pubs.usgs.gov/ds/781/synthetic-class.xml'
POSITIVE = 'explicit-public-domain-redistribution'
REVIEWED_TERMS = (
    'USGS-authored or produced data and information are in the public domain from the U.S. '
    'Government and are freely redistributable with proper metadata and source attribution. '
    'Please recognize and acknowledge the U.S. Geological Survey as the originator of the dataset '
    'and in products derived from these data.'
)


@pytest.mark.parametrize(('terms', 'access', 'change'), [
    pytest.param(REVIEWED_TERMS, 'None', None, id='reviewed-original'),
    pytest.param('not public domain and not freely redistributable', 'None', 'terms', id='negated'),
    pytest.param(REVIEWED_TERMS + ' Other producers own some layers.', 'None', 'terms', id='mixed-source'),
    pytest.param(REVIEWED_TERMS + ' Redistribution requires permission.', 'None', 'terms', id='conditional'),
    pytest.param('Rights unspecified', 'None', 'terms', id='unknown'),
    pytest.param(REVIEWED_TERMS, 'Access by permission', 'terms', id='restricted-access'),
    pytest.param(REVIEWED_TERMS, 'None', 'bytes', id='unreviewed-metadata-bytes'),
    pytest.param(REVIEWED_TERMS, 'None', 'archive', id='transplanted-notice'),
    pytest.param(REVIEWED_TERMS, 'None', 'url', id='wrong-original-url'),
])
def test_only_reviewed_terms_for_original_product_are_admitted(terms, access, change, tmp_path, monkeypatch):
    reviewed_xml = f'''<metadata><idinfo><citation><citeinfo><title>Synthetic grid</title></citeinfo></citation>
    <accconst>{escape(access)}</accconst><useconst>{escape(terms)}</useconst></idinfo>
    <eainfo><detailed><attr><attrlabl>Value</attrlabl><attrdomv><edom><edomv>3</edomv>
    <edomvd>Hard rugose bedrock</edomvd></edom></attrdomv></attr></detailed></eainfo></metadata>'''.encode()
    raw = reviewed_xml + b'\n' if change == 'bytes' else reviewed_xml
    product = {'kind': 'seafloor-character', 'archive_url': ARCHIVE,
               'metadata_url': CATALOG_METADATA, 'description': 'Synthetic character grid'}
    review_row = {'map_area': 'Synthetic area', 'kind': product['kind'], 'archive_url': ARCHIVE,
                  'metadata_url': CATALOG_METADATA, 'xml_url': XML, 'status': 'reviewed',
                  'metadata_sha256': hashlib.sha256(reviewed_xml).hexdigest(),
                  'access_constraints': access, 'use_constraints': terms, 'rights_evidence': POSITIVE}
    review = {'scope': 'usgs-ds781-original-fgdc-metadata-triage', 'record_count': 1, 'records': [review_row]}
    path = tmp_path / 'review.json'
    path.write_text(json.dumps(review), encoding='utf-8')
    monkeypatch.setattr(fgdc, 'METADATA_REVIEW', path)

    if change == 'archive':
        product['archive_url'] = ARCHIVE.replace('synthetic-class', 'other-class')
    if change == 'url':
        product['metadata_url'] = CATALOG_METADATA.replace('synthetic-class', 'other-class')
    area = {'name': 'Synthetic area', 'planning_sector_ids': [], 'catalog_url': 'synthetic', 'products': [product]}
    filler = {'kind': 'bathymetry', 'metadata_url': None}
    areas = [area, *({'name': f'Filler {n}', 'planning_sector_ids': [], 'products': [
        {**filler, 'archive_url': f'https://pubs.usgs.gov/ds/781/synthetic-{n}-{i}.zip'} for i in range(2)
    ]} for n in range(38))]
    inventory = {'schema_version': 1, 'index_sha256': 'synthetic', 'map_areas': areas}
    triage = fgdc.audit(inventory, fetcher=lambda _: raw)
    candidate = next(row for row in triage['records'] if row['archive_url'] == product['archive_url'])
    assert candidate['status'] == 'reviewed'
    assert candidate['rights_evidence'] == (POSITIVE if change is None else 'requires-review')

    # Replay a legacy receipt with a false affirmative label at both consumers.
    candidate['rights_evidence'] = POSITIVE
    archive_opens = []

    def archive_fetcher(url, _path):
        archive_opens.append(url)
        raise ValueError('Offline archive boundary reached')

    native = audit_native(inventory, triage, tmp_path, fetcher=archive_fetcher)
    row = native['products'][0]
    assert archive_opens == ([ARCHIVE] if change is None else [])
    assert row['status'] == ('failed' if change is None else 'held')

    # Replay a prior native receipt claiming it had already inspected this raster.
    row.update(status='ok', archive_sha256='synthetic', class_table_status='missing', class_counts={'3': 1})
    native['inspected_count'] = 1
    if change is None:
        result = audit_classes(native, triage, getter=lambda url: {XML: raw}[url])
        assert result['verified_class_3_count'] == 1
    else:
        with pytest.raises(ValueError, match='redistribution review is not pinned'):
            audit_classes(native, triage, getter=lambda _: pytest.fail('held metadata must not be opened'))


def test_negated_redistribution_does_not_receive_affirmative_label_from_parser():
    xml = b'''<metadata><idinfo><citation><citeinfo><title>Synthetic grid</title>
    </citeinfo></citation><useconst>not public domain and not freely redistributable</useconst>
    </idinfo></metadata>'''
    assert fgdc.parse_xml(xml)['rights_evidence'] == 'requires-review'
