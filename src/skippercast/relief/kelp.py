"""Build one September of the authors' derived Planet canopy polygons, locally only."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from urllib.request import HTTPRedirectHandler, build_opener
from zipfile import ZipFile

ZENODO = 'https://zenodo.org'
POLYGON_RECORD = '17644635'
POLYGON_CONCEPT = '10.5281/zenodo.17644634'
LATEST = f'{ZENODO}/api/records/{POLYGON_RECORD}/versions/latest'
CC_BY = 'https://creativecommons.org/licenses/by/4.0/legalcode'
RIGHTS_TEXT = (
    'License Creative Commons Attribution 4.0 International '
    'The Creative Commons Attribution license allows re-distribution and re-use of a licensed '
    'work on the condition that the creator is appropriately credited. Read more'
)
ARCHIVE = re.compile(r'(20\d{2})_09_PlanetDove_KelpPolygon\.zip', re.ASCII)
# Deliberately bounded; a larger future archive needs a new operational check.
MAX_ARCHIVE = 64 * 1024**2
MAX_UNPACKED = 512 * 1024**2
CHUNK = 1024**2


class Refusal(ValueError):
    """A short, producer-authored reason safe to put in a receipt."""


class _LatestRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.full_url != LATEST or not re.fullmatch(
            rf'{re.escape(ZENODO)}/api/records/[1-9][0-9]*', newurl
        ):
            raise Refusal('unexpected Zenodo redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url):
    """Only the fixed Zenodo URLs assembled below; never follow a file-list URL."""
    return build_opener(_LatestRedirect()).open(url, timeout=60)


def _metadata(url):
    limit = 2 * CHUNK
    with _open(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise Refusal('oversize Zenodo metadata')
    return data.decode('utf-8')


class _Rights(HTMLParser):
    """Read the public record's Rights block, not an occurrence elsewhere on the page."""

    def __init__(self, html):
        super().__init__()
        self.depth = self.blocks = 0
        self.parts = []
        self.links = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            if attrs.get('id') == 'licenses':
                self.blocks += 1
                self.depth = self.depth or 1
            elif self.depth:
                self.depth += 1
        if self.depth and tag == 'a':
            self.links.append(attrs.get('href'))

    def handle_endtag(self, tag):
        if tag == 'div' and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and data.strip():
            self.parts.append(data)

    @property
    def text(self):
        return ' '.join(' '.join(self.parts).split())

    def permits(self, metadata):
        return (self.blocks == 1 and not self.depth and self.text == RIGHTS_TEXT
                and self.links == [CC_BY] and isinstance(metadata, dict)
                and metadata.get('license') == {'id': 'cc-by-4.0'}
                and not metadata.get('rights'))


def _newest_september(files):
    candidates = []
    for entry in files:
        key = entry['key']
        match = ARCHIVE.fullmatch(key)
        if match:
            candidates.append((int(match[1]), entry))
    if not candidates:
        raise Refusal('no September polygon ZIP in the latest Zenodo version')
    year = max(year for year, _ in candidates)
    newest = [entry for candidate, entry in candidates if candidate == year]
    if len(newest) != 1:
        raise Refusal('ambiguous newest September ZIP')
    entry = newest[0]
    size = entry['size']
    checksum = re.fullmatch(r'md5:([0-9a-f]{32})', entry['checksum'])
    if not checksum or type(size) is not int or not 0 < size <= MAX_ARCHIVE:
        raise Refusal('missing or out-of-bounds Zenodo MD5/size')
    return year, entry['key'], checksum[1], size


def _members(archive, year):
    """Allow only the named classification shapefiles and their known sidecars."""
    prefix = f'{year}_09_California_KelpCanopy_'.lower()
    pattern = re.compile(prefix + r'(kelppresence|areasurveyed)\.(shp|shx|dbf|prj|cpg|sbn|sbx|qix|shp\.xml)')
    files = {}
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = PurePosixPath(info.filename)
        match = pattern.fullmatch(name.name.lower())
        if not match:
            raise Refusal('unexpected member in the Planet classification ZIP')
        layer, suffix = match.groups()
        key = layer, suffix
        total += info.file_size
        if key in files or total > MAX_UNPACKED:
            raise Refusal('duplicate or oversize Planet shapefile members')
        files[key] = info
    required = {'shp', 'shx', 'dbf', 'prj'}
    if not required.issubset(suffix for layer, suffix in files if layer == 'kelppresence'):
        raise Refusal('incomplete September KelpPresence shapefile')
    return files


def _download(url, destination, md5, size, year):
    # Keep the bounded payload in memory until both its pins and its members
    # pass; an unexpected imagery archive must never be written to disk.
    with _open(url) as response:
        payload = response.read(size + 1)
    if len(payload) != size:
        raise Refusal('Zenodo archive size mismatch')
    if hashlib.md5(payload, usedforsecurity=False).hexdigest() != md5:
        raise Refusal('Zenodo archive MD5 mismatch')
    with ZipFile(BytesIO(payload)) as archive:
        _members(archive, year)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        staged = Path(tmp) / 'download.part'
        staged.write_bytes(payload)
        staged.replace(destination)


def _polygons(geometry):
    if not geometry.is_empty:
        if geometry.geom_type == 'Polygon':
            yield geometry
        elif geometry.geom_type in ('GeometryCollection', 'MultiPolygon'):
            for part in geometry.geoms:
                yield from _polygons(part)


def _water_mask(raw):
    # The supplied, reviewed California marine boundary must be RFC 7946 GeoJSON.
    from shapely import from_geojson, prepare, union_all

    data = json.loads(raw)
    if 'crs' in data:
        raise Refusal('California waters mask must be WGS84 GeoJSON without a legacy CRS')
    geometry = from_geojson(raw)
    parts = list(_polygons(geometry))
    if not parts or any(not part.is_valid for part in parts):
        raise Refusal('California waters mask must contain valid polygons')
    waters = union_all(parts)
    west, south, east, north = waters.bounds
    if not (-126 <= west < east <= -113 and 30 <= south < north <= 43):
        raise Refusal('California waters mask extent is not in California WGS84 coordinates')
    prepare(waters)
    return waters


def canopy_features(archive_path, year, waters_geojson, *, scratch=None):
    """Emit only positive canopy geometry clipped to the supplied waters mask.

    No simplification (0 m); no dissolve, gap fill, or inferred zero canopy.
    AreaSurveyed describes visibility, not kelp, and is never emitted as canopy.
    """
    import shapefile
    from pyproj import Transformer
    from shapely import make_valid, transform
    from shapely.geometry import mapping, shape

    waters = _water_mask(waters_geojson)
    with ZipFile(archive_path) as archive, tempfile.TemporaryDirectory(dir=scratch) as tmp:
        members = _members(archive, year)
        base = Path(tmp) / 'canopy'
        for suffix in ('shp', 'shx', 'dbf', 'prj'):
            with archive.open(members['kelppresence', suffix]) as src, base.with_suffix('.' + suffix).open('wb') as dst:
                shutil.copyfileobj(src, dst, CHUNK)
        project = Transformer.from_crs(base.with_suffix('.prj').read_text(), 'EPSG:4326', always_xy=True)
        properties = {'season': 'september', 'year': year, 'sensor': 'Planet 3 m'}
        with shapefile.Reader(str(base.with_suffix('.shp'))) as reader:
            if reader.shapeType not in (shapefile.POLYGON, shapefile.POLYGONM, shapefile.POLYGONZ):
                raise Refusal('KelpPresence must be polygonal')
            for record in reader.iterShapes():
                if record.shapeType == shapefile.NULL:
                    continue
                geo = transform(shape(record.__geo_interface__), project.transform, interleaved=False)
                # The even-odd linework repair handles self-touching pixel edges
                # without buffering them, or promoting line/point remnants.
                if not geo.is_valid:
                    geo = make_valid(geo)
                if not waters.intersects(geo):
                    continue
                clipped = geo if waters.covers(geo) else waters.intersection(geo)
                for polygon in _polygons(clipped):
                    yield {'type': 'Feature', 'geometry': mapping(polygon), 'properties': properties}


def build_planet_pmtiles(archive, year, waters_geojson, output, record_id):
    """Tile with Tippecanoe 2.82+ using stable relative filenames and no expansion."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp)
        with (stage / 'canopy.ndjson').open('w', encoding='utf-8') as sink:
            count = 0
            for feature in canopy_features(archive, year, waters_geojson, scratch=stage):
                sink.write(json.dumps(feature, separators=(',', ':'), allow_nan=False) + '\n')
                count += 1
        if not count:
            raise Refusal('no clipped canopy; refusing an empty replacement')
        attribution = (
            f'Cavanaugh et al., Zenodo doi:10.5281/zenodo.{record_id} (CC BY 4.0: {CC_BY}); '
            'doi:10.1038/s43247-025-03134-y. Modified: clipped and vector tiled.'
        )
        subprocess.run([
            'tippecanoe', '--quiet', '--output=kelp.pmtiles', '--layer=kelp',
            f'--name=Kelp canopy seen September {year} (Planet 3 m)',
            f'--attribution={attribution}', '--minimum-zoom=13', '--maximum-zoom=16',
            '--full-detail=14', '--low-detail=14', '--minimum-detail=14',
            '--buffer=0', '--no-line-simplification', '--no-tiny-polygon-reduction',
            '--no-feature-limit', '--no-tile-size-limit', 'canopy.ndjson',
        ], cwd=stage, check=True, env={**os.environ, 'TIPPECANOE_MAX_THREADS': '1', 'TMPDIR': str(stage.resolve())})
        archive_out = stage / 'kelp.pmtiles'
        digest = _sha256(archive_out)
        archive_out.replace(output)
        return digest


def _sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _last_success(directory):
    for path in sorted(directory.glob('????-??-??-planet.json'), reverse=True):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['status'] in ('updated', 'no_change') and data['source'] == 'Zenodo Planet polygons':
            return data
    return {}


def refresh_planet(*, archive_root, out, waters, receipt_dir, date):
    """Check Planet alone; keep the last good output on any refusal or failure."""
    receipt: dict[str, str | int | None] = dict(
        source='Zenodo Planet polygons', record_url=None, version=None, md5=None, size=None,
        newest_september=None, rights_text=None, rights_text_sha256=None, waters_sha256=None,
        output_sha256=None, status='access_failed', checked_date=date.isoformat(),
    )
    try:
        record = json.loads(_metadata(LATEST))
        version = str(record['id'])  # Zenodo's immutable version-specific record ID.
        if record['conceptdoi'] != POLYGON_CONCEPT or not re.fullmatch(r'[1-9][0-9]*', version):
            raise Refusal('latest result is not a version of the approved polygon series')
        page = f'{ZENODO}/records/{version}'
        receipt.update(version=version, record_url=page)
        rights = _Rights(_metadata(page))
        receipt.update(rights_text=rights.text, rights_text_sha256=hashlib.sha256(rights.text.encode()).hexdigest())
        if not rights.permits(record.get('metadata', {})):
            receipt['status'] = 'rights_changed'
        year, name, md5, size = _newest_september(record['files'])
        receipt.update(md5=md5, size=size, newest_september=f'{year}-09')
        if receipt['status'] != 'rights_changed':
            raw_waters = waters.read_bytes()
            receipt['waters_sha256'] = hashlib.sha256(raw_waters).hexdigest()
            output = out / '_kelp' / f'planet-{year}' / 'kelp.pmtiles'
            previous = _last_success(receipt_dir)
            identity = ('version', 'md5', 'size', 'newest_september', 'waters_sha256')
            if (all(previous.get(k) == receipt[k] for k in identity) and output.is_file()
                    and _sha256(output) == previous.get('output_sha256')):
                receipt.update(status='no_change', output_sha256=previous['output_sha256'])
            else:
                archive = archive_root / version / name
                if not (archive.is_file() and archive.stat().st_size == size
                        and _md5(archive) == md5):
                    _download(f'{ZENODO}/api/records/{version}/files/{name}/content', archive, md5, size, year)
                digest = build_planet_pmtiles(archive, year, raw_waters, output, version)
                receipt.update(status='updated', output_sha256=digest)
    except Exception as exc:
        # GIS/transport failures have library-specific exception types. Only our own
        # messages are safe here; never persist untrusted exception messages or paths.
        receipt['error'] = str(exc) if isinstance(exc, Refusal) else type(exc).__name__
    receipt_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=receipt_dir) as tmp:
        staged = Path(tmp) / 'receipt.json'
        staged.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        staged.replace(receipt_dir / f'{date.isoformat()}-planet.json')
    return receipt


def _md5(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()
