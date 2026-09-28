"""Refresh original spatial restriction sources into a private dated snapshot.

Reuses the statewide CDFW and NOAA collectors. Security boundaries require a
reviewed local catalog: new geography is held until its restrictions are reviewed.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from pyproj import Geod, Transformer
from shapely.geometry import Polygon, box, mapping

from skippercast.platform.contracts import REPO, atomic_json, read_json
from .io import sha256
from .screen import VERSION


def ecfr_bytes(url):
    if not url.startswith('https://www.ecfr.gov/api/versioner/v1/'):
        raise ValueError('Unreviewed eCFR endpoint')
    request = Request(url, headers={'Accept-Encoding': 'gzip', 'User-Agent': 'SkipperCast/1.0'})
    with urlopen(request, timeout=30) as response:
        if response.url != url:
            raise ValueError('eCFR redirect refused')
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError('Oversized eCFR response')
        if response.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
    if len(raw) > 5_000_000:
        raise ValueError('Oversized eCFR document')
    return raw


def security_layer(config, getter=ecfr_bytes):
    titles_url = 'https://www.ecfr.gov/api/versioner/v1/titles'
    raw = getter(titles_url)
    titles = json.loads(raw)['titles']
    title = next(row for row in titles if row['number'] == 33)
    issue = title['up_to_date_as_of']
    features, receipts = [], []
    for zone in config['security_zones']:
        url = f"https://www.ecfr.gov/api/versioner/v1/full/{issue}/title-33.xml?section={zone['section']}"
        body = getter(url)
        section = ET.fromstring(body)
        digest = hashlib.sha256(body).hexdigest()
        if section.get('N') != zone['section'] or digest != zone['reviewed_xml_sha256']:
            raise ValueError('Security text changed; boundary review required')
        if zone['geometry_method'] != 'nad83-geodesic-circle':
            raise ValueError('Unsupported security boundary method')
        lon, lat = zone['center_nad83']
        geod = Geod(ellps='GRS80')
        # One-meter outward approximation avoids an inscribed chord cutting
        # inside the official 2,000-yard circle. This is labeled planning margin.
        points = [geod.fwd(lon, lat, angle, zone['radius_m']+1)[:2] for angle in range(360)]
        convert = Transformer.from_crs(4269, 4326, always_xy=True)
        geometry = Polygon([convert.transform(*p) for p in points])
        features.append({'type': 'Feature', 'geometry': mapping(geometry),
                         'properties': {'id': zone['id'], 'source_url': url,
                                        'datum': 'NAD83', 'planning_margin_m': 1}})
        receipts.append({'url': url, 'sha256': digest, 'up_to_date_as_of': issue})
    return {'type': 'FeatureCollection', 'features': features}, {
        'titles_url': titles_url, 'titles_sha256': hashlib.sha256(raw).hexdigest(),
        'sections': receipts, 'up_to_date_as_of': issue}


def refresh(root=REPO, *, mpa_collect=None, federal_collect=None, getter=ecfr_bytes):
    # Repository scripts already contain complete-inventory and transport checks.
    if mpa_collect is None:
        from scripts.collect_cdfw_mpas import collect as mpa_collect
    if federal_collect is None:
        from scripts.collect_noaa_groundfish_areas import collect as federal_collect
    root = Path(root)
    config = read_json(root/'catalog/seafloor-screen.json')
    destination = root/'var/seafloor/screen'
    destination.mkdir(parents=True, exist_ok=True)
    try:
        mpa, federal = mpa_collect(), federal_collect()
        security, evidence = security_layer(config, getter)
        checked = datetime.now(timezone.utc).isoformat()
        data = {'version': VERSION, 'checked_at': checked,
                'reviewed_reaches': config['reviewed_reaches'],
                'scope': mapping(box(*config['bounds_wgs84'])), 'layers': {},
                'policy_sha256': sha256(root/'catalog/seafloor-screen.json')}
        sources = [('cdfw-mpa', mpa['data']['geojson'], mpa['checked_at'], mpa['data']['source_url']),
                   ('noaa-federal', federal, federal['retrieved_at'], federal['service_url']),
                   ('security', security, checked, evidence['sections'][0]['url'])]
        for ident, geo, stamp, url in sources:
            # Content-addressed files keep the last snapshot coherent if a later
            # collector fails. Never overwrite bytes referenced by a receipt.
            digest = hashlib.sha256(json.dumps(geo, sort_keys=True).encode()).hexdigest()
            path = destination/f'{ident}-{digest}.json'
            atomic_json(path, geo)
            data['layers'][ident] = {'status': 'ok', 'checked_at': stamp, 'file': path.name,
                'sha256': sha256(path), 'source_url': url, 'feature_count': len(geo['features'])}
        data['layers']['security']['evidence'] = evidence
        atomic_json(destination/'source-receipts.json', {'mpa': mpa, 'security': evidence})
        atomic_json(destination/'snapshot.json', data, indent=2)
        (destination/'refresh-failure.json').unlink(missing_ok=True)
        return data
    except Exception as error:
        # Retained geometry is useful for diagnosis, but a failed current refresh
        # cannot silently promote candidates using a formerly successful snapshot.
        atomic_json(destination/'refresh-failure.json', {
            'checked_at': datetime.now(timezone.utc).isoformat(), 'error': str(error)[:400]})
        raise
