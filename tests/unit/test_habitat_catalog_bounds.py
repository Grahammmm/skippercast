"""Source envelopes measured from all vertices in the four EPSG:26910 layers."""
import json
from pathlib import Path


def test_habitat_catalog_bounds_cover_source_vertices():
    rows = json.loads((Path(__file__).resolve().parents[2] / 'catalog/sources.json').read_text())['sources']
    sources = {row['id']: row for row in rows}
    # WGS84 extrema, transformed from every source polygon vertex (always_xy).
    extrema = {
        'nanphab': (-119.52595858492705, 34.01959923290194, -119.44956483022165, 34.08095602035663),
        'sanahab': (-119.45553005904179, 33.984636612835544, -119.33250214214621, 34.02420877180203),
        'sanphab': (-119.53128536905776, 33.97927262015446, -119.451577529403, 34.02813871022469),
        'secruhab': (-119.7231174226895, 33.935397235077296, -119.5890593213255, 33.98831226164276),
    }
    for name, (west, south, east, north) in extrema.items():
        bounds = sources[f'usgs-of2005-1170-{name}']['bounds']
        assert bounds[0] <= west and bounds[1] <= south, name
        assert bounds[2] >= east and bounds[3] >= north, name
