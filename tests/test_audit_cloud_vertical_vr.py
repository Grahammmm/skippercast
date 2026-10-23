import os, pytest
pytestmark = pytest.mark.skipif(os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1", reason="audit repro: set SKIPPERCAST_AUDIT_CLOUD=1")

import hashlib

np = pytest.importorskip('numpy')
h5py = pytest.importorskip('h5py')
rasterio = pytest.importorskip('rasterio')
pytest.importorskip('pyproj')
pytest.importorskip('shapely')


def _vr_fixture(tmp_path, mutate=None):
    from tests.gis.test_coastal_vr_refinements import make_vr_bag
    from skippercast.coastal.handoff.common import ref
    source = tmp_path / 'H11879_MB_VR_MLLW.bag'
    xml = make_vr_bag(source)
    if mutate is not None:
        mutate(source)
    artifact = ref(tmp_path, source, 'native-raster-v1')
    row = dict(id='synthetic-vr-bag', title=source.name, kind='bathymetry', format='bag',
               url='https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H11879/BAG/' + source.name,
               sha256=artifact['sha256'], horizontal_crs='EPSG:26911', vertical_datum='MLLW')
    return tmp_path, source, artifact, row, hashlib.sha256(xml.encode()).hexdigest()


def test_vr_output_admits_cells_whose_uncertainty_is_nodata(tmp_path):
    """VR refinement cells with a valid depth but nodata (1e6) or NaN uncertainty are
    emitted into the GeoTIFF and then counted as valid native support by
    mapping_input.observe (which reads band 1 only for GTiff). The regular-BAG path
    requires a valid (elevation, uncertainty) pair (source_pair_valid and the explicit
    uncertainty-nodata check), so the same survey cell is dropped when regular and admitted
    when variable-resolution. Expected: VR-derived support excludes cells whose
    uncertainty is nodata or non-finite (receipt valid_cells and observe valid_count both
    count only valid pairs).
    """
    from skippercast.coastal import vertical
    from skippercast.coastal.handoff import mapping_input, vr_refinements as vr
    nodata = np.float32(1_000_000)

    def mutate(path):
        with h5py.File(path, 'r+') as bag:
            ds = bag['BAG_root']['varres_refinements']
            rec = ds[...]
            # records 2 and 3 have valid depths; give them unusable uncertainty
            rec[0, 2]['depth_uncrt'] = nodata
            rec[0, 3]['depth_uncrt'] = np.nan
            ds[...] = rec
    root, source, artifact, row, msha = _vr_fixture(tmp_path, mutate)
    with h5py.File(source) as bag:
        rec = bag['BAG_root']['varres_refinements'][0, :50]
    assert np.isfinite(rec['depth'][2]) and rec['depth'][2] != nodata
    pair_valid = int((np.isfinite(rec['depth']) & (rec['depth'] != nodata)
                      & np.isfinite(rec['depth_uncrt']) & (rec['depth_uncrt'] != nodata)).sum())
    receipt = vr.emit(root, artifact, source_row=row, metadata_sha256=msha, output_dir='derived')
    total = 0
    for output in receipt['outputs']:
        tif = output['artifact']
        with rasterio.open(root / tif['path']) as ds:
            observed = vertical.from_raster(ds, source_sha256=tif['sha256'])
        block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                     evidence=[vertical.evidence_from_observation(observed)])
        h, w = output['shape']
        facts, holds, *_ = mapping_input.observe(root, tif, window=[0, 0, w, h], vertical=block)
        total += facts['valid_count']
    assert total == pair_valid, 'observe admits cells without a valid uncertainty'
    assert receipt['bag']['valid_refinement_cells'] == pair_valid


def test_vr_refinement_null_1e6_counted_valid_when_overview_fill_differs(tmp_path):
    """The VR reader takes refinement nodata from the overview band's HDF5 fill value
    (GDAL nodatavals). BAG fixes the refinement null at 1e6 (BAG_NULL_ELEVATION). If
    the overview fill value is anything else (here -9999), refinement nodes holding 1e6
    are emitted as valid soundings of +1,000,000 m elevation and counted in the receipt
    and by observe. Expected: a 1e6 refinement node is never a valid sounding (or the
    adapter refuses a BAG whose nodata is not 1e6).
    """
    from skippercast.coastal.handoff import vr_refinements as vr

    def mutate(path):
        with h5py.File(path, 'r+') as f:
            r = f['BAG_root']
            for name in ('elevation', 'uncertainty'):
                d = r[name]
                data, attrs = d[:], dict(d.attrs)
                del r[name]
                n = r.create_dataset(name, data=data, fillvalue=np.float32(-9999),
                                     maxshape=(None, None), chunks=True)
                for k, v in attrs.items():
                    n.attrs[k] = v
    root, source, artifact, row, msha = _vr_fixture(tmp_path, mutate)
    try:
        receipt = vr.emit(root, artifact, source_row=row, metadata_sha256=msha, output_dir='derived')
    except ValueError:
        return  # refusing such a BAG is acceptable behaviour
    # Fixture: 50 active nodes, one 1e6 null and one NaN -> 48 soundings.
    assert receipt['bag']['valid_refinement_cells'] == 48
