"""F28-05: an authentic archive must match its requested raster role."""

import hashlib
import zipfile

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")
MemoryFile = pytest.importorskip("rasterio.io").MemoryFile
from_origin = pytest.importorskip("rasterio.transform").from_origin

from research.scripts import audit_point_buchon_original_pair as pair
from research.scripts import audit_point_buchon_ncei_beam_overlap as beam
from research.scripts import audit_point_buchon_ncei_multibeam_lead as lead


@pytest.fixture
def archives(tmp_path, monkeypatch):
    paths = []
    for name, value, dtype in [("not-depth.zip", -75, "float32"),
                               ("Bathymetry-decoy.zip", 3, "uint8")]:
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=2, height=2, count=1,
                             dtype=dtype, crs="EPSG:32610",
                             transform=from_origin(0, 4, 2, 2)) as dataset:
                dataset.write(np.full((2, 2), value, dtype=dtype), 1)
            raw = memory.read()
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("raster.tif", raw)
        paths.append(path)
    digests = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    monkeypatch.setattr(pair, "EXPECTED_BATHY", digests[0])
    monkeypatch.setattr(pair, "EXPECTED_CLASS", digests[1])
    return paths, digests


def test_role_authentication_rejects_duplicate_and_crossed_archives(archives, monkeypatch):
    # A digest that is authentic for the other role must not reach a join or fetch.
    (depth, character), _ = archives
    monkeypatch.setattr(beam, "PROBES", {})
    def forbidden_fetch(_url):
        pytest.fail("invalid raster pair reached a fetch")
    for audit in (beam.audit, lead.audit):
        for first, second in ((depth, depth), (character, depth), (character, character)):
            with pytest.raises(ValueError, match="archive hash changed"):
                audit(first, second, fetcher=forbidden_fetch)


def test_correct_renamed_pair_emits_verified_hashes(archives, monkeypatch):
    # This catches filename-based selection and literal expected-hash receipts.
    (depth, character), digests = archives
    monkeypatch.setattr(beam, "PROBES", {})
    report = beam.audit(depth, character, fetcher=lambda _: pytest.fail("unexpected fetch"))
    assert report["usgs_original_bathymetry_sha256"] == digests[0]
    assert report["usgs_original_character_sha256"] == digests[1]
    assert pair.original_tiff(depth, "bathy")[1] == digests[0]
    assert pair.original_tiff(character, "character")[1] == digests[1]
    with pytest.raises(ValueError, match="Unknown USGS raster role"):
        pair.original_tiff(depth, "unrecognized")
