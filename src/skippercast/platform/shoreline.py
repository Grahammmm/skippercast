"""Publish a region's NOAA CUSP shoreline (FE-10, docs/plans/front-end/design.md § 11).

scripts/shoreline/import_cusp.py writes catalog/shoreline/<id>.geojson; the
platform build copies it byte for byte to dist/regions/<id>/shoreline.geojson
after checking that every feature keeps its source date and NOAA creator and
lies inside the region. A region without an import publishes no shoreline.
"""
from pathlib import Path
import re
import shutil

from .contracts import read_json

DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def check_shoreline(collection, region):
    """Raise ValueError unless the collection is a dated, NOAA-created, in-region CUSP extract."""
    provenance = collection.get('provenance') or {}
    if collection.get('type') != 'FeatureCollection' or provenance.get('region_id') != region['id']:
        raise ValueError(f"Shoreline for {region['id']} is not its CUSP FeatureCollection")
    if provenance.get('source_id') != 'noaa-cusp-shoreline' or provenance.get('features') != len(collection['features']):
        raise ValueError(f"Shoreline for {region['id']} has incomplete provenance")
    west, south, east, north = region['bounds']
    for feature in collection['features']:
        properties, geometry = feature.get('properties') or {}, feature.get('geometry') or {}
        if not DATE.fullmatch(str(properties.get('source_date'))) or properties.get('DAT_SET_CR') != 'NOAA':
            raise ValueError(f"Shoreline feature {feature.get('id')} lacks a source date or a NOAA creator")
        lines = {'LineString': [geometry.get('coordinates')], 'MultiLineString': geometry.get('coordinates')}.get(geometry.get('type'))
        if not lines or any(len(line) < 2 or any(not (west <= x <= east and south <= y <= north) for x, y in line)
                            for line in lines):
            raise ValueError(f"Shoreline feature {feature.get('id')} is not a line inside {region['id']}")


def publish_shoreline(root, region, output):
    """Copy the checked import to output/shoreline.geojson; remove a stale copy when there is none."""
    source, target = Path(root) / 'catalog/shoreline' / f"{region['id']}.geojson", Path(output) / 'shoreline.geojson'
    if not source.is_file():
        target.unlink(missing_ok=True)
        return None
    check_shoreline(read_json(source), region)
    shutil.copyfile(source, target)
    return f"regions/{region['id']}/shoreline.geojson"
