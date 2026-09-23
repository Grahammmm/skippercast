"""Compile coastwide discovery sectors without promoting them to fishing grounds."""
from pathlib import Path
from .contracts import REPO, atomic_json, bbox, public_url, read_json


def compile_sectors(root=REPO):
    root = Path(root)
    source = read_json(root / 'catalog/coastal-sectors.json')
    coasts = read_json(root / 'catalog/coasts.json')['regions']
    packages = {p['id']: p for p in read_json(root / 'dist/regions/index.json')['regions']}
    if source.get('schema_version') != 1 or not source.get('reviewed_at'):
        raise ValueError('Invalid coastal sector catalog')
    public_url(source['survey_feed_url'])
    public_url(source['survey_product_feed_url'])
    for lead in source['survey_discovery']:
        public_url(lead['url'])
    result, seen = [], set()
    for coast in coasts:
        bands = [s for s in source['sectors'] if s['coast'] == coast['id']]
        if not bands:
            raise ValueError('Every coast needs at least one discovery sector')
        bands.sort(key=lambda item: item['latitude'][0])
        if bands[0]['latitude'][0] != coast['latitude'][0] or bands[-1]['latitude'][1] != coast['latitude'][1]:
            raise ValueError('Sector bands must cover their parent coast')
        for index, sector in enumerate(bands):
            south, north = sector['latitude']
            if index and bands[index - 1]['latitude'][1] != south:
                raise ValueError('Sector bands must meet without gaps or overlaps')
            if sector['id'] in seen or not sector['id'].replace('-', '').isalnum() or not sector['name']:
                raise ValueError('Invalid or duplicate sector identity')
            seen.add(sector['id'])
            bounds = [coast['bounds'][0], south, coast['bounds'][2], north]
            bbox(bounds)
            overlapping = []
            candidates = 0
            for package_id in coast['packages']:
                package = packages[package_id]
                west, psouth, east, pnorth = package['fishing_bounds']
                if east < bounds[0] or west > bounds[2] or pnorth <= south or psouth >= north:
                    continue
                overlapping.append(package_id)
                region = read_json(root / 'regions' / package_id / 'region.json')
                atlas = read_json(root / 'dist' / region['assets']['atlas'])
                candidates += sum(bounds[0] <= p['longitude'] <= bounds[2]
                                  and south <= p['latitude'] < north for p in atlas['targets'])
            result.append({**sector, 'bounds': bounds, 'status': 'discovery',
                           'rules_url': coast['rules_url'],
                           'partial_package_ids': overlapping,
                           'published_candidate_points': candidates,
                           'note': 'Browse area only. Survey coverage, current fish presence and date-specific legal access have not been established by this sector.'})
    if len(result) != len(source['sectors']):
        raise ValueError('Sector references an unknown coast')
    packet = {'schema_version': 1, 'reviewed_at': source['reviewed_at'],
              'scope': source['scope'], 'survey_feed_url': source['survey_feed_url'],
              'survey_product_feed_url': source['survey_product_feed_url'],
              'survey_discovery': source['survey_discovery'],
              'sectors': result}
    atomic_json(root / 'dist/data/coastal-sectors.json', packet)
    return packet
