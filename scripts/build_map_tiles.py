#!/usr/bin/env python3
"""Build vector map tiles (PMTiles) for the MapLibre map test.

    TIPPECANOE=/path/to/tippecanoe python scripts/build_map_tiles.py

Layers (each written to `dist/tiles/<name>.pmtiles`, one `reefs` layer, zooms 8-15):
- morro-bay-reef-outlines: the 107 partial USGS rough-habitat footprints in
  `dist/data/atlas.json` (`areas`), about 320 KB of GeoJSON.
- socal-survey-habitat: the 410 Southern California survey habitat polygons
  (228,000 vertices, 6.4 MB GeoJSON), the densest layer in the app, to show
  how the formats scale.
The GeoJSON stays the source of truth; tiles are a delivery format.
Requires tippecanoe 2.82+ (https://github.com/felt/tippecanoe).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TILES = ROOT / 'dist/tiles'


def morro_bay_reefs():
    for area in json.loads((ROOT / 'dist/data/atlas.json').read_text())['areas']:
        yield {'type': 'Feature', 'geometry': area['geometry'], 'properties': {
            'id': area['id'], 'area_ha': round(area['area_ha'], 2), 'source_id': area['source_id'],
            'research_only': bool(area.get('research_only')), 'targets': ','.join(area['target_ids'])}}


def socal_survey_habitat():
    data = json.loads((ROOT / 'dist/regions/southern-california/survey-habitat.geojson').read_text())
    for feature in data['features']:
        p = feature['properties']
        yield {'type': 'Feature', 'geometry': feature['geometry'], 'properties': {
            'id': p['id'], 'name': p['name'], 'habitat_kind': p['habitat_kind'],
            'area_km2': p.get('area_km2'), 'source_id': p['source_id'], 'research_only': True}}


LAYERS = {
    'morro-bay-reef-outlines': (morro_bay_reefs, 'SkipperCast Morro Bay reef outlines',
                                'USGS California Seafloor Mapping Program (via SkipperCast atlas)',
                                'Partial mapped rough-habitat footprints; research-only, not complete reefs.'),
    'socal-survey-habitat': (socal_survey_habitat, 'SkipperCast Southern California survey habitat',
                             'NOAA / USGS survey habitat (via SkipperCast)',
                             'Historical mapped habitat context; research-only, not fishing spots.'),
}


def build(tool, name):
    make, title, attribution, description = LAYERS[name]
    features = list(make())
    out = TILES / f'{name}.pmtiles'
    TILES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'layer.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}))
        # Relative paths and the bare tool name: tippecanoe records its command line in the
        # tile metadata, and temp or home paths would make every build differ.
        env = {**os.environ, 'PATH': f"{Path(tool).parent}{os.pathsep}{os.environ.get('PATH', '')}", 'TIPPECANOE_MAX_THREADS': '1'}
        subprocess.run(['tippecanoe', '--quiet', '--force', '-o', out.name, '-l', 'reefs', '-Z', '8', '-z', '15',
                        '--no-tile-size-limit', '--no-feature-limit', '--detect-shared-borders',
                        '--name', title, '--attribution', attribution, '--description', description,
                        'layer.geojson'], check=True, cwd=tmp, env=env)
        shutil.copyfile(Path(tmp) / out.name, out)
    print(f'{out.relative_to(ROOT)}: {out.stat().st_size / 1000:.0f} KB from {len(features)} features')


def main():
    tool = os.environ.get('TIPPECANOE') or shutil.which('tippecanoe')
    if not tool:
        raise SystemExit('tippecanoe not found; set TIPPECANOE or install https://github.com/felt/tippecanoe')
    for name in sys.argv[1:] or LAYERS:
        build(tool, name)


if __name__ == '__main__':
    main()
