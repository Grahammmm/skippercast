"""public_url records the same explicit model that sample() queries."""
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from skippercast.forecast import local

BASE = {'latitude': '35', 'longitude': '-123', 'hourly': 'wave_height'}


def sampled_query(model, params):
    with mock.patch.object(local, 'local_root', return_value='/x'), \
            mock.patch.object(local, 'run_sampler', return_value={}) as sampler:
        local.sample(model, params)
    return sampler.call_args.args[2]


def models_of(url):
    return parse_qs(urlsplit(url).query)['models']


class PublicUrlModelTests(unittest.TestCase):
    def test_explicit_model_overrides_conflicting_provenance_selector(self):
        params = {**BASE, 'models': 'ncep_gfswave016'}
        url = local.public_url('ecmwf_wam', params)
        self.assertEqual(models_of(url), ['ecmwf_wam'])
        self.assertEqual(models_of(url), parse_qs(sampled_query('ecmwf_wam', params))['models'])

    def test_omitted_selector_is_recorded_once(self):
        url = local.public_url('ecmwf_wam', BASE)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['models'], ['ecmwf_wam'])
        self.assertEqual(query['hourly'], ['wave_height'])
        self.assertEqual(query['latitude'], ['35'])
        self.assertEqual(url, f"{local.API}/v1/marine?{sampled_query('ecmwf_wam', BASE)}")

    def test_matching_selector_preserves_existing_url_bytes(self):
        params = {**BASE, 'models': 'ncep_gfswave016'}
        self.assertEqual(
            local.public_url('ncep_gfswave016', params),
            'https://skippercast.com/api/om/v1/marine?latitude=35&longitude=-123'
            '&hourly=wave_height&models=ncep_gfswave016')
        self.assertIn('/v1/marine?', local.public_url('ecmwf_wam', {**BASE, 'models': 'ecmwf_wam'}))
        self.assertIn('/v1/forecast?', local.public_url('gfs_seamless', {**BASE, 'models': 'gfs_seamless'}))

    def test_encoding_and_caller_mapping_are_preserved(self):
        params = {'latitude': '35,36', 'longitude': '-123,-122', 'hourly': 'a b+c'}
        before = dict(params)
        url = local.public_url('ecmwf_wam', params)
        self.assertEqual(params, before)
        self.assertIn('latitude=35%2C36', url)
        self.assertIn('hourly=a+b%2Bc', url)
        sampled_query('ecmwf_wam', params)
        self.assertEqual(params, before)


if __name__ == '__main__':
    unittest.main()
