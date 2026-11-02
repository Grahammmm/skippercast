"""Compile the reviewed first-run port directory from regional forecast points."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(root=ROOT):
    source = json.loads((root / 'catalog/home-ports.json').read_text())
    index = json.loads((root / 'dist/regions/index.json').read_text())
    regions = {row['id']: row for row in index['regions']}
    configs = {}
    seen = set()
    ports = []
    for i, item in enumerate(source['ports']):
        for field in ('id', 'name', 'region', 'forecast_point'):
            if not isinstance(item, dict) or not isinstance(item.get(field), str) or not item[field]:
                raise ValueError(f'Port {i} missing {field}')
        if item['id'] in seen:
            raise ValueError('Duplicate port: ' + item['id'])
        if item['region'] not in regions:
            raise ValueError('Unknown region for port: ' + item['id'])
        seen.add(item['id'])
        match = item.get('match')
        if not (isinstance(match, list) and len(match) == 2
                and all(type(v) is int or (type(v) is float and math.isfinite(v)) for v in match)):
            raise ValueError('Port match must be two numbers: ' + item['id'])
        lat, lon = match
        if not (32 <= lat <= 42.1 and -125.5 <= lon <= -116.5):
            raise ValueError('Port match location outside California: ' + item['id'])
        if item['region'] not in configs:
            configs[item['region']] = json.loads((root / 'dist' / regions[item['region']]['config']).read_text())
        point = next((p for p in configs[item['region']]['forecast_points'] if p['id'] == item['forecast_point']), None)
        if point is None:
            raise ValueError('Unknown forecast point for port: ' + item['id'])
        ports.append({'id': item['id'], 'name': item['name'], 'region': item['region'],
                      'region_name': regions[item['region']]['name'], 'status': regions[item['region']]['status'],
                      'forecast_point': item['forecast_point'], 'forecast_name': point['name'],
                      'match': item['match'], 'view': [point['latitude'], point['longitude'], 10]})
    result = {'schema_version': 1, 'ports': ports,
              'note': 'Port matching is approximate and stays on this device. Map centers are marine forecast samples, not harbor entrances or navigation waypoints.'}
    output = root / 'dist/data/home-ports.json'
    tmp = output.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    tmp.replace(output)
    return result


if __name__ == '__main__':
    print(f"Compiled {len(build()['ports'])} home-port choices")
