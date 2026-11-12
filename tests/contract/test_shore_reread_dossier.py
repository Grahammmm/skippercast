"""Shore re-read dossier checker (SC1952-07): synthetic completeness and refusal regressions.

Offline: nothing here reads var/ or the network. The committed receipt is checked as a file in the tree.
"""
import ast
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from tests._support import ROOT

SPEC = importlib.util.spec_from_file_location('check_shore_reread_dossier', ROOT / 'scripts/check_shore_reread_dossier.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

H = lambda c: c * 64  # noqa: E731 - a syntactically valid sha256
AT = '2026-11-04T08:00:00.000Z'
PRIV = 'var/shore-review/SC1952-07/'
RECEIPT = ROOT / 'research/receipts/morro-bay-shore-reread-2026-11-03.json'


def same(basis='b', **kw):
    return {'state': 'unchanged', 'basis': basis, **kw}


def source(sid, host, raw='bytes-identical'):
    return {'id': sid, 'url': f'https://{host}/x', 'finalUrl': f'https://{host}/x', 'httpStatus': 200, 'fetchedAt': AT, 'bytes': 10,
            'sha256': H('a'), 'privatePath': PRIV + sid, 'acquisition': {'state': 'acquired'}, 'rawComparison': {'state': raw, 'note': 'n'},
            'baselineRefs': [{'path': 'catalog/shore-habitat/morro-bay.geojson', 'pointer': '/sourceChecks/acquisitions/' + sid, 'sha256': H('b')}]}


def dossier():
    runs = []
    for rid, ids in checker.RUNS.items():
        runs.append({'id': rid, 'accessIds': list(ids), 'access': {'state': 'unchanged'}, 'legal': same(),
                     'source': {'objectClass': same(old={'1': '3A'}, new={'1': '3A'}), 'fullFeatureGeometry': same(old={'1': H('c')}, new={'1': H('c')}),
                                'selectedGeometry': same(old={'sha256': H('d'), 'vertices': 3}, new={'sha256': H('d'), 'vertices': 3}),
                                'priorGeometryHash': {'state': 'unverifiable', 'basis': 'no archived entry'},
                                'rawResponseChange': {'state': 'unverifiable', 'basis': 'raw bytes differ, selected run decides'}}})
    points = []
    for pid, rid in checker.POINTS.items():
        points.append({'id': pid, 'objectId': int(pid[4:]), 'runId': rid, 'state': 'unchanged',
                       'fields': {'Name': {'state': 'unchanged', 'old': 'n', 'new': 'n'}, 'Date_Closd': {'state': 'unchanged', 'old': ' ', 'new': ' '}}})
    m2 = [{'id': k, 'objectId': v, 'name': 'Estero Bluffs', 'coordinates': [-120.9, 35.4], 'state': 'unverifiable', 'basis': 'no archived baseline'} for k, v in checker.M2.items()]
    return {
        'schemaVersion': 1, 'kind': 'shore-reread-dossier', 'stage': 'M1a', 'region': 'morro-bay', 'inspectedGitSha': 'a' * 40,
        'acquiredAt': {'first': AT, 'last': AT}, 'approval': {'status': 'none', 'statement': 'Not an approval or renewal.'},
        'commands': [{'command': 'collect_shore_habitat.py --save-sources var/x'}], 'holds': ['owner re-read pending'],
        'baselines': [{'id': 'b', 'path': 'catalog/shore-habitat/morro-bay.geojson', 'sha256': H('e')}],
        'privateFiles': [{'path': PRIV + 'sources/a.json', 'bytes': 1, 'sha256': H('f')}],
        'sources': [source(k, v, 'bytes-differ' if k in ('noaa', 'terms') else 'bytes-identical') for k, v in checker.SOURCE_HOSTS.items()],
        'runs': runs, 'accessPoints': points,
        'terms': {'rawItem': {'state': 'changed', 'basis': 'bytes differ', 'old': {'sha256': H('1')}, 'new': {'sha256': H('2')}},
                  'licenseInfo': same(old={'sha256': H('3')}, new={'sha256': H('3')})},
        'rules': {'publisherDate': {'state': 'changed', 'basis': 'date moved', 'old': '2026-10-01', 'new': '2026-11-02'},
                  'surfperch': same(old={'season': 'year-round'}, new={'season': 'year-round'}),
                  'californiaHalibut': same(old={'min': 22}, new={'min': 22}),
                  'licenseScope': {'state': 'unverifiable', 'basis': 'archived text came from another page'},
                  'rawPage': {'state': 'changed', 'basis': 'byte change only, no historical HTML', 'old': {'sha256': H('4')}, 'new': {'sha256': H('5')}}},
        'm2Candidates': m2,
        'm2EsteroBluffs': {'selectionState': 'unresolved', 'dependentHold': 'SC1952-08 selection held',
                           'siteSelectionLimits': {'state': 'unverifiable', 'basis': 'not substantiated'},
                           'ownerUrl': {'state': 'unverifiable', 'basis': 'none in the sources'}, 'candidates': []},
    }


def problems(doc):
    return checker.check(doc)


class CompleteDossier(unittest.TestCase):
    def test_complete_dossier_accepts_explicit_unverifiable_baseline(self):
        doc = dossier()
        self.assertEqual(problems(doc), [])
        # missing old HTML is a byte change, distinct from the unchanged species text
        self.assertEqual((doc['rules']['rawPage']['state'], doc['rules']['surfperch']['state'], doc['rules']['licenseScope']['state']),
                         ('changed', 'unchanged', 'unverifiable'))
        self.assertEqual(problems(json.loads(RECEIPT.read_text(encoding='utf-8'))), [])

    def test_unverifiable_without_basis_and_unknown_state_refused(self):
        doc = dossier()
        doc['rules']['licenseScope'] = {'state': 'unverifiable'}
        doc['terms']['licenseInfo']['state'] = 'probably-fine'
        found = '\n'.join(problems(doc))
        self.assertIn('rules.licenseScope: basis missing', found)
        self.assertIn('terms.licenseInfo: state must be one of', found)

    def test_proposed_estero_selection_needs_legend_names_and_owner_url(self):
        doc = dossier()
        doc['m2EsteroBluffs']['selectionState'] = 'proposed'
        doc['m2EsteroBluffs']['candidates'] = [{'objectId': 2255, 'esi': '1A', 'esiLegend': [{'code': '1A', 'legend': None}], 'coordinatesSha256': H('9'), 'vertices': 20}]
        found = '\n'.join(problems(doc))
        self.assertIn('selection must stay unresolved', found)
        self.assertIn('needs object id, ESI code with legend names', found)
        doc = dossier()
        doc['m2EsteroBluffs']['dependentHold'] = ' '
        self.assertIn('must state the held dependent work', '\n'.join(problems(doc)))


class IdentityRefusals(unittest.TestCase):
    def test_missing_or_duplicate_identity_refused(self):
        doc = dossier()
        doc['accessPoints'] = [p for p in doc['accessPoints'] if p['id'] != 'ccc-770']
        self.assertIn("accessPoints: missing ['ccc-770']", problems(doc))
        doc = dossier()
        doc['m2Candidates'] = [p for p in doc['m2Candidates'] if p['id'] != 'ccc-794']
        self.assertIn("m2Candidates: missing ['ccc-794']", problems(doc))
        doc = dossier()
        doc['runs'].append(copy.deepcopy(doc['runs'][0]))
        self.assertIn("runs: duplicate ['hearst-memorial-beach']", problems(doc))
        doc = dossier()
        doc['accessPoints'].append(copy.deepcopy(doc['accessPoints'][1]))
        self.assertIn("accessPoints: duplicate ['ccc-804']", problems(doc))
        doc = dossier()
        doc['runs'][1]['id'] = 'moss-landing'
        found = '\n'.join(problems(doc))
        self.assertIn("runs: missing ['morro-strand']", found)
        self.assertIn("runs: unexpected ['moss-landing']", found)

    def test_wrong_region_and_misfiled_access_point_refused(self):
        doc = dossier()
        doc['region'] = 'monterey'
        doc['accessPoints'][0]['runId'] = 'pismo-beach'
        doc['runs'][1]['accessIds'] = ['ccc-804']
        found = '\n'.join(problems(doc))
        self.assertIn('region must be morro-bay', found)
        self.assertIn('accessPoints[ccc-770]: runId must be hearst-memorial-beach', found)
        self.assertIn('runs[morro-strand]: accessIds must be', found)

    def test_missing_source_or_off_host_redirect_refused(self):
        doc = dossier()
        doc['sources'] = [s for s in doc['sources'] if s['id'] != 'cdfwRules']
        self.assertIn("sources: missing ['cdfwRules']", problems(doc))
        doc = dossier()
        doc['sources'][1]['finalUrl'] = 'https://example.org/x'
        self.assertIn('no off-host redirect', '\n'.join(problems(doc)))


class RawHashIsNotSemantic(unittest.TestCase):
    def test_raw_hash_change_is_not_semantic_change(self):
        doc = dossier()
        # a changed full NOAA response and metadata-only terms bytes, with the selected facts unchanged
        self.assertEqual(doc['sources'][0]['rawComparison']['state'], 'bytes-differ')
        self.assertEqual(doc['terms']['rawItem']['state'], 'changed')
        self.assertEqual(problems(doc), [])
        doc['runs'][0]['source']['selectedGeometry']['state'] = 'changed'
        doc['terms']['licenseInfo']['state'] = 'changed'
        found = '\n'.join(problems(doc))
        self.assertIn('runs[hearst-memorial-beach].source.selectedGeometry: marked changed but old and new are equal', found)
        self.assertIn('terms.licenseInfo: marked changed but old and new are equal', found)

    def test_raw_response_change_never_reads_as_run_change(self):
        doc = dossier()
        doc['runs'][2]['source']['rawResponseChange']['state'] = 'changed'
        self.assertIn('a raw response change is never a selected-run change', '\n'.join(problems(doc)))

    def test_unchanged_claim_needs_equal_values_and_rolls_up(self):
        doc = dossier()
        doc['runs'][0]['source']['selectedGeometry']['new']['sha256'] = H('9')
        doc['accessPoints'][0]['fields']['Name']['new'] = 'renamed'
        found = '\n'.join(problems(doc))
        self.assertIn('selectedGeometry: marked unchanged but old and new differ', found)
        self.assertIn('accessPoints[ccc-770].fields.Name: marked unchanged but old and new differ', found)
        doc = dossier()
        doc['accessPoints'][0]['fields']['Name'] = {'state': 'changed', 'old': 'a', 'new': 'b'}
        self.assertIn('accessPoints[ccc-770]: unchanged although a field is', '\n'.join(problems(doc)))


class FailedSources(unittest.TestCase):
    def test_failed_or_truncated_source_never_unchanged(self):
        doc = dossier()
        noaa = doc['sources'][0]
        noaa['acquisition']['state'] = 'failed'
        found = '\n'.join(problems(doc))
        self.assertIn('a failed source cannot carry a hash or byte count as if acquired', found)
        self.assertIn('must have rawComparison unverifiable', found)
        self.assertIn('runs[hearst-memorial-beach].source.selectedGeometry: unchanged although source', found)
        noaa.update(sha256=None, bytes=None, httpStatus=None)
        noaa['rawComparison']['state'] = 'unverifiable'
        for run in doc['runs']:
            for k in ('objectClass', 'fullFeatureGeometry', 'selectedGeometry'):
                run['source'][k] = {'state': 'failed', 'basis': 'NOAA layer not acquired'}
        self.assertEqual(problems(doc), [])

    def test_each_failed_source_blocks_its_dependents(self):
        for sid, path in (('access', 'accessPoints[ccc-770]'), ('terms', 'terms.licenseInfo'),
                          ('cdfwRules', 'rules.surfperch'), ('cdfwRules', 'runs[hearst-memorial-beach].legal')):
            with self.subTest(sid=sid, path=path):
                doc = dossier()
                src = next(s for s in doc['sources'] if s['id'] == sid)
                src.update(sha256=None, bytes=None, httpStatus=None)
                src['acquisition']['state'] = 'truncated'
                src['rawComparison']['state'] = 'unverifiable'
                self.assertIn(path + ': unchanged although source', '\n'.join(problems(doc)))

    def test_absent_bytes_or_hash_is_not_a_successful_acquisition(self):
        for field, bad in (('sha256', None), ('sha256', 'xyz'), ('bytes', 0), ('httpStatus', 206), ('fetchedAt', 'yesterday')):
            with self.subTest(field=field, bad=bad):
                doc = dossier()
                doc['sources'][2][field] = bad
                self.assertIn('acquired needs sha256, positive bytes, HTTP 200 and a UTC fetchedAt', '\n'.join(problems(doc)))
        doc = dossier()
        doc['sources'][3]['acquisition']['state'] = 'partial'
        self.assertIn('acquisition.state must be acquired, failed or truncated', '\n'.join(problems(doc)))


class NoRenewalOrLeak(unittest.TestCase):
    def test_no_review_renewal_or_private_inventory_leak(self):
        doc = dossier()
        doc['approval']['status'] = 'approved'
        self.assertIn('approval.status must be none', '\n'.join(problems(doc)))
        for mutate, expect in (
                (lambda d: d['runs'][0].update(reviewedAt='2026-11-04T00:00:00Z'), "field 'reviewedAt'"),
                (lambda d: d.update(renewedAt=AT), "field 'renewedAt'"),
                (lambda d: d['runs'][0].update(reviewExpiresAt=AT), "field 'reviewExpiresAt'"),
                (lambda d: d['holds'].append('ok'), None),
                (lambda d: d['m2Candidates'][0].update(Description='trail leads seaward'), "field 'Description'"),
                (lambda d: d['m2Candidates'][0].update(PHONE_NMBR='805 555 0100'), "field 'PHONE_NMBR'"),
                (lambda d: d['m2Candidates'][0].update(photos=['a.jpg']), "field 'photos'"),
                (lambda d: d['m2Candidates'][0].update(GoogleMaps_Location='x'), "field 'GoogleMaps_Location'"),
                (lambda d: d['m2Candidates'][0].update(note='call 805-555-0100'), 'raw inventory link or phone'),
                (lambda d: d['m2Candidates'][0].update(note='https://www.google.com/maps/search/?api=1&query=35,-120'), 'raw inventory link or phone'),
                (lambda d: d['terms'].update(note='review renewed for 30 days'), 'approval or renewal wording'),
                (lambda d: d['runs'][0]['legal'].update(basis='legality approved'), 'approval or renewal wording'),
                (lambda d: d['rules']['licenseScope'].update(basis='Certified current'), 'approval or renewal wording')):
            with self.subTest(expect=expect):
                doc = dossier()
                mutate(doc)
                found = '\n'.join(problems(doc))
                if expect:
                    self.assertIn(expect, found)
                else:
                    self.assertEqual(found, '')

    def test_prose_holds_may_say_no_renewal(self):
        doc = dossier()
        doc['approval']['statement'] = 'This renews nothing and approves no legality.'
        doc['holds'] = ['No renewal or approval is given.']
        self.assertEqual(problems(doc), [])

    def test_checker_makes_zero_outbound_calls(self):
        banned = {'socket', 'ssl', 'http', 'urllib.request', 'urllib3', 'requests', 'httpx', 'aiohttp', 'ftplib', 'smtplib', 'subprocess'}
        imported = set()
        for node in ast.walk(ast.parse((ROOT / 'scripts/check_shore_reread_dossier.py').read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual({m for m in imported if any(m == b or m.startswith(b + '.') for b in banned)}, set())

        def refuse(*args, **kwargs):
            raise AssertionError('outbound network call')
        with mock.patch.object(socket, 'socket', side_effect=refuse), mock.patch.object(socket, 'create_connection', side_effect=refuse):
            self.assertEqual(problems(dossier()), [])


class CommandLine(unittest.TestCase):
    def run_main(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'r.json'
            if text is not None:
                path.write_text(text, encoding='utf-8')
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = checker.main([str(path)])
            return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        code, out, _ = self.run_main(json.dumps(dossier()))
        self.assertEqual((code, out.startswith('OK')), (0, True))
        bad = dossier()
        bad['region'] = 'elsewhere'
        code, out, _ = self.run_main(json.dumps(bad))
        self.assertEqual((code, 'FAIL region must be morro-bay' in out), (1, True))
        self.assertEqual(self.run_main('{not json')[0], 2)
        self.assertEqual(self.run_main(None)[0], 2)
        self.assertEqual(checker.main([]), 2)
        self.assertEqual(problems([]), ['dossier must be a JSON object'])


if __name__ == '__main__':
    unittest.main()
