"""Original-producer rights review, independent of distributor or fish presence."""
from copy import deepcopy
from datetime import date, timedelta
import unittest
from skippercast.seafloor.rights import CSUMB_LICENSE, CSUMB_POLICY, CSUMB_CREDIT, source_rights, feature_rights
from skippercast.seafloor.manifest import qualify_row, validate_manifest
from tests.contract.test_seafloor_manifest import ROWS
from tests._support import ROOT, NOW


def csumb_row():
    row = deepcopy(next(r for r in ROWS if r['status'] == 'usable'))
    row.update(publisher='CSUMB (NOAA NCEI distributor)', license=CSUMB_LICENSE,
               url='https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/BSS_Block03/original.tar.gz')
    row['rights_review'] = {'producer':'CSUMB SFML', 'policy_url':CSUMB_POLICY,
        'source_sha256':row['sha256'], 'reviewed_on':NOW.date().isoformat(),
        'allowed_use':'noncommercial', 'attribution':CSUMB_CREDIT,
        'navigation_use':False, 'for_profit_permission':'required-not-obtained'}
    return row


class SourceRightsTests(unittest.TestCase):
    def test_reviewed_ventresca_original_can_qualify_with_same_producer_restrictions(self):
        row = csumb_row()
        row['url'] = ('https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/'
                      'SCC_Block01/multibeam/data/version2/products/SCC_Block01_additional_products.tar.gz')
        receipt = dict(row['adapter_review'], source_id=row['id'],
                       source_bytes=row['bytes'], horizontal_crs=row['horizontal_crs'])
        public = qualify_row(row, receipt, rights_url=CSUMB_POLICY)
        validate_manifest({'surveys': [public]}, ROOT)
        rights = source_rights(public, today=NOW.date())
        self.assertEqual(rights['commercial_use'], 'permission-required')
        self.assertFalse(rights['navigation_use'])
        self.assertEqual(rights['attribution'], CSUMB_CREDIT)
        with self.assertRaisesRegex(ValueError, 'For-profit'):
            source_rights(public, use='for-profit', today=NOW.date())
        for change in ({'source_sha256': '0'*64}, {'producer': 'NOAA'},
                       {'allowed_use': 'commercial'}, {'navigation_use': True}):
            bad = deepcopy(row)
            bad['rights_review'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                source_rights(bad, today=NOW.date())

    def test_unreviewed_or_lookalike_cruise_archives_remain_rejected(self):
        row = csumb_row()
        for url in (
            'https://data.ngdc.noaa.gov/platforms/ocean/ships/another_cruise/original.tar.gz',
            'https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca-other/original.tar.gz',
            'https://data.ngdc.noaa.gov.evil.test/platforms/ocean/ships/ventresca/original.tar.gz',
            'http://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/original.tar.gz',
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                source_rights(dict(row, url=url), today=NOW.date())

    def test_checked_noncommercial_producer_contract_can_qualify_without_inventing_public_domain(self):
        row=csumb_row()
        receipt=dict(row['adapter_review'], source_id=row['id'], source_bytes=row['bytes'], horizontal_crs=row['horizontal_crs'])
        public=qualify_row(row,receipt,rights_url=CSUMB_POLICY)
        self.assertEqual(public['license'],CSUMB_LICENSE)
        self.assertEqual(public['status'],'usable')
        validate_manifest({'surveys':[public]},ROOT)
        rights=source_rights(public,today=NOW.date())
        self.assertEqual(rights['commercial_use'],'permission-required')
        self.assertFalse(rights['navigation_use'])
        self.assertEqual(rights['attribution'],CSUMB_CREDIT)
        with self.assertRaisesRegex(ValueError,'For-profit'):
            source_rights(public,use='for-profit',today=NOW.date())
        with self.assertRaisesRegex(ValueError,'Unknown deployment'):
            source_rights(public,use='unknown',today=NOW.date())
        with self.assertRaisesRegex(ValueError,'policy URL'):
            qualify_row(row,receipt,rights_url='https://example.test/not-the-producer-policy')

    def test_missing_conflicting_or_fabricated_permissions_do_not_qualify(self):
        base=csumb_row()
        cases=[{'source_sha256':'0'*64},{'producer':'NOAA'},{'allowed_use':'commercial'},
               {'attribution':''},{'navigation_use':True},{'for_profit_permission':'obtained'},
               {'policy_url':'https://example.test/terms'}, {'reviewed_on':'2026-99-99'},
               {'reviewed_on':(NOW.date()+timedelta(days=1)).isoformat()}]
        for change in cases:
            with self.subTest(change=change):
                row=deepcopy(base);row['rights_review'].update(change)
                with self.assertRaises(ValueError):source_rights(row,today=NOW.date())
        for change in ({'rights_review':{}},{'publisher':'NOAA'},{'url':'https://example.test/original'}, {'license':'unknown'}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):source_rights(dict(base,**change),today=NOW.date())

    def test_mixed_source_terms_and_unknown_contributors_cannot_disappear(self):
        restricted=csumb_row();restricted['id']='csumb'
        federal=deepcopy(next(r for r in ROWS if r['status']=='usable'));federal['id']='usgs'
        sources={r['id']:r for r in (restricted,federal)}
        rights=feature_rights(['usgs','csumb','csumb'],sources)
        self.assertEqual(len(rights),2)
        self.assertEqual({r['license'] for r in rights},{CSUMB_LICENSE,'public-domain-us-gov'})
        for ids in ([],['csumb','missing']):
            with self.assertRaisesRegex(ValueError,'incomplete'):feature_rights(ids,sources)
