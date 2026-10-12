"""Coast asset publisher (FE-85): unknown or rights-held sources refuse the run before any download."""
from datetime import datetime, timezone
import hashlib
import io
import json
import unittest
from unittest.mock import patch

from scripts.coast import publish_assets as pa

CATALOG = [
    {'id': 'usgs-open', 'review_status': 'approved', 'documentation_url': 'https://doi.org/10.5066/P9OPEN01',
     'rights': {'commercial_use': 'allowed'}},
    {'id': 'usgs-held', 'review_status': 'approved', 'documentation_url': 'https://doi.org/10.5066/P9HELD01',
     'rights': {'commercial_use': 'permission-required'}},
    {'id': 'noaa-candidate', 'review_status': 'candidate', 'documentation_url': 'https://example.gov/candidate/',
     'rights': {'commercial_use': 'allowed'}},
    {'id': 'usgs-naip', 'review_status': 'approved', 'documentation_url': 'https://example.gov/naip',
     'rights': {'commercial_use': 'allowed'}},
]
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)
RELEASE = 'c' * 64


def habitat_documents(region_etag=None, public_region=None):
    """A synthetic live habitat release, its public copy and the reef context bound to it."""
    region = {'regionId': 'morro-bay', 'archiveSha256': 'a' * 64, 'archiveBytes': 5, 'expiresAt': '2099-01-01T00:00:00+00:00',
              'archiveETag': region_etag or f'"sha256-{"a" * 64}"'}
    control = {'status': 'ready', 'ready': True, 'releaseId': RELEASE, 'expiresAt': '2099-01-01T00:00:00+00:00',
               'regions': [region, {**region, 'regionId': 'monterey-point-sur'}]}
    public = {**control, 'regions': [public_region or region, {**region, 'regionId': 'monterey-point-sur'}],
              'sources': [{'url': 'https://doi.org/10.5066/P9OPEN01'}], 'geojsonSha256': 'b' * 64, 'geojsonBytes': 9}
    reef = {'expiresAt': '2099-01-01T00:00:00+00:00',
            'asset': {'url': '/data/coast-wide/reef-context.bin', 'sha256': 'd' * 64, 'bytes': 7}}
    return {'/api/habitat/release': control, '/data/skippercast-manifest.json': public, pa.REEF_CONTEXT: reef}


def serving(documents, calls):
    def fake_get(path, origin=pa.ORIGIN, headers=None):
        calls.append(path)
        return 200, {}, json.dumps(documents[path]).encode()
    return patch.object(pa, 'get', fake_get)


class RightsGateTests(unittest.TestCase):
    def test_sources_match_by_doi_or_documented_prefix_only(self):
        found = pa.catalog_ids(['https://media.example.gov/2022/10.5066-P9OPEN01/grid.zip',
                                'https://example.gov/candidate/H1.bag', 'https://unlisted.example/grid'], CATALOG)
        self.assertEqual(list(found.values()), ['usgs-open', 'noaa-candidate', None])

    def test_held_candidate_and_unknown_sources_are_each_refused(self):
        urls = ['https://doi.org/10.5066/P9OPEN01', 'https://doi.org/10.5066/P9HELD01',
                'https://example.gov/candidate/x', 'https://unlisted.example/grid']
        problems = pa.refusals('terrain', urls, CATALOG)
        self.assertEqual(len(problems), 3)
        self.assertTrue(any('rights held for usgs-held' in p for p in problems))
        self.assertTrue(any('rights held for noaa-candidate' in p for p in problems))
        self.assertTrue(any('unknown source https://unlisted.example/grid' in p for p in problems))
        self.assertEqual(pa.refusals('terrain', urls[:1], CATALOG), [])
        self.assertEqual(pa.refusals('terrain', urls[:1], CATALOG[:3]), ['terrain: unknown source usgs-naip (no catalog/sources.json row)'])

    def test_a_group_whose_manifest_names_no_source_is_refused(self):
        self.assertEqual(pa.refusals('habitat', [], CATALOG), ['habitat: upstream manifest lists no sources'])
        self.assertIn('terrain: upstream manifest lists no sources', pa.refusals('terrain', [], CATALOG))

    def test_terrain_plan_pins_enumerated_assets_and_refuses_before_downloading_them(self):
        terrain = {'sources': [{'url': 'https://doi.org/10.5066/P9HELD01'}],
                   'tiles': [{'lods': [{'url': '/data/coast-wide/t.bin', 'sha256': 'a' * 64, 'bytes': 3}]}],
                   'provenanceUrl': '/data/coast-wide/provenance.json',
                   'shoreAsset': {'url': '/data/slo-shore-habitat.geojson', 'sha256': 'b' * 64, 'bytes': 1}}
        calls = []
        provenance = {'sources': [{'url': 'https://doi.org/10.5066/P9OPEN01'}]}
        with serving({pa.TERRAIN_INDEX[0]: terrain, pa.TERRAIN_INDEX[1]: {}, pa.TERRAIN_INDEX[2]: provenance}, calls):
            problems, wanted = pa.plan(['terrain'], catalog=CATALOG, now=NOW)
        self.assertEqual(sorted(calls), sorted(pa.TERRAIN_INDEX))
        self.assertEqual(problems, ['terrain: rights held for usgs-held (approved, commercial_use permission-required)'])
        self.assertEqual(wanted['/data/coast-wide/t.bin'], {'sha256': 'a' * 64, 'bytes': 3})
        self.assertIn('/data/coast-wide/provenance.json', wanted)
        self.assertNotIn('/data/slo-shore-habitat.geojson', wanted)  # shore files stay on the bridge (FE-10, FE-43)

    def test_chart_provenance_sources_are_checked_and_must_be_listed(self):
        terrain = {'sources': [{'url': 'https://doi.org/10.5066/P9OPEN01'}]}
        for provenance, reason in (({'sources': [{'url': 'https://encdirect.example.gov/enc/76'}]}, 'unknown source https://encdirect.example.gov/enc/76'),
                                   ({}, 'upstream manifest lists no sources')):
            with serving({pa.TERRAIN_INDEX[0]: terrain, pa.TERRAIN_INDEX[1]: {}, pa.TERRAIN_INDEX[2]: provenance}, []):
                problems, _ = pa.plan(['terrain'], catalog=CATALOG, now=NOW)
            self.assertEqual(problems, [f'terrain: {reason}'])
        chart = {'provenance': {'url': pa.TERRAIN_INDEX[2], 'sha256': 'f' * 64, 'bytes': 2}}
        with serving({pa.TERRAIN_INDEX[0]: terrain, pa.TERRAIN_INDEX[1]: chart, pa.TERRAIN_INDEX[2]: terrain}, []):
            problems, _ = pa.plan(['terrain'], catalog=CATALOG, now=NOW)
        self.assertEqual(problems, [f'terrain: {pa.TERRAIN_INDEX[2]} differs from the digest the chart model declares'])

    def test_groups_match_the_worker(self):
        self.assertEqual([pa.group_of(p) for p in ('/api/habitat/release', '/data/skippercast-species.json',
                                                   '/data/coast-wide/reef-context.bin', '/data/coast3d/x.bin',
                                                   '/data/slo-shoreline.geojson')],
                         ['habitat', 'habitat', 'habitat', 'terrain', None])


class HabitatPlanTests(unittest.TestCase):
    def plan(self, documents):
        calls = []
        with serving(documents, calls):
            problems, wanted = pa.plan(['habitat'], catalog=CATALOG, now=NOW)
        self.assertEqual(sorted(calls), sorted(documents))  # manifests only, no archive bytes
        return problems, wanted

    def test_every_region_and_the_reef_context_are_pinned_with_the_release(self):
        problems, wanted = self.plan(habitat_documents())
        self.assertEqual(problems, [])
        # The renderer HEADs every region the public manifest lists, so each one is copied.
        for region in ('morro-bay', 'monterey-point-sur'):
            self.assertEqual(wanted[f'/api/habitat/tiles?region={region}'],
                             {'habitatRelease': RELEASE, 'expiresAt': '2099-01-01T00:00:00+00:00', 'sha256': 'a' * 64, 'bytes': 5})
        self.assertEqual(wanted['/data/coast-wide/reef-context.bin']['sha256'], 'd' * 64)
        self.assertEqual(wanted[pa.REEF_CONTEXT]['expiresAt'], '2099-01-01T00:00:00+00:00')
        self.assertEqual(wanted['/data/skippercast-habitat.geojson']['habitatRelease'], RELEASE)

    def test_etag_that_is_not_the_digest_or_a_drifted_public_copy_is_refused(self):
        problems, _ = self.plan(habitat_documents(region_etag='"r2-etag"'))
        self.assertTrue(any('ETag is not its SHA-256' in p for p in problems))
        drifted = {'regionId': 'morro-bay', 'archiveSha256': 'e' * 64, 'archiveBytes': 5, 'expiresAt': '2099-01-01T00:00:00+00:00',
                   'archiveETag': f'"sha256-{"e" * 64}"'}
        problems, wanted = self.plan(habitat_documents(public_region=drifted))
        self.assertTrue(any('morro-bay differs from the live release' in p for p in problems))
        self.assertNotIn('/api/habitat/tiles?region=morro-bay', wanted)

    def test_a_public_manifest_without_sources_is_refused(self):
        for sources in ([], None):
            documents = habitat_documents()
            documents['/data/skippercast-manifest.json']['sources'] = sources
            problems, _ = self.plan(documents)
            self.assertEqual(problems, ['habitat: upstream manifest lists no sources'])

    def test_expired_or_unready_release_and_held_sources_are_refused(self):
        documents = habitat_documents()
        documents['/api/habitat/release'] = {**documents['/api/habitat/release'], 'expiresAt': '2026-01-01T00:00:00+00:00', 'ready': False}
        documents['/data/skippercast-manifest.json']['sources'].append({'url': 'https://doi.org/10.5066/P9HELD01'})
        problems, _ = self.plan(documents)
        for reason in ('release expired', 'does not name the live ready release', 'rights held for usgs-held'):
            self.assertTrue(any(reason in p for p in problems), reason)


class FetchAndUploadTests(unittest.TestCase):
    def test_archives_are_read_in_exact_ranges_and_checked_against_the_release(self):
        data = bytes(range(256)) * 20000  # just over two 2 MiB ranges
        entry = {'habitatRelease': RELEASE, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        seen = []

        def fake_get(path, origin=pa.ORIGIN, headers=None):
            start, end = map(int, headers['Range'][6:].split('-'))
            seen.append((path, start, end))
            return 206, {}, data[start:end + 1]
        with patch.object(pa, 'get', fake_get):
            body, stored = pa.fetch('/api/habitat/tiles?region=morro-bay', entry)
        self.assertEqual(body, data)
        self.assertEqual([s[1:] for s in seen], [(0, pa.RANGE - 1), (pa.RANGE, 2 * pa.RANGE - 1), (2 * pa.RANGE, len(data) - 1)])
        self.assertTrue(all(p == f'/api/habitat/tiles?region=morro-bay&release={RELEASE}' for p, *_ in seen))
        self.assertEqual(stored['contentType'], 'application/octet-stream')
        seen.clear()  # the proxy refuses one range over a whole archive, so a small one is read in two
        small = data[:300]
        with patch.object(pa, 'get', fake_get):
            body, _ = pa.fetch('/api/habitat/tiles?region=cambria-san-simeon',
                               {'habitatRelease': RELEASE, 'sha256': hashlib.sha256(small).hexdigest(), 'bytes': 300})
        self.assertEqual((body, [s[1:] for s in seen]), (small, [(0, 298), (299, 299)]))
        with patch.object(pa, 'get', lambda *a, **k: (200, {}, b'changed')), self.assertRaises(ValueError):
            pa.fetch('/data/coast-wide/t.bin', {'sha256': 'a' * 64, 'bytes': 7})

    def test_upload_promotes_the_pointer_last(self):
        order = []

        class S3:
            def head_object(self, **kw): raise KeyError
            def put_object(self, **kw): order.append(kw['Key']); self.body = kw['Body']
            def get_object(self, **kw): return {'Body': io.BytesIO(self.body)}
        digest = hashlib.sha256(b'tile').hexdigest()
        manifest = json.dumps({'objects': {'/data/coast-wide/t.bin': {'sha256': digest, 'contentType': 'x/y'}}}).encode()
        with patch.object(pa.Path, 'read_bytes', lambda self: b'tile'):
            pa.upload(S3(), 'bucket', 'out', 'e' * 64, manifest)
        self.assertEqual(order, ['coast/objects/' + digest, f'coast/releases/{"e" * 64}.json', 'coast/current.json'])
        with patch.object(pa.Path, 'read_bytes', lambda self: b'tampered'), self.assertRaises(RuntimeError):
            pa.upload(S3(), 'bucket', 'out', 'e' * 64, manifest)


if __name__ == '__main__':
    unittest.main()
