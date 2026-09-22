import unittest,json,hashlib
from pathlib import Path
try:
 from shapely.geometry import shape
 from shapely.ops import unary_union
except ImportError:shape=None
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipIf(shape is None,'Optional native GIS tools unavailable')
class SearchGeometry(unittest.TestCase):
 def test_sources_boundaries_and_species(self):
  for path in (ROOT/'regions').glob('*/region.json'):
   r=json.loads(path.read_text());asset=r['assets'].get('search_plans')
   if not asset:continue
   d=json.loads((ROOT/'dist'/asset).read_text());exclusions=[]
   for key in ('protected_areas','closures'):
    if r['assets'].get(key):exclusions += [shape(f['geometry']) for f in json.loads((ROOT/'dist'/r['assets'][key]).read_text())['features']]
   excluded=unary_union(exclusions)
   for receipt in d['input_receipts']:
    self.assertEqual(hashlib.sha256((ROOT/'dist'/receipt['path']).read_bytes()).hexdigest(),receipt['sha256'])
   for f in d['features']:
    g=shape(f['geometry']);self.assertTrue(g.is_valid);self.assertFalse(g.intersects(excluded));self.assertFalse(f['properties']['fish_confirmed'])
if __name__=='__main__':unittest.main()
