"""F06-07 / SCA-263: BAG embedded metadata is bounded in decoded bytes, not elements.

Contract: native-container admission and the XML readers accept only the BAG
fixed-width one-byte character layout and cap its byte length before any bulk
read. The believable bug: checking ``dataset.size`` (an element count) lets a
wide fixed-width dtype (``S8``) or a variable-length string pass the guard and
then be fully materialised, so the one-million-byte ceiling is not real.
"""
import pytest

pytestmark = pytest.mark.gis  # Writes real synthetic HDF5 containers.

from skippercast.coastal.handoff import common  # noqa: E402

XML = '<gmi:MI_Metadata>synthetic</gmi:MI_Metadata>'


def _bag(tmp_path, metadata):
    import h5py
    import numpy as np
    path = tmp_path / 'synthetic.bag'
    with h5py.File(path, 'w') as bag:
        root = bag.create_group('BAG_root')
        root.create_dataset('elevation', data=np.zeros((1, 1), dtype='f4'))
        root.create_dataset('uncertainty', data=np.zeros((1, 1), dtype='f4'))
        metadata(root)
    return path


def _admit(tmp_path, metadata):
    path = _bag(tmp_path, metadata)
    return common.validate_native_source(tmp_path, common.ref(tmp_path, path, 'synthetic-bag-v1'))


def test_ordinary_s1_and_u1_metadata_admitted_and_decoded(tmp_path):
    import h5py
    import numpy as np
    data = np.frombuffer((XML + '\0\0').encode(), dtype='S1')
    path = _admit(tmp_path, lambda root: root.create_dataset('metadata', data=data))
    with h5py.File(path, 'r') as bag:
        assert common.read_bag_metadata_text(bag['BAG_root']['metadata']) == XML
    other = tmp_path / 'other'
    other.mkdir()
    _admit(other, lambda root: root.create_dataset('metadata', data=np.frombuffer(XML.encode(), dtype='u1')))


def test_exact_byte_ceiling_admitted_and_one_over_refused(tmp_path):
    ok, over = tmp_path / 'ok', tmp_path / 'over'
    ok.mkdir(), over.mkdir()
    _admit(ok, lambda root: root.create_dataset('metadata', shape=(1_000_000,), dtype='S1'))
    with pytest.raises(ValueError, match='byte bound exceeded'):
        _admit(over, lambda root: root.create_dataset('metadata', shape=(1_000_001,), dtype='S1'))


@pytest.mark.parametrize('dtype', ['S8', 'S2', '<u4'])
def test_wide_fixed_width_metadata_refused_by_byte_length(tmp_path, dtype):
    # 200_000 elements passes the old element-count guard but decodes to >1 MB.
    with pytest.raises(ValueError, match='fixed-width one-byte'):
        _admit(tmp_path, lambda root: root.create_dataset('metadata', shape=(200_000,), dtype=dtype))


def test_variable_length_metadata_refused(tmp_path):
    import h5py
    import numpy as np
    with pytest.raises(ValueError, match='fixed-width one-byte'):
        _admit(tmp_path, lambda root: root.create_dataset(
            'metadata', data=np.array([XML], dtype=object), dtype=h5py.string_dtype()))


def test_reader_bounds_before_bulk_read():
    import numpy as np

    class Wide:
        dtype, shape, size = np.dtype('S8'), (200_000,), 200_000

        def __getitem__(self, key):
            raise AssertionError('bulk read before byte bound')

    with pytest.raises(ValueError, match='fixed-width one-byte'):
        common.read_bag_metadata_text(Wide())
