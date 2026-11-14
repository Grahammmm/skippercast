"""Check planned basemap detail boxes offline; this does not inspect or publish tiles.

    python3 scripts/basemap/check_detail.py             # current extract settings
    python3 scripts/basemap/check_detail.py --dir DIR   # saved plan.json + detail.geojson
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.basemap import regions


def check_detail(planned, detail, root=regions.ROOT):
    """Require every current active/preview box and the exact zoom 11–14 split."""
    expected = regions.region_boxes(root)
    if planned.get('detail') != {'minzoom': 11, 'maxzoom': 14}:
        raise ValueError('Detail extraction must cover zooms 11–14')
    if planned.get('overview', {}).get('maxzoom') != 10:
        raise ValueError('Overview must end at zoom 10')
    boxes = planned.get('regions', [])
    ids = [box['id'] for box in boxes]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate detail region IDs')
    actual = {box['id']: regions.check_bbox(box['bbox']) for box in boxes}
    wanted = {box['id']: box['bbox'] for box in expected}
    if actual != wanted:
        missing = sorted(wanted.keys() - actual.keys())
        extra = sorted(actual.keys() - wanted.keys())
        changed = sorted(k for k in wanted.keys() & actual.keys() if wanted[k] != actual[k])
        raise ValueError(f'Detail boxes differ: missing={missing}, extra={extra}, changed={changed}')
    if detail != regions.detail_region(boxes):
        raise ValueError('detail.geojson does not match the planned region boxes')
    coverage = []
    for path in sorted(Path(root, 'regions').glob('*/region.json')):
        region = json.loads(path.read_text())
        w, s, e, n = regions.check_bbox(region['bounds'])
        containers = [box['id'] for box in boxes
                      if box['bbox'][0] <= w and box['bbox'][1] <= s
                      and box['bbox'][2] >= e and box['bbox'][3] >= n]
        if not containers:
            raise ValueError(f"No detail box contains region {region['id']}")
        coverage.append({'id': region['id'], 'bbox': [w, s, e, n], 'containers': containers})
    return coverage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dir', type=Path, help='Check saved extraction settings instead of current defaults')
    args = parser.parse_args(argv)
    try:
        if args.dir:
            planned = json.loads((args.dir / 'plan.json').read_text())
            detail = json.loads((args.dir / 'detail.geojson').read_text())
        else:
            boxes = regions.region_boxes()
            planned = {'overview': {'maxzoom': regions.OVERVIEW_MAXZOOM},
                       'detail': {'minzoom': regions.OVERVIEW_MAXZOOM + 1,
                                  'maxzoom': regions.DETAIL_MAXZOOM}, 'regions': boxes}
            detail = regions.detail_region(boxes)
        boxes = check_detail(planned, detail)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f'FAIL: {error}\n')
    for box in boxes:
        print(f"PASS {box['id']}: zooms 11–14 inside detail box {', '.join(box['containers'])} {box['bbox']}")
    print(f'{len(boxes)} of {len(boxes)} regions inside a detail box (extract settings only; not archive coverage)')


if __name__ == '__main__':
    main()
