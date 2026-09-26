"""Compile the reviewed first-run port directory from regional forecast points."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = json.loads((ROOT / 'catalog/home-ports.json').read_text())
    index = json.loads((ROOT / 'dist/regions/index.json').read_text())
    regions = {row['id']: row for row in index['regions']}
    seen = set()
    ports = []
    for item in source['ports']:
        if item['id'] in seen or item['region'] not in regions:
            raise ValueError('Duplicate port or unknown region: ' + item['id'])
        seen.add(item['id'])
        lat, lon = item['match']
        if not (32 <= lat <= 42.1 and -125.5 <= lon <= -116.5):
            raise ValueError('Port match location outside California: ' + item['id'])
        region = json.loads((ROOT / 'dist' / regions[item['region']]['config']).read_text())
        point = next((p for p in region['forecast_points'] if p['id'] == item['forecast_point']), None)
        if point is None:
            raise ValueError('Unknown forecast point for port: ' + item['id'])
        ports.append({'id': item['id'], 'name': item['name'], 'region': item['region'],
                      'region_name': regions[item['region']]['name'], 'status': regions[item['region']]['status'],
                      'forecast_point': item['forecast_point'], 'forecast_name': point['name'],
                      'match': item['match'], 'view': [point['latitude'], point['longitude'], 10]})
    result = {'schema_version': 1, 'ports': ports,
              'note': 'Port matching is approximate and stays on this device. Map centers are marine forecast samples, not harbor entrances or navigation waypoints.'}
    output = ROOT / 'dist/data/home-ports.json'
    output.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    return result


if __name__ == '__main__':
    print(f"Compiled {len(build()['ports'])} home-port choices")
