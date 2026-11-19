"""F29-10: ScienceBase's ZIP timestamps are not source identity."""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from tests._support import ROOT

pytestmark = pytest.mark.gis


@pytest.fixture
def source(tmp_path):
    from research.scripts import build_central_sediment_context as context

    manifest = json.loads((ROOT / 'catalog/usgs-central-sediment-source.json').read_text())
    metadata = tmp_path / 'source.xml'
    metadata.write_bytes(b'''<metadata>
        <idinfo><citation><citeinfo><pubdate>2019</pubdate><title>Synthetic Sediment Thickness</title>
        </citeinfo></citation><useconst>public domain</useconst></idinfo>
        <eainfo><detailed><attr><attrdomv><rdom><attrunit>meters</attrunit></rdom></attrdomv></attr></detailed></eainfo>
        <spref><horizsys><planar><gridsys><utm><utmzone>10</utmzone></utm></gridsys></planar></horizsys></spref>
    </metadata>''')
    # Opaque synthetic bytes exercise identity at the validation boundary, before GDAL opens the TIFF.
    payload = b'synthetic raster bytes'

    def package(year, content=payload, *, name=manifest['raster_member'], extra=False, codec=ZIP_DEFLATED):
        buf = BytesIO()
        with ZipFile(buf, 'w') as archive:
            archive.writestr(ZipInfo(name, (year, 1, 1, 0, 0, 0)), content, compress_type=codec)
            if extra:
                archive.writestr('unreviewed-sidecar.aux.xml', b'synthetic sidecar')
        return buf.getvalue()

    manifest.update(archive_sha256=sha256(package(2020)).hexdigest(),
                    metadata_sha256=sha256(metadata.read_bytes()).hexdigest(),
                    raster_sha256=sha256(payload).hexdigest())
    return context, manifest, metadata, payload, package


@pytest.mark.parametrize('year', [2020, 2021], ids=['original', 'retimestamped'])
def test_timestamp_only_repack_preserves_source_identity(source, tmp_path, year):
    context, manifest, metadata, payload, package = source
    archive = tmp_path / 'source.zip'
    raw = package(year)
    archive.write_bytes(raw)
    assert (sha256(raw).hexdigest() == manifest['archive_sha256']) == (year == 2020)
    transport_hash, verified_raster = context.validate_source(manifest, archive, metadata)
    assert transport_hash == sha256(raw).hexdigest()
    assert verified_raster == payload


@pytest.mark.parametrize(('change', 'error'), [
    ('raster', 'GeoTIFF member changed'),
    ('metadata', 'metadata digest changed'),
    ('member-name', 'exact original GeoTIFF'),
    ('extra-member', 'exact original GeoTIFF'),
    ('transport-bound', 'archive exceeded size bound'),
    ('member-bound', 'GeoTIFF exceeded size bound'),
    ('unbounded-codec', 'Unsupported original USGS ZIP compression'),
])
def test_repackaging_does_not_bypass_source_checks(source, tmp_path, monkeypatch, change, error):
    context, manifest, metadata, payload, package = source
    archive = tmp_path / 'source.zip'
    raw = package(2021)
    if change == 'raster':
        raw = package(2021, payload + b' changed')
    elif change == 'metadata':
        metadata.write_bytes(metadata.read_bytes() + b'\n')  # Valid XML, but not the reviewed bytes.
    elif change == 'member-name':
        raw = package(2021, name='other.tif')
    elif change == 'extra-member':
        raw = package(2021, extra=True)
    elif change == 'transport-bound':
        monkeypatch.setattr(context, 'MAX_ARCHIVE_BYTES', len(raw) - 1)
    elif change == 'member-bound':
        monkeypatch.setattr(context, 'MAX_RASTER_BYTES', len(payload) - 1)
    elif change == 'unbounded-codec':
        raw = package(2021, codec=ZIP_BZIP2)
    archive.write_bytes(raw)
    with pytest.raises(ValueError, match=error):
        context.validate_source(manifest, archive, metadata)


@pytest.mark.parametrize('changed', [False, True], ids=['repackaged', 'changed-raster'])
def test_cold_archive_fetch_verifies_before_caching(source, tmp_path, monkeypatch, changed):
    context, manifest, _, payload, package = source
    archive = tmp_path / 'source.zip'
    raw = package(2021, payload + b' changed' if changed else payload)

    class OfflineResponse(BytesIO):
        url = manifest['archive_url']

    def offline_response(request, *, timeout):
        assert request.full_url == OfflineResponse.url
        return OfflineResponse(raw)

    monkeypatch.setattr(context, 'urlopen', offline_response)
    if changed:
        with pytest.raises(ValueError, match='GeoTIFF member changed'):
            context.download_archive_missing(manifest, archive)
        assert not archive.exists()
        assert not list(tmp_path.glob('*.tmp'))
    else:
        context.download_archive_missing(manifest, archive)
        assert archive.read_bytes() == raw
