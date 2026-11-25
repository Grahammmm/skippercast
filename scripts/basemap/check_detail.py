"""Check planned basemap overview and detail boxes offline; this does not inspect or publish tiles.

    python3 scripts/basemap/check_detail.py             # current extract settings
    python3 scripts/basemap/check_detail.py --dir DIR   # saved plan.json + detail.geojson
    python3 scripts/basemap/check_detail.py --manifest PATH  # saved basemap pointer
"""
import argparse
import json
import math
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.basemap import regions


def check_detail(planned, detail, root=regions.ROOT):
    """Require every current active/preview box, overview coverage, and the exact zoom split."""
    expected = regions.region_boxes(root)
    if planned.get('detail') != {'minzoom': 11, 'maxzoom': 14}:
        raise ValueError('Detail extraction must cover zooms 11–14')
    overview = planned.get('overview', {})
    if overview.get('maxzoom') != 10:
        raise ValueError('Overview must end at zoom 10')
    bbox = overview.get('bbox')
    if (not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox)):
        raise ValueError('plan.json: overview.bbox must be an array of four numbers')
    try:
        west, south, east, north = regions.check_bbox(bbox)
    except (ValueError, OverflowError) as error:
        raise ValueError('plan.json: overview.bbox must have finite, ordered coordinates within bounds') from error
    for box in expected:
        w, s, e, n = box['bbox']
        if not (west <= w and south <= s and east >= e and north >= n):
            raise ValueError(f"plan.json: overview.bbox does not contain region {box['id']}")
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


def _load(path):
    try:
        return json.loads(path.read_text())
    except OSError as error:
        raise ValueError(f'{path.name}: cannot read: {error.strerror or error}') from error
    except json.JSONDecodeError as error:
        raise ValueError(f'{path.name}: not valid JSON (line {error.lineno} column {error.colno})') from error
    except RecursionError as error:
        raise ValueError(f'{path.name}: JSON nesting exceeds parser limit') from error


def _shape(planned, detail):
    """Name the file and field of a misshaped saved plan, or return None."""
    if not isinstance(planned, dict):
        return 'plan.json: not a JSON object'
    for key in ('overview', 'detail'):
        if not isinstance(planned.get(key), dict):
            return f'plan.json: "{key}" must be an object'
    if not isinstance(planned.get('regions'), list):
        return 'plan.json: "regions" must be a list'
    for i, box in enumerate(planned['regions']):
        bbox = box.get('bbox') if isinstance(box, dict) else None
        if (not isinstance(box, dict) or not isinstance(box.get('id'), str)
                or not isinstance(bbox, list) or len(bbox) != 4
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           and v == v for v in bbox)):
            return f'plan.json: regions[{i}] must be an object with a string "id" and a 4-number "bbox"'
    if not isinstance(detail, dict):
        return 'detail.geojson: not a JSON object'
    return None


def check_manifest(path):
    """Require overview coverage and report which detail boxes contain each indexed region."""
    try:
        manifest = _load(path)
    except UnicodeDecodeError as error:
        raise ValueError(f'{path.name}: not valid JSON (invalid text encoding)') from error
    if not isinstance(manifest, dict):
        raise ValueError(f'{path.name}: manifest must be a JSON object')
    if manifest.get('detail') != {'minzoom': 11, 'maxzoom': 14}:
        raise ValueError(f'{path.name}: detail must be {{"minzoom": 11, "maxzoom": 14}}')
    overview = manifest.get('overview')
    if not isinstance(overview, dict):
        raise ValueError(f'{path.name}: overview must be an object')
    if overview.get('maxzoom') != 10:
        raise ValueError(f'{path.name}: overview.maxzoom must be 10')
    boxes = manifest.get('regions')
    if not isinstance(boxes, list):
        raise ValueError(f'{path.name}: regions must be a list')
    bboxes = [('overview.bbox', overview.get('bbox'))]
    for i, box in enumerate(boxes):
        if not isinstance(box, dict):
            raise ValueError(f'{path.name}: regions[{i}] must be an object')
        if not isinstance(box.get('id'), str) or not box['id']:
            raise ValueError(f'{path.name}: regions[{i}].id must be a nonempty string')
        bboxes.append((f'regions[{i}].bbox', box.get('bbox')))
    for field, bbox in bboxes:
        if (not isinstance(bbox, list) or len(bbox) != 4
                or not all(type(v) is int or (type(v) is float and math.isfinite(v)) for v in bbox)
                or not (bbox[0] < bbox[2] and bbox[1] < bbox[3])):
            raise ValueError(f'{path.name}: {field} must be an array of four finite, ordered numbers')

    try:
        w, s, e, n = regions.check_bbox(overview['bbox'])
    except (ValueError, OverflowError) as error:
        raise ValueError(f'{path.name}: overview.bbox must have finite, ordered coordinates within bounds') from error

    coverage = {}
    for region in regions.region_boxes():
        west, south, east, north = region['bbox']
        if not (w <= west and s <= south and e >= east and n >= north):
            raise ValueError(f"{path.name}: overview.bbox does not contain indexed region {region['id']}")
        coverage[region['id']] = [box['id'] for box in boxes
                                  if box['bbox'][0] <= west and box['bbox'][1] <= south
                                  and box['bbox'][2] >= east and box['bbox'][3] >= north]
    misses = sorted(region_id for region_id, ids in coverage.items() if not ids)
    if misses:
        raise ValueError(f"manifest detail boxes miss indexed region(s): {', '.join(misses)}")
    return coverage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--dir', type=Path, help='Check saved extraction settings instead of current defaults')
    inputs.add_argument('--manifest', type=Path, metavar='PATH', help='Check a saved basemap pointer footprint')
    args = parser.parse_args(argv)
    try:
        if args.manifest:
            coverage = check_manifest(args.manifest)
            for region_id, ids in coverage.items():
                print(f"PASS {region_id}: inside manifest detail box {', '.join(ids)}")
            count = len(coverage)
            print(f"{count} of {count} indexed regions inside the manifest's detail boxes "
                  "(footprint only; tile bytes not inspected)")
            return
        if args.dir:
            planned = _load(args.dir / 'plan.json')
            detail = _load(args.dir / 'detail.geojson')
            problem = _shape(planned, detail)
            if problem:
                raise ValueError(problem)
        else:
            boxes = regions.region_boxes()
            planned = {'overview': {'bbox': regions.overview_box(boxes),
                                    'maxzoom': regions.OVERVIEW_MAXZOOM},
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
