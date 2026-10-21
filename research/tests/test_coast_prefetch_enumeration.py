"""Offline pagination, identity, metadata-only routes and fail-closed reconciliation."""
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from research.scripts import enumerate_coast_prefetch as e
from skippercast.coastal.prefetch import Hold, atomic_json


def listing(keys=(), *, truncated=False, token=None):
    contents = ''.join(f'<Contents><Key>{k}</Key><Size>{n}</Size><ETag>not-sha256</ETag></Contents>' for k, n in keys)
    return (f'<ListBucketResult xmlns="{e.NS["s"]}">{contents}'
            f'<IsTruncated>{str(truncated).lower()}</IsTruncated>'
            + (f'<NextContinuationToken>{token}</NextContinuationToken>' if token else '')
            + '</ListBucketResult>').encode()


def test_s3_paginates_encodes_tokens_and_deduplicates():
    calls = []
    pages = [listing([('BlueTopo/a', 1)], truncated=True, token='a+/='),
             listing([('BlueTopo/a', 1), ('BlueTopo/b', 2)])]
    def get(url):
        calls.append(parse_qs(urlsplit(url).query))
        return pages.pop(0)
    assert len(e.list_s3(get, 'BlueTopo/')) == 2
    assert calls[1] == {'list-type': ['2'], 'prefix': ['BlueTopo/'], 'max-keys': ['1000'],
                        'continuation-token': ['a+/=']}


@pytest.mark.parametrize('pages', [
    [listing(truncated=True)],
    [listing(truncated=True, token='a'), listing(truncated=True, token='a')],
    [listing([('outside/key', 1)])],
    [listing([('BlueTopo/a', 1)], truncated=True, token='a'), listing([('BlueTopo/a', 2)])],
    [b'<Error/>'],
])
def test_bad_s3_pages_fail_closed(pages):
    with pytest.raises(Hold):
        e.list_s3(lambda _: pages.pop(0), 'BlueTopo/')


def test_bag_links_keep_all_variants_and_refuse_escapes():
    directory = e.DIRECTORY + 'H12001-H14000/H13089/BAG/'
    links = b'<a href="a_VR.bag">a</a><a href="b_2m.bag">b</a><a href="../">up</a><a href="a_VR.bag">duplicate</a>'
    assert e.bag_urls(links, directory) == [directory + 'a_VR.bag', directory + 'b_2m.bag']
    for bad in [b'<a href="../other.bag">escape</a>', b'<a href="https://evil.example/x.bag">escape</a>', b'<html>no bags</html>']:
        with pytest.raises(Hold):
            e.bag_urls(bad, directory)


def query_stub(change=None):
    def query(params):
        if 'returnCountOnly' in params:
            return {'count': 101}
        if 'returnIdsOnly' in params:
            return {'objectIds': list(range(101)), 'objectIdFieldName': 'OBJECTID'}
        ids = list(map(int, params['objectIds'].split(',')))
        page = {'spatialReference': {'wkid': 4326}, 'features': [
            {'attributes': {'OBJECTID': i, 'SURVEY_ID': f'H{i:05d}'}} for i in ids]}
        if change:
            change(page)
        return page
    return query


def test_nos_ids_batched_with_completeness_proof():
    assert len(e.nos_features(query_stub())) == 101


@pytest.mark.parametrize('change', [
    lambda p: p.update(exceededTransferLimit=True),
    lambda p: p.update(spatialReference={'wkid': 3857}),
    lambda p: p['features'].pop(),
    lambda p: p['features'].append(p['features'][0]),
])
def test_nos_truncation_and_crs_fail(change):
    with pytest.raises(Hold):
        e.nos_features(query_stub(change))


@pytest.mark.parametrize('url', [e.S3 + 'BlueTopo/tile/data.tiff',
    'https://www.gmrt.org/services/GridServer?layer=topo',
    e.DIRECTORY + 'H12001-H14000/H13089/BAG/file.bag',
    e.S3 + 'BlueTopo/_BlueTopo_Tile_Scheme/../../file.gpkg'])
def test_metadata_routes_never_fetch_source_payloads(tmp_path, url):
    metadata = e.Metadata(tmp_path, offline=True)
    with pytest.raises(Hold):
        metadata.get(url)


def test_retained_metadata_hash_and_offline_replay(tmp_path):
    metadata = e.Metadata(tmp_path, offline=True)
    url = e.S3 + '?list-type=2&prefix=BlueTopo/'
    key = hashlib.sha256(url.encode()).hexdigest()
    body = tmp_path / (key + '.body')
    body.write_bytes(b'fixture')
    atomic_json(tmp_path / (key + '.json'), {'url': url, 'bytes': 7,
                'sha256': hashlib.sha256(b'fixture').hexdigest()})
    assert metadata.get(url) == b'fixture'
    body.write_bytes(b'changed')
    with pytest.raises(Hold, match='mismatch'):
        metadata.get(url)


def test_reconcile_preserves_pins_and_holds_and_full_segment_association():
    url = e.DIRECTORY + 'H12001-H14000/H13089/BAG/a.bag'
    old = {'url': url, 'source': 'noaa-nos', 'segments': ['C1'], 'bytes': 12, 'sha256': 'a' * 64}
    seed = {'files': [old], 'unresolved': [
        {'id': 'noaa-nos-statewide'}, {'id': 'bluetopo-ca'}, {'id': 'association-test', 'url': url}]}
    extra = {'files': [], 'unresolved': [{'source': 'gebco-2026-california-subset', 'reason': 'held'},
                                        {'source': 'nos-bag-ca-inventory-gaps'}]}
    nos = ([{**old, 'bytes': None, 'sha256': None, 'segments': ['C1', 'C2']}], [], {'survey': 'evidence'})
    result = e.reconcile(seed, extra, nos, None)
    assert result['files'][0]['segments'] == ['C1', 'C2']
    assert result['files'][0]['bytes'] == 12 and result['files'][0]['sha256'] == 'a' * 64
    assert result['unresolved'] == [{'id': 'bluetopo-ca'}, extra['unresolved'][0]]
    assert len(result['reconciled_seed_gaps']) == 2


def test_supplement_is_exactly_hash_pinned(tmp_path):
    path = tmp_path / 'supplement.json'
    path.write_text(json.dumps({'files': [], 'unresolved': []}))
    with pytest.raises(Hold, match='accepted artifact'):
        e.supplement(path)


def test_head_uses_no_body_and_replays_without_network(tmp_path):
    from types import SimpleNamespace
    metadata = e.Metadata(tmp_path)
    url = e.DIRECTORY + 'H12001-H14000/H13089/BAG/a.bag'
    calls = []
    def request(method, target, **kwargs):
        calls.append((method, target, kwargs))
        return SimpleNamespace(headers={'Content-Length': '123', 'ETag': 'etag'}, final_url=url)
    metadata.transport.request = request
    assert metadata.head(url)['bytes'] == 123
    assert calls[0][0] == 'HEAD' and calls[0][2]['max_bytes'] == 0
    assert e.Metadata(tmp_path, offline=True).head(url)['bytes'] == 123
    assert len(calls) == 1


def test_missing_head_size_does_not_fallback_to_get(tmp_path):
    from types import SimpleNamespace
    metadata = e.Metadata(tmp_path)
    url = e.DIRECTORY + 'H12001-H14000/H13089/BAG/a.bag'
    calls = []
    def request(method, target, **kwargs):
        calls.append(method)
        return SimpleNamespace(headers={}, final_url=url)
    metadata.transport.request = request
    with pytest.raises(Hold, match='positive size'):
        metadata.head(url)
    assert calls == ['HEAD']


def test_metadata_budget_fails_without_request(tmp_path):
    metadata = e.Metadata(tmp_path)
    metadata.requests = 2000
    with pytest.raises(Hold, match='bound reached'):
        metadata.get(e.S3 + '?list-type=2')
    with pytest.raises(Hold, match='bound reached'):
        metadata.head(e.DIRECTORY + 'H12001-H14000/H13089/BAG/a.bag')


def test_nos_exclusions_are_explained_not_silently_dropped():
    url = e.DIRECTORY + 'D00001-D02000/D00186/BAG/a.bag'
    seed = {'files': [], 'unresolved': [{'id': 'association-a', 'source': 'noaa-nos', 'url': url}]}
    nos = ([], [], {'D00186': {'segments': [], 'bounds': [-121, 36, -120, 37]}})
    result = e.reconcile(seed, {'files': [], 'unresolved': []}, nos, None)
    assert not result['unresolved'] and not result['files']
    assert result['reconciled_seed_gaps'][0]['resolution'].startswith('Official survey envelope outside')


def test_generated_subset_metadata_does_not_clear_transfer_hold():
    extra = {'files': [{'source': 'crm', 'segments': ['C1'], 'bytes': None,
                       'url': 'https://www.ngdc.noaa.gov/thredds/dodsC/crm/fixture.dods?z[0:1:2]'}],
             'unresolved': []}
    result = e.reconcile({'files': [], 'unresolved': []}, extra, None, None)
    assert 'preflight' in result['unresolved'][0]['reason']
