"""R6a: derive the package layer inventory from the current producer receipts.

    region.py inventory --region <id> --out <OUT>
    region.py package --region <id> --out <OUT> --manifest OUT/<id>/inventory/manifest.json \\
        --upstream tiles:public --upstream digests --upstream zone:public --upstream inventory

The layer producers write disjoint leaves (``tiles`` -> ``layers/public/tiles``, ``zone`` ->
``layers/public/zone``, ``digests`` -> ``layers/public/relief.digests``), so a rebuild of one
never replaces another. This stage copies no layer bytes. It lists the exact files that the
current producer receipts own and derives the release metadata from the archive the tiles
receipt owns, the public selection and the source catalog. ``package`` then hashes every
listed file against those receipts again, and with ``--upstream inventory`` it refuses a
manifest that is not this stage's current output.

Depth contours are not part of the relief release: they ship through the repository
contour channel (``layers/contours``, R10), not through ``release.json``.

Metadata rules (nothing here certifies a cell; QA checks the emitted evidence):
- ``bounds``, ``minzoom``, ``maxzoom`` and ``native_support_by_zoom`` come from the PMTiles
  metadata the tile builder wrote into the archive. Per-file selection ids are mapped to
  their catalog id; when several files of one catalog source share a resolution, the
  zoom's tile count is the largest single-file count (a lower bound of their union).
- ``sources`` has one row per catalog id of the public selection, with the catalog rights.
  A label is ``measured`` only when every selected file of the source says so.
  ``survey_dates`` is ``["unstated"]`` when the selection carries no dates.
- ``detail_summary`` has one nominal 0-300 ft band per (catalog id, resolution), with the
  lowest per-file support-class cap when every file has one.
"""
from __future__ import annotations

import gzip
import json
import struct

from skippercast.relief import mosaic, package, receipts

UPSTREAM = ('select', 'tiles:public', 'digests', 'zone:public')
TARGET = 'inventory'
MANIFEST = 'manifest.json'
CODE_FILES = ('skippercast.relief.package', 'skippercast.relief.mosaic')
SHALLOW_M = 91.44
_RIGHTS_TEXT = ('public_display', 'license', 'attribution', 'commercial_use', 'terms_url')
_SUPPORT_KEYS = ('tiles', 'limit_m', 'support_class')


class InventoryError(receipts.ReceiptError):
    """The producer receipts cannot describe one public release."""


def archive_metadata(path):
    """The JSON metadata of a PMTiles v3 archive (header and metadata only)."""
    with path.open('rb') as stream:
        header = stream.read(127)
        if len(header) != 127 or header[:8] != b'PMTiles\x03':
            raise InventoryError('expected a PMTiles v3 archive')
        offset, length = struct.unpack_from('<QQ', header, 24)
        stream.seek(offset)
        data = stream.read(length)
    if len(data) != length:
        raise InventoryError('truncated PMTiles metadata')
    compression = header[97]
    if compression == 2:
        data = gzip.decompress(data)
    elif compression not in (0, 1):
        raise InventoryError('unsupported PMTiles metadata compression')
    doc = json.loads(data)
    if not isinstance(doc, dict):
        raise InventoryError('PMTiles metadata is not an object')
    return doc


def owned(doc, prefix=package.LAYERS):
    """Region-relative output paths of a receipt under ``prefix``."""
    return sorted(row['path'] for row in doc['outputs'] if row['path'].startswith(prefix))


def catalog_rows():
    doc = package.decode_document((package.repo_root() / 'catalog/sources.json').read_bytes())
    return {row['id']: row for row in doc['sources']}


def release_source(sid, rows, registered):
    if registered is None:
        raise InventoryError(f'selected source {sid!r} has no catalog row')
    rights = registered.get('rights') or {}
    label = 'measured' if all(row.get('label') == 'measured' for row in rows) else 'estimated'
    datums = sorted({row['vertical_datum'] for row in rows if isinstance(row.get('vertical_datum'), str)
                     and row['vertical_datum'].strip()})
    dates = sorted({d for row in rows for d in (row.get('survey_dates') or ()) if isinstance(d, str) and d.strip()})
    attribution = rights.get('attribution') or rows[0].get('attribution')
    if not isinstance(attribution, str) or not attribution.strip():
        raise InventoryError(f'source {sid!r} has no attribution')
    out = {'id': sid, 'label': label, 'estimated': label != 'measured', 'attribution': attribution,
           'vertical_datum': '; '.join(datums) or 'unstated', 'survey_dates': dates or ['unstated'],
           'rights_class': 'public'}
    # Carry the catalog rights as recorded; package and the pointer schema decide whether they allow release.
    out['rights'] = {k: rights[k] for k in _RIGHTS_TEXT if isinstance(rights.get(k), str) and rights[k].strip()}
    if isinstance(rights.get('attribution_required'), bool):
        out['rights']['attribution_required'] = rights['attribution_required']
    if rights.get('redistribution_reviewed') is True:
        out['rights']['redistribution_reviewed'] = True
    for key, field in (('provider', 'provider'), ('source_url', 'documentation_url')):
        if isinstance(registered.get(field), str) and registered[field].strip():
            out[key] = registered[field]
    return out


def zoom_support(by_zoom, catalog_id):
    result = {}
    for z, support in sorted(by_zoom.items(), key=lambda item: int(item[0])):
        if not isinstance(support, dict):
            raise InventoryError(f'invalid archive support at z{z}')
        merged = {}
        for native in support.get('sources') or ():
            sid = catalog_id.get(native.get('id'))
            if sid is None:
                raise InventoryError(f'archive support names an unselected source at z{z}')
            key = (sid, native['resolution_m'])
            merged[key] = max(merged.get(key, 0), native['tiles'])
        row = {k: support[k] for k in _SUPPORT_KEYS if k in support}
        row['sources'] = [{'id': sid, 'resolution_m': res, 'tiles': n}
                          for (sid, res), n in sorted(merged.items(), key=lambda item: (item[0][1], item[0][0]))]
        result[str(z)] = row
    return result


def plan(ctx):
    table = mosaic.selected(ctx, 'sources.json')
    archive = mosaic.upstream_file(ctx, 'tiles.public', ctx.region.dir / package.ARCHIVE)
    return receipts.Plan([receipts.Input(table, 'sources'),
                          receipts.Input(package.repo_root() / 'catalog/sources.json', 'rights')],
                         {'archive': ctx.region.record(archive), 'shallow_m': SHALLOW_M})


def build(ctx, out):
    tiles, digests, zone = (ctx.upstream[key] for key in ('tiles.public', 'digests', 'zone.public'))
    if package.ARCHIVE not in owned(tiles):
        raise InventoryError('the current tiles receipt does not own the relief archive')
    index = owned(digests, package.LAYERS + 'relief.digests/')
    if package.DIGEST_ROOT not in index:
        raise InventoryError('the current digests receipt does not own the digest root')
    layer_paths = sorted({package.ARCHIVE, *index, *owned(zone)})

    metadata = archive_metadata(mosaic.upstream_file(ctx, 'tiles.public', ctx.region.dir / package.ARCHIVE))
    rows = mosaic.sources(ctx)
    if not rows:
        raise InventoryError('the public selection has no sources')
    groups = {}
    catalog_id = {}
    for row in rows:
        sid = row.get('source_id') or row['id']
        catalog_id[row['id']] = sid
        groups.setdefault(sid, []).append(row)
    catalog = catalog_rows()
    sources = [release_source(sid, members, catalog.get(sid)) for sid, members in sorted(groups.items())]

    bands = {}
    for sid, members in groups.items():
        for res in sorted({row['resolution_m'] for row in members}):
            same = [row for row in members if row['resolution_m'] == res]
            band = {'source_id': sid, 'min_depth_m': 0, 'max_depth_m': SHALLOW_M, 'resolution_m': res}
            caps = [row.get('support_class_cap') for row in same]
            if all(type(cap) is int and cap in (1, 2, 3) for cap in caps):
                band['support_class'] = min(caps)
            bands[(sid, res)] = band
    manifest = {
        'region': ctx.region.id,
        'bounds': metadata['bounds'],
        'minzoom': metadata['minzoom'],
        'maxzoom': metadata['maxzoom'],
        'sources': sources,
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [bands[key] for key in sorted(bands)]},
        'native_support_by_zoom': zoom_support(metadata.get('native_support_by_zoom') or {}, catalog_id),
        'layer_paths': layer_paths,
    }
    (out / MANIFEST).write_bytes(receipts.canonical(manifest))
    return {'layers': len(layer_paths), 'sources': len(sources)}
