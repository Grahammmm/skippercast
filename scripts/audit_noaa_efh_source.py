"""Audit NOAA West Coast EFH map-service species labels and source granularity.

EFH boundaries are broad planning context. They never become fishing spots,
catch probabilities, legal closures or a substitute for current ocean data.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE = 'https://maps.fisheries.noaa.gov/server/rest/services/WCR/EFH_mapservice/MapServer'
INPORT_HMS = 'https://www.fisheries.noaa.gov/inport/item/80209'
NOAA_GROUNDFISH = 'https://www.fisheries.noaa.gov/resource/map/essential-fish-habitat-groundfish-and-salmon'
FIELDS = {'SITENAME_L', 'LIFESTAGE', 'TYPE', 'FMC', 'Region', 'INSTATEWAT'}


def fetch_json(url):
    if not url.startswith(BASE + '/') and url != BASE + '?f=pjson':
        raise ValueError('Only the reviewed NOAA EFH service is allowed')
    request = Request(url, headers={'User-Agent': 'SkipperCast NOAA EFH source review/1.0'})
    with urlopen(request, timeout=25) as response:
        if not response.url.startswith(BASE) or response.status != 200:
            raise ValueError('NOAA EFH source redirected or unavailable')
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Oversized NOAA EFH response')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def audit(service, layer, query, hashes, *, checked_at=None):
    if service.get('mapName') != 'EFH_mapservice' or layer.get('id') != 4:
        raise ValueError('Unexpected NOAA EFH map service/layer')
    if layer.get('geometryType') != 'esriGeometryPolygon':
        raise ValueError('NOAA EFH layer geometry changed')
    if not FIELDS.issubset({field['name'] for field in layer.get('fields', [])}):
        raise ValueError('NOAA EFH species field schema changed')
    if query.get('error') or query.get('exceededTransferLimit') or not query.get('features'):
        raise ValueError('Incomplete NOAA EFH species query')
    labels = sorted({str(feature['attributes']['SITENAME_L']).strip()
                     for feature in query['features']})
    if not {'Groundfish', 'Yellowfin Tuna', 'Albacore Tuna'}.issubset(labels):
        raise ValueError('Expected broad groundfish/HMS EFH classes absent')
    bluefin_alias = 'Northern Bluefin Tuna' in labels and 'Pacific Bluefin Tuna' not in labels
    return {
        'schema_version': 1, 'scope': 'noaa-west-coast-efh-source-granularity-review',
        'checked_at': checked_at or datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'service_url': BASE, 'layer_url': BASE + '/4',
        'service_sha256': hashes['service'], 'layer_sha256': hashes['layer'],
        'distinct_query_sha256': hashes['query'],
        'source_catalog_urls': [NOAA_GROUNDFISH, INPORT_HMS],
        'service_labels': labels, 'service_label_count': len(labels),
        'bluefin_label_needs_2026_crosswalk': bluefin_alias,
        'groundfish_is_aggregate_not_rockfish_or_lingcod': 'Groundfish' in labels
        and not {'Rockfish', 'Lingcod'} & set(labels),
        'coastwide_eligibility_context_only': True,
        'fishing_target': False, 'exportable': False, 'legal_clearance': False,
        'method': 'Original NOAA map-service metadata and distinct species labels are checked without using generalized polygon edges as precise fish positions. Compare labels against the newer 2026 NOAA HMS InPort metadata before any species crosswalk.',
        'limitations': ['EFH designations describe broad habitat necessary to fish, not current presence, catch success, a legal opening or a site-level habitat model.',
                        'The service groups groundfish and uses Northern Bluefin Tuna while the 2026 HMS InPort record names Pacific bluefin; do not silently equate or rank these from this service.',
                        'Official text descriptions remain determinative; the NOAA map polygons can overlap land and are unsuitable as precise nearshore boundaries.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist/data/noaa-efh-source-review.json'))
    args = parser.parse_args()
    params = urlencode({'where': '1=1', 'outFields': ','.join(sorted(FIELDS)),
                        'returnGeometry': 'false', 'returnDistinctValues': 'true', 'f': 'json'})
    service, h1 = fetch_json(BASE + '?f=pjson')
    layer, h2 = fetch_json(BASE + '/4?f=pjson')
    query, h3 = fetch_json(BASE + '/4/query?' + params)
    result = audit(service, layer, query, {'service': h1, 'layer': h2, 'query': h3})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    print(result['service_label_count'], 'broad EFH labels; fishing targets withheld')


if __name__ == '__main__':
    main()
