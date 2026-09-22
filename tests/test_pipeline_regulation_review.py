from copy import deepcopy
from datetime import datetime, timezone, timedelta
import gzip
from io import BytesIO
import json
from unittest import TestCase
from unittest.mock import patch

from skippercast.platform.contracts import REPO
from skippercast.pipeline import regulations as rules
from skippercast.pipeline.collect import Client
from skippercast.pipeline.parsers import page_watch
from skippercast.pipeline.regulation_review import approved_registry, coverage


class ReviewGate(TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 22, 18, tzinfo=timezone.utc)
        self.j = json.loads((REPO/'jurisdictions/california-southern.json').read_text())
        self.r = json.loads((REPO/'dist'/self.j['regulations_asset']).read_text())
        self.packet = {'jurisdiction_id': self.j['id'], 'sources': {}}
        self.decision = {'jurisdiction_id': self.j['id'], 'revision': 'fixture',
            'reviewed_at': self.now.isoformat(), 'reviewed_species': list(self.r['species']),
            'rules_content_sha256': rules.content_hash(self.r), 'sources': {}}
        for ident, spec in self.r['sources'].items():
            self.packet['sources'][ident] = {'url': spec['url'], 'status': 'ok',
                'checked_at': self.now.isoformat(), 'data_retrieved_at': (self.now-timedelta(minutes=1)).isoformat(),
                'data': {'content_sha256': 'a'*64, 'normalization': spec['normalization']}}
            self.decision['sources'][ident] = {'decision': 'approve', 'content_sha256': 'a'*64,
                'note': 'Fixture review: checked the specific source and its legal scope.'}

    def apply(self):
        return approved_registry(self.r, self.j, self.packet, self.decision, self.now)

    def test_decision_is_bound_to_region_content_species_source_and_retrieval(self):
        for mutation in (
            lambda: self.decision.update(jurisdiction_id='california-central'),
            lambda: self.r['species']['halibut'].update(bag='invented limit'),
            lambda: self.decision['reviewed_species'].remove('lobster'),
            lambda: self.packet['sources']['rules-book'].update(url='https://example.org/book.pdf'),
            lambda: self.packet['sources']['rules-book'].update(data_retrieved_at=(self.now-timedelta(days=2)).isoformat()),
            lambda: self.decision.update(reviewed_at=(self.now-timedelta(hours=1)).isoformat()),
            lambda: self.packet['sources']['rules-book']['data'].update(content_sha256=None),
            lambda: self.packet['sources']['rules-book']['data'].update(normalization='another-parser'),
        ):
            self.setUp(); mutation()
            with self.assertRaises(ValueError): self.apply()

    def test_failed_ancillary_source_can_be_held_without_approving_it(self):
        key = 'rules-navy-sci'
        self.packet['sources'][key].update(status='failed', data=None, data_retrieved_at=None)
        self.decision['sources'][key].update(decision='hold', content_sha256=None,
            note='Access failed; current Navy law and operational access must be checked separately.')
        result = self.apply()
        self.assertIsNone(result['sources'][key]['approved_content_sha256'])
        report = coverage(result, self.packet['sources'], self.now)
        self.assertEqual(report['species']['halibut']['issues'], [])
        self.assertTrue(any(key in a['issues'] for a in report['areas'].values()))
        self.decision['sources'][key]['decision'] = 'approve'
        with self.assertRaises(ValueError): self.apply()

    def test_post_review_edits_and_wrong_source_identity_never_stay_approved(self):
        approved = self.apply()
        self.assertEqual(approved['rules_review_status'], 'reviewed')
        for change in (
            lambda r: r['species']['halibut'].update(bag='changed'),
            lambda r: r['species']['halibut']['windows'][0].update(end='2026-11-30'),
            lambda r: r['area_notices'][0].update(note='changed'),
            lambda r: r['sources']['rules-book'].update(url='https://nrm.dfg.ca.gov/other'),
        ):
            changed = deepcopy(approved); change(changed)
            self.assertEqual(rules.regulatory_snapshot(self.packet['sources'], self.now, changed)['rules_review_status'], 'content-needs-review')
        for field, value, expected in [('url','https://example.org','identity-mismatch')]:
            self.packet['sources']['rules-book'][field] = value
            self.assertEqual(rules.regulatory_snapshot(self.packet['sources'],self.now,approved)['checks']['rules-book']['status'],expected)

    def test_document_link_changes_are_watched_even_when_link_text_is_unchanged(self):
        a = page_watch('<p>rules</p><a href="one.pdf">current booklet</a>', ['rules'])
        b = page_watch('<p>rules</p><a href="two.pdf">current booklet</a>', ['rules'])
        self.assertNotEqual(a['content_sha256'], b['content_sha256'])
        c = page_watch('<p>rules</p><!--old law <a href="old.pdf">old</a>--><a href="one.pdf">current booklet</a>', ['rules'])
        self.assertEqual(a['content_sha256'], c['content_sha256'])
        with self.assertRaises(ValueError): page_watch('<!--obsolete lobster law--><p>unrelated</p>', ['lobster'])
        self.assertTrue(rules.valid_window({'start':'2026-10-02','end':'2026-12-31','start_at':'2026-10-03T01:00:00Z'}))

    def test_another_region_or_changed_footprint_cannot_inherit_approval(self):
        from skippercast.platform.contracts import load_region
        region = load_region('southern-california')
        rules.validate_region_binding(self.j,self.r,region)
        region['fishing_bounds'][3] = 35.0
        with self.assertRaises(ValueError): rules.validate_region_binding(self.j,self.r,region)

    def test_scheduled_report_identifies_expired_review_periods(self):
        result = self.apply()
        self.assertTrue(coverage(result, self.packet['sources'], self.now)['valid_for_current_date'])
        self.assertFalse(coverage(result, self.packet['sources'], datetime(2027,1,1,8,tzinfo=timezone.utc))['valid_for_current_date'])


class FederalAndCompressedSources(TestCase):
    def test_ecfr_uses_supported_current_section_and_rejects_bad_metadata_or_text(self):
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        meta = {'meta': {'import_in_progress': False}, 'titles': [{'number':50,
            'latest_issue_date':'2026-09-15','up_to_date_as_of':'2026-09-18'}]}
        body = '<DIV8 TYPE="SECTION" N="660.721"><HEAD>Albacore and bluefin limits</HEAD><P>Two bluefin.</P></DIV8>'
        class Fake:
            def __init__(self): self.now=now; self.requests=[]
            def get(self, url, as_json=False): return deepcopy(meta) if as_json else body
        spec = {'title':50,'section':'660.721','keywords':['bluefin']}
        with patch.dict(rules._ecfr_index, {}, clear=True):
            result = rules._ecfr_section(Fake(),spec)
            self.assertEqual(result['up_to_date_as_of'],'2026-09-18')
        for bad in ('<html>bluefin</html>',body.replace('660.721','660.999'), '<!DOCTYPE x>'+body):
            with patch.dict(rules._ecfr_index, {}, clear=True):
                previous=body;body=bad
                with self.assertRaises((ValueError,rules.ElementTree.ParseError)):rules._ecfr_section(Fake(),spec)
                body=previous
        for current, importing in [('2026-08-01',False),('2026-09-18',True)]:
            meta['titles'][0]['up_to_date_as_of']=current;meta['meta']['import_in_progress']=importing
            with patch.dict(rules._ecfr_index, {}, clear=True):
                with self.assertRaises(ValueError):rules._ecfr_section(Fake(),spec)

    def test_gzip_is_supported_and_decompressed_size_is_bounded(self):
        class Response(BytesIO):
            status=200;url='https://www.ecfr.gov/api/test'
            headers={'Content-Encoding':'gzip','Content-Type':'application/json'}
        class Opener:
            def __init__(self, body):self.body=body
            def open(self, request, timeout):
                self.request=request
                return Response(gzip.compress(self.body))
        for body, succeeds in [(b'{"ok":true}',True),(b'x'*5_000_001,False)]:
            c=Client(datetime(2026,9,22,tzinfo=timezone.utc));opener=Opener(body)
            with patch('skippercast.pipeline.collect.check_public_address'),patch('skippercast.pipeline.collect.build_opener',return_value=opener):
                if succeeds:
                    self.assertEqual(c.get(Response.url,as_json=True),{'ok':True})
                    self.assertEqual(opener.request.get_header('Accept-encoding'),'gzip')
                    self.assertIn('compressed_bytes',c.requests[0])
                else:
                    with self.assertRaises(ValueError):c.get(Response.url)
