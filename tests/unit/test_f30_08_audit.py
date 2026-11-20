"""F30-08: context geometry must cite the XML bytes that defined its classes."""
from hashlib import sha256
from unittest.mock import Mock

import pytest

from tests.unit.test_f30_04_audit import (ARCHIVE_URL, LEGACY, MODERN, NOW, XML_URL,
                                         original_legend, raster_digest)  # noqa: F401 (fixture)

pytestmark = pytest.mark.gis


@pytest.fixture(params=['statewide', 'doi'])
def build_context(request, monkeypatch, tmp_path):
    from shapely.geometry import Polygon

    from research.scripts import build_usgs_doi_context as doi
    from research.scripts import build_usgs_statewide_context as statewide

    builder = statewide if request.param == 'statewide' else doi
    monkeypatch.setattr(builder, 'mpa_union', lambda _: Polygon())
    decoder = Mock(wraps=statewide._class3_encoding)
    monkeypatch.setattr(statewide, '_class3_encoding', decoder)
    mpas = {'sources': {'mpas': {'data_retrieved_at': NOW.isoformat()}}}
    kind = 'seafloor_character'
    product = {'metadata_url': XML_URL, 'filename': 'synthetic.tif', 'description': 'synthetic'}

    def build(record, audited_xml, audited_archive):
        row = {'kind': kind, 'status': 'ok', 'release_id': 'SYNTHETIC', 'block_id': 'SYNTHETIC',
               'metadata_url': XML_URL, 'archive_url': ARCHIVE_URL, 'archive_sha256': audited_archive}
        if audited_xml is not None:
            row['metadata_sha256'] = audited_xml
        metadata = {'scope': 'usgs-state-waters-doi-native-metadata',
                    'records': [{**record, 'block_id': 'SYNTHETIC', 'kind': kind}]}
        if request.param == 'statewide':
            result = statewide.build(
                {'source_url': XML_URL, 'blocks': [{'id': 'SYNTHETIC', 'products': {kind: [product]}}]},
                metadata, {'scope': 'usgs-state-waters-native-grid-audit', 'products': [row]}, mpas, tmp_path,
            )
            return result['features'], result['failed_blocks']
        result = doi.build(
            {'scope': 'usgs-state-waters-doi-product-links', 'releases': [{'products': [product]}]},
            metadata, {'scope': 'usgs-state-waters-doi-native-grid-audit', 'products': [row]}, mpas, tmp_path,
            {'schema_version': 1, 'scope': 'reviewed-usgs-natural-hard-context-holds'},
        )
        return result['features'], result['failed_releases']

    return build, decoder


@pytest.mark.parametrize('case', ['exact-match', 'changed-xml', 'missing-digests', 'archive-mismatch'])
def test_context_requires_the_audited_legend(build_context, raster_digest, case):
    """A URL-only join would decode a new legend's class 13 yet cite the old XML."""
    build, decoder = build_context
    original = original_legend(values=(MODERN,))
    current = original.copy()
    audited_xml = original['xml_sha256']
    audited_archive = raster_digest
    if case == 'changed-xml':
        current = original_legend(definitions=(('SUBSTRATE', LEGACY),))
        assert current['metadata_url'] == original['metadata_url']
        assert current['xml_sha256'] != audited_xml
    elif case == 'missing-digests':
        del current['xml_sha256']
        audited_xml = None
    elif case == 'archive-mismatch':
        audited_archive = sha256(b'different synthetic archive').hexdigest()

    features, failures = build(current, audited_xml, audited_archive)
    if case == 'exact-match':
        assert not failures
        assert len(features) == 1
        assert features[0]['properties']['source_metadata_sha256'] == current['xml_sha256']
        assert features[0]['properties']['source_file_sha256'] == raster_digest
    else:
        assert not features
        assert len(failures) == 1 and failures[0].startswith('SYNTHETIC:')
        if case == 'archive-mismatch':
            assert 'raster digest' in failures[0]
        else:
            assert 'XML digest' in failures[0]
            decoder.assert_not_called()
