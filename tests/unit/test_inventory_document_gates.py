"""Individually malformed reviews never clear cached inventory holds."""
import hashlib
import pytest
from skippercast.coastal import cached_inventory as ci


def write_document(root, role, value):
    data = ci.encoded(value)
    (root/(role+'.json')).write_bytes(data)
    return {'path': role+'.json', 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'contract': 'cached-source-json-v1'}


def valid_plan(root):
    source = {'sha256': 'a'*64, 'bytes': 4, 'url': 'https://example.org/synthetic.bag'}
    (root/'source.bag').write_bytes(b'data')
    binding = {'source': {'sha256': source['sha256'], 'bytes': 4}}
    header = dict(binding, vertical={'conflicts': [], 'datum': 'MLLW', 'sign': 'positive_up',
        'units': 'm', 'datum_realization': 'unknown', 'scale': 1, 'offset': 0, 'scale_offset_applied': False},
        shape=[8, 8], transform=[2, 0, 0, 0, -2, 16], resolution_m=[2, 2], driver='BAG', count=2,
        horizontal_crs='EPSG:26910')
    scope = dict(binding, status='accepted_scope_only', independent=True, holds=[], checked_at=90,
                 valid_until=300, window_set=[[0, 0, 4, 4]], product_region='synthetic',
                 native_quality_accepted=False, global_affine=header['transform'], grid_shape=header['shape'])
    rights = dict(binding, independent=True, private_use=True,
                  accepted_source_rights_for_declared_private_purpose=True, holds_added=[], checked_at=90, valid_until=300)
    candidate = {'source_manifest': write_document(root, 'source', source),
                 'prepared_acquisition': write_document(root, 'prepared', binding),
                 'header': write_document(root, 'header', header),
                 'scope': write_document(root, 'scope', scope),
                 'rights': write_document(root, 'rights', rights),
                 'cache_path': 'source.bag', 'window_set': [[0, 0, 4, 4]]}
    return {'schema': ci.PLAN, 'region': 'synthetic', 'candidates': [candidate],
            'metadata_bytes': ci.MAX_METADATA, 'output_bytes': ci.MAX_OUTPUT,
            'network_bytes': 0, 'source_read_bytes': 0, 'output_root': str(root/'out')}


@pytest.mark.parametrize('role', ['header', 'rights', 'scope'])
@pytest.mark.parametrize('mutation', ['empty', 'missing', 'null', 'list', 'string', 'false'])
def test_each_review_document_gate_with_otherwise_valid_prerequisites(tmp_path, monkeypatch, role, mutation):
    plan = valid_plan(tmp_path)
    original = ci.bounded_metadata_read
    def metadata_only(root, name, expected):
        assert name.endswith('.json'), 'No native payload reads permitted'
        return original(root, name, expected)
    monkeypatch.setattr(ci, 'bounded_metadata_read', metadata_only)
    control = ci.inventory(tmp_path, plan, now=100, horizon=200)
    assert control['sources'][0]['holds'] == []
    assert control['usable_source_ids'] == ['a'*64]
    candidate = plan['candidates'][0]
    if mutation == 'missing':
        candidate.pop(role)
    else:
        candidate[role] = write_document(tmp_path, role, {'empty': {}, 'null': None, 'list': [],
                                                       'string': 'bad', 'false': False}[mutation])
    if mutation not in {'empty', 'missing'}:
        with pytest.raises(ValueError, match='JSON object'):
            ci.inventory(tmp_path, plan, now=100, horizon=200)
    else:
        result = ci.inventory(tmp_path, plan, now=100, horizon=200)
        expected = role+'_metadata_missing' if mutation == 'missing' else {
            'header': 'vertical_metadata_unresolved', 'rights': 'private_source_rights_unreviewed',
            'scope': 'prospective_geographic_scope_unreviewed'}[role]
        assert expected in result['sources'][0]['holds']
        assert not result['sources'][0]['usable_for_acquisition_request']
        assert result['usable_source_ids'] == []
        assert result['usage']['source_read_bytes'] == result['usage']['network_bytes'] == 0
