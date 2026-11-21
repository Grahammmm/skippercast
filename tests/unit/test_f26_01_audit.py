"""F26-01 contract controls (offline), not a change to any research replay.

Run with pytest for the supported outcomes. To observe the current default
callers, run `python -m tests.unit.test_f26_01_audit` with the survey stack.
The read-only probe prints counts/booleans only and exits 1 on a privacy gap;
it intentionally is not a required pytest check while the callers are unfixed.
"""

from collections import Counter
import io
import json
import socket
import urllib.request
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from research.scripts import audit_csumb_vdatum_bridge as bridge


PRIVATE_MARKER = 'synthetic-held-response-not-for-receipt'


def _no_network(*args, **kwargs):
    raise AssertionError('Unexpected real transport in offline footprint fixture')


def _datum_sample(x, y):
    return {'region': 'WESTCOAST', 's_h_frame': 'NAD83_2011', 's_v_frame': 'NAVD88',
            's_v_geoid': 'geoid09', 's_v_unit': 'm', 't_h_frame': 'IGS14',
            't_v_frame': 'MLLW', 't_v_unit': 'm', 's_x': x, 's_y': y,
            't_x': x, 't_y': y, 't_z': 1.25, 'uncertainty': 0.5,
            'private_marker': PRIVATE_MARKER}


class _JsonResponse(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'application/json'}


class _OfflineObservation:
    def __init__(self):
        self.urls = []
        self.requests = Counter()

    def urlopen(self, request, *, timeout):
        # This is the transport boundary, after the caller prepares the URL.
        url = request.full_url
        self.urls.append(url)
        query = parse_qs(urlsplit(url).query)
        if {'s_x', 's_y'} <= query.keys():
            self.requests['coordinate_queries'] += 1
            payload = _datum_sample(query['s_x'][0], query['s_y'][0])
        elif 'bbox' in query:
            self.requests['envelope_queries'] += 1
            payload = {'type': 'FeatureCollection', 'numberReturned': 0,
                       'totalFeatures': 0, 'features': [], 'private_marker': PRIVATE_MARKER}
        else:
            raise AssertionError('Unexpected request shape in offline footprint fixture')
        return _JsonResponse(json.dumps(payload).encode())

    def receipt(self, public):
        serialized = json.dumps(public)
        return {
            'coordinate_queries': self.requests['coordinate_queries'],
            'envelope_queries': self.requests['envelope_queries'],
            'private_response_in_output': PRIVATE_MARKER in serialized,
            'raw_request_url_in_output': ('"request_url"' in serialized
                                          or any(url in serialized for url in self.urls)),
        }


def _local_control(approved_samples, point):
    """Reference outcome only; no approval of real samples or provider access."""
    sample = approved_samples.get(point)
    if sample is None:
        return {'status': 'unavailable'}
    x, y = point
    return bridge.assess(sample, x, y, 'NAD83_2011')


@pytest.mark.parametrize(('held', 'expected'), [
    (True, {'status': 'sample_available', 'offset_m': 1.25, 'vdatum_uncertainty_m': 0.5}),
    (False, {'status': 'unavailable'}),
], ids=['approved-local-replay', 'no-held-sample'])
def test_offline_footprint_contract(held, expected):
    point = (10.0, 20.0)  # Synthetic, outside the audited areas.
    samples = {point: _datum_sample(*point)} if held else {}
    observed = _OfflineObservation()
    with (patch.object(bridge, 'urlopen', observed.urlopen),
          patch.object(urllib.request, 'urlopen', _no_network),
          patch.object(socket.socket, 'connect', _no_network),
          patch.object(socket, 'getaddrinfo', _no_network)):
        public = _local_control(samples, point)
    assert public == expected
    assert not any(observed.receipt(public).values())


def _observe_baseline():
    # Only the opt-in probe needs native GIS packages. No production input files.
    from shapely.geometry import box, mapping, shape
    from research.scripts import audit_bss03_datum_footprint as bss
    from research.scripts import audit_ciap_video_block_overlap as ciap

    features = [{'geometry': mapping(box(x, 1_000_000, x + 100, 1_000_100)),
                 'properties': {}} for x in (500_000, 500_200, 500_400)]
    blocks = {'scope': 'private-bss03-camera-100m-research-blocks', 'crs': 'EPSG:26910',
              'features': features}
    access = {'scope': 'bss03-original-camera-100m-access-triage',
              'private_block_fingerprint': bss.fingerprint(features)}
    bss_trace, ciap_trace = _OfflineObservation(), _OfflineObservation()
    with (patch.object(bridge, 'urlopen', bss_trace.urlopen),
          patch.object(ciap, 'urlopen', ciap_trace.urlopen),
          patch.object(urllib.request, 'urlopen', _no_network),
          patch.object(socket.socket, 'connect', _no_network),
          patch.object(socket, 'getaddrinfo', _no_network),
          patch.object(ciap, 'BLOCKS', {'synthetic': ('unused', blocks['crs'], len(features))}),
          patch.object(ciap, 'load_blocks', return_value=[shape(f['geometry']) for f in features])):
        bss_public, _held = bss.compile_review(blocks, access)
        ciap_public = ciap.build()
    return {'bss03_vdatum': bss_trace.receipt(bss_public),
            'ciap_video': ciap_trace.receipt(ciap_public)}


if __name__ == '__main__':
    observations = _observe_baseline()
    print(json.dumps(observations, sort_keys=True))
    raise SystemExit(int(any(any(result.values()) for result in observations.values())))
