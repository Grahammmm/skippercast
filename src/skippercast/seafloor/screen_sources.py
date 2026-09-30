"""Refresh original spatial restriction sources into a private dated snapshot.

Reuses the statewide CDFW and NOAA collectors. Security boundaries require a
reviewed local catalog: new geography is held until its restrictions are reviewed.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from pyproj import Geod, Transformer
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform

from skippercast import http
from skippercast.platform.contracts import REPO, atomic_json, read_json
from .io import sha256
from .screen import VERSION


def ecfr_bytes(url, session=None):
    if not url.startswith('https://www.ecfr.gov/api/versioner/v1/'):
        raise ValueError('Unreviewed eCFR endpoint')
    try:
        response = (session or http.default_session()).get(
            url, headers={'Accept-Encoding': 'gzip'}, timeout=30, max_bytes=5_000_000,
            follow_redirects=False, allowed_hosts=['www.ecfr.gov'])
    except http.BodyTooLarge as error:
        raise ValueError('Oversized eCFR response') from error
    except http.ContractError as error:
        if 'Redirect refused' in str(error):
            raise ValueError('eCFR redirect refused') from error
        raise
    return response.body


_DMS_PAIR = re.compile(
    r'latitude\s+(\d{1,2})°(\d{1,2})′(\d{1,2})″[,;]?\s*'
    r'longitude\s+(\d{1,3})°(\d{1,2})′(\d{1,2})″')


def reviewed_dms_coastal_envelope(zone, section):
    """Over-cover a published coastal zone when its landward edge is shoreline.

    The regulation gives seaward vertices but no shoreline polyline or coordinate
    datum. Closing on a reviewed inland meridian and buffering outward is
    intentionally conservative; it may hold safe water, never certify the
    regulation's exact boundary or a launch-day opening.
    """
    paragraphs = [''.join(node.itertext()) for node in section.iter('P')
                  if zone['paragraph_marker'] in ''.join(node.itertext())]
    if len(paragraphs) != 1:
        raise ValueError('Reviewed security-zone paragraph missing or ambiguous')
    found = [[int(part) for part in pair] for pair in _DMS_PAIR.findall(paragraphs[0])]
    if len(found) < 3 or found != zone['expected_pairs_dms']:
        raise ValueError('Published security-zone coordinates changed')
    if zone['source_datum'] != 'unknown' or zone['longitude_hemisphere'] != 'W':
        raise ValueError('Unreviewed coastal-zone coordinate interpretation')
    def decimal(degrees, minutes, seconds):
        if not (0 <= minutes < 60 and 0 <= seconds < 60):
            raise ValueError('Invalid published DMS coordinate')
        return degrees + minutes/60 + seconds/3600
    vertices = [(-decimal(*pair[3:]), decimal(*pair[:3])) for pair in found]
    inland = zone['inland_closure_lon']
    margin = zone['planning_margin_m']
    if (not all(inland > lon + .05 for lon, _ in (vertices[0], vertices[-1]))
            or not 0 < margin <= 500):
        raise ValueError('Unreviewed coastal-zone safety envelope')
    south, north = vertices[-1], vertices[0]
    outline = Polygon(vertices + [(inland, south[1]), (inland, north[1])])
    if not outline.is_valid or outline.is_empty:
        raise ValueError('Invalid coastal-zone safety envelope')
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    unproject = Transformer.from_crs(3310, 4326, always_xy=True).transform
    return transform(unproject, transform(project, outline).buffer(margin))


def reviewed_dms_polygon(zone, section):
    """Exclude an explicitly closed, reviewed NAD83 navigation-area polygon.

    Conditional harbor closure is not modeled as permanently active. Keeping
    the entrance out of fishing recommendations is a conservative planning
    choice; it does not prohibit transit when the Coast Guard permits it.
    """
    text = ' '.join(''.join(section.itertext()).split())
    start, end = zone['paragraph_marker'], zone['end_marker']
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError('Reviewed navigation-area paragraph missing or ambiguous')
    selected = text.split(start, 1)[1].split(end, 1)[0]
    expression = r'(\d{1,2})°(\d{1,2})′(\d{1,2})″\s*N,?\s*(\d{1,3})°(\d{1,2})′(\d{1,2})″\s*W'
    found = [[int(part) for part in pair] for pair in re.findall(expression, selected)]
    if len(found) < 3 or found != zone['expected_pairs_dms']:
        raise ValueError('Published navigation-area coordinates changed')
    if zone['source_datum'] != 'NAD83' or not 0 < zone['planning_margin_m'] <= 100:
        raise ValueError('Unreviewed navigation-area coordinate interpretation')
    def decimal(degrees, minutes, seconds):
        if not 0 <= minutes < 60 or not 0 <= seconds < 60:
            raise ValueError('Invalid published DMS coordinate')
        return degrees + minutes/60 + seconds/3600
    vertices = [(-decimal(*pair[3:]), decimal(*pair[:3])) for pair in found]
    outline = Polygon(vertices)
    if not outline.is_valid or outline.is_empty:
        raise ValueError('Invalid reviewed navigation-area polygon')
    project = Transformer.from_crs(4269, 3310, always_xy=True).transform
    unproject = Transformer.from_crs(3310, 4326, always_xy=True).transform
    return transform(unproject, transform(project, outline).buffer(zone['planning_margin_m']))


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
        if zone['geometry_method'] == 'nad83-geodesic-circle':
            lon, lat = zone['center_nad83']
            geod = Geod(ellps='GRS80')
            # One-meter outward approximation avoids an inscribed chord cutting
            # inside the official 2,000-yard circle. This is labeled planning margin.
            points = [geod.fwd(lon, lat, angle, zone['radius_m']+1)[:2]
                      for angle in range(360)]
            convert = Transformer.from_crs(4269, 4326, always_xy=True)
            geometry = Polygon([convert.transform(*p) for p in points])
            datum, margin = 'NAD83', 1
        elif zone['geometry_method'] == 'reviewed-dms-coastal-envelope':
            geometry = reviewed_dms_coastal_envelope(zone, section)
            datum, margin = 'unknown', zone['planning_margin_m']
        elif zone['geometry_method'] == 'reviewed-dms-polygon':
            geometry = reviewed_dms_polygon(zone, section)
            datum, margin = zone['source_datum'], zone['planning_margin_m']
        else:
            raise ValueError('Unsupported security boundary method')
        features.append({'type': 'Feature', 'geometry': mapping(geometry),
                         'properties': {'id': zone['id'], 'source_url': url,
                                        'datum': datum, 'planning_margin_m': margin}})
        receipts.append({'url': url, 'sha256': digest, 'up_to_date_as_of': issue})
    # Out-of-scope fixed zones and moving-vessel rules still need a current
    # hash check. A changed or missing section invalidates the release screen;
    # no fabricated stationary geometry is created for a mobile restriction.
    for review in config.get('reviewed_notice_sections', []):
        if (review.get('classification') not in
                {'outside-reviewed-scope', 'trip-time-vessel-restriction'}
                or not review.get('review_basis')
                or not re.fullmatch(r'[0-9]+\.[0-9]+', review.get('section', ''))):
            raise ValueError('Invalid reviewed notice section')
        url = f"https://www.ecfr.gov/api/versioner/v1/full/{issue}/title-33.xml?section={review['section']}"
        body = getter(url)
        section = ET.fromstring(body)
        digest = hashlib.sha256(body).hexdigest()
        if section.get('N') != review['section'] or digest != review['reviewed_xml_sha256']:
            raise ValueError('Reviewed notice text changed; scope review required')
        receipts.append({'url': url, 'sha256': digest, 'up_to_date_as_of': issue,
                         'classification': review['classification']})
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
        data['layers']['security']['source_urls'] = [row['url'] for row in evidence['sections']]
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
