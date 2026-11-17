"""Seafloor "Deep" base tiles: colour ramp, nodata transparency and a readable PMTiles v3 archive."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

import numpy as np
import rasterio
from rasterio.transform import from_origin

from scripts import build_bathy_tiles as bt

NODATA = -999999.0


def varints(data, pos, count):
    out = []
    for _ in range(count):
        value = shift = 0
        while True:
            byte = data[pos]
            pos += 1
            value |= (byte & 0x7f) << shift
            shift += 7
            if not byte & 0x80:
                break
        out.append(value)
    return out, pos


def read_archive(path):
    """Minimal independent PMTiles v3 reader: header, metadata and {(z, x, y): png bytes}."""
    data = Path(path).read_bytes()
    assert data[:8] == b'PMTiles\x03' and len(data) > 127
    root_offset, root_length, meta_offset, meta_length, leaf_offset, leaf_length, data_offset, data_length = \
        struct.unpack_from('<QQQQQQQQ', data, 8)
    tiles_addressed = struct.unpack_from('<Q', data, 72)[0]
    header = {'clustered': data[96], 'internal': data[97], 'tile_compression': data[98], 'tile_type': data[99],
              'minzoom': data[100], 'maxzoom': data[101], 'leaf_length': leaf_length,
              'bounds': [v / 1e7 for v in struct.unpack_from('<iiii', data, 102)], 'addressed': tiles_addressed}
    metadata = json.loads(gzip.decompress(data[meta_offset:meta_offset + meta_length]))
    directory = gzip.decompress(data[root_offset:root_offset + root_length])
    (count,), pos = varints(directory, 0, 1)
    deltas, pos = varints(directory, pos, count)
    runs, pos = varints(directory, pos, count)
    lengths, pos = varints(directory, pos, count)
    offsets, pos = varints(directory, pos, count)
    assert pos == len(directory)
    ids, last = [], 0
    for d in deltas:
        last += d
        ids.append(last)
    tiles, expected = {}, 0
    for i in range(count):
        offset = expected if offsets[i] == 0 else offsets[i] - 1
        expected = offset + lengths[i]
        for k in range(runs[i]):
            tiles[ids[i] + k] = data[data_offset + offset:data_offset + offset + lengths[i]]
    return header, metadata, tiles, data_length


def zxy_by_id(z, x, y):
    return bt.tile_id(z, x, y)


def decode_png(png):
    """Tiny PNG decoder for 8-bit RGB/RGBA (filters 0-2 only, which is all the builder writes)."""
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, ihdr = 8, b'', None
    while pos < len(png):
        (length,) = struct.unpack_from('>I', png, pos)
        kind = png[pos + 4:pos + 8]
        body = png[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack_from('>I', png, pos + 8 + length)
        assert crc == zlib.crc32(kind + body) & 0xffffffff
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat += body
        pos += 12 + length
    width, height, depth, colour = ihdr[:4]
    assert depth == 8 and colour in (2, 6)
    bpp = 3 if colour == 2 else 4
    raw = zlib.decompress(idat)
    stride = width * bpp
    rows = np.zeros((height, stride), dtype=np.uint8)
    for y in range(height):
        kind = raw[y * (stride + 1)]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=y * (stride + 1) + 1).astype(np.int32)
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2 and y:
            line = (line + rows[y - 1]) & 255
        else:
            assert kind in (0, 1, 2)
        rows[y] = line
    pixels = rows.reshape(height, width, bpp)
    if bpp == 3:
        pixels = np.concatenate([pixels, np.full((height, width, 1), 255, np.uint8)], axis=-1)
    return pixels


def write_survey(path, size=300, west_nodata=100):
    """A small EPSG:3310 raster off Morro Bay: sloping shelf with a ridge, west part not surveyed."""
    yy, xx = np.mgrid[0:size, 0:size].astype('float64')
    depth = 30 + 0.5 * xx + 12 * np.sin(yy / 18.0) + 25 * np.exp(-(((xx - 200) / 20) ** 2 + ((yy - 150) / 30) ** 2))
    elevation = (-depth).astype('float32')
    elevation[:, :west_nodata] = NODATA
    with rasterio.open(path, 'w', driver='GTiff', width=size, height=size, count=1, dtype='float32',
                       crs='EPSG:3310', transform=from_origin(-122000, -288000, 10, 10), nodata=NODATA) as ds:
        ds.write(elevation, 1)
    return elevation


class RampTests(unittest.TestCase):
    def test_ramp_is_cmocean_deep(self):
        lut = bt.deep_lut()
        self.assertEqual(lut.shape, (256, 3))
        self.assertEqual(lut[0].tolist(), [253, 254, 204])      # cmocean deep, shallow end
        self.assertEqual(lut[128].tolist(), [72, 142, 158])
        self.assertEqual(lut[255].tolist(), [40, 26, 44])        # deep end
        self.assertEqual(bt.deep_colour(np.array([1.0]))[0].tolist(), (lut[255] / 255.0).tolist())

    def test_depth_stretch_matches_the_study_breakpoints(self):
        canyon = bt.style_for_zoom(11)['bp']
        position = bt.ramp_position(np.array([-30.0, -60.0, -250.0, -1600.0, -4000.0, 5.0]), canyon)
        np.testing.assert_allclose(position, [0.0, 0.0, 0.22, 1.0, 1.0, 0.0])
        near = bt.style_for_zoom(13)['bp']
        np.testing.assert_allclose(bt.ramp_position(np.array([-10.0, -35.0, -140.0]), near), [0.22, 0.58, 1.0])

    def test_style_follows_zoom(self):
        self.assertEqual(bt.style_for_zoom(8), bt.style_for_zoom(11))
        self.assertEqual(bt.style_for_zoom(11)['bp'], bt.CANYON['bp'])
        self.assertEqual(bt.style_for_zoom(11)['ve'], 2.2)
        self.assertEqual(bt.style_for_zoom(13)['bp'], bt.NEARSHORE['bp'])
        self.assertEqual(bt.style_for_zoom(15)['ve'], 6.0)
        mid = bt.style_for_zoom(12)
        self.assertEqual(mid['bp'][1], (250.0 + 10.0) / 2)
        self.assertAlmostEqual(mid['ve'], 4.1)

    def test_lit_slopes_are_brighter_than_shaded_slopes(self):
        _, columns = np.mgrid[0:40, 0:40]
        ramp = (-100.0 + 2.0 * columns).astype('float64')       # rises toward the east
        west_light = bt.raw_intensity(ramp, 10.0, 3.0, 270.0)   # the slope faces west, so a western sun lights it
        east_light = bt.raw_intensity(ramp, 10.0, 3.0, 90.0)
        self.assertGreater(west_light[20, 20], east_light[20, 20])
        flat = bt.raw_intensity(np.zeros((8, 8)), 10.0, 3.0, 315.0)
        np.testing.assert_allclose(flat, np.sin(np.radians(bt.ALTITUDE)))
        self.assertEqual(bt.rescale(np.array([0.5, 0.5]), 0.5, 0.5).tolist(), [0.5, 0.5])

    def test_fill_keeps_the_mask_and_never_invents_a_different_valid_depth(self):
        elevation = np.full((6, 6), -50.0)
        elevation[:, :3] = NODATA
        invalid = elevation == NODATA
        filled = bt.fill_nodata(elevation.astype('float32'), invalid)
        self.assertTrue((filled == -50.0).all())                 # nearest valid value only
        self.assertEqual(invalid.sum(), 18)


class ArchiveTests(unittest.TestCase):
    def test_tile_ids_follow_the_hilbert_order_of_the_spec(self):
        self.assertEqual([bt.tile_id(0, 0, 0), bt.tile_id(1, 0, 0), bt.tile_id(1, 0, 1), bt.tile_id(1, 1, 1),
                          bt.tile_id(1, 1, 0)], [0, 1, 2, 3, 4])
        self.assertEqual(bt.tile_id(2, 0, 0), 5)
        self.assertEqual(sorted(bt.tile_id(3, x, y) for x in range(8) for y in range(8)), list(range(21, 85)))

    def test_png_round_trips_and_uses_rgb_only_when_opaque(self):
        rng = np.random.default_rng(3)
        rgba = rng.integers(0, 256, (16, 20, 4), dtype=np.uint8)
        rgba[..., 3] = 255
        opaque = bt.encode_png(rgba)
        self.assertEqual(opaque[25], 2)                           # IHDR colour type 2 = RGB
        np.testing.assert_array_equal(decode_png(opaque), rgba)
        rgba[3, 4, 3] = 0
        clear = bt.encode_png(rgba)
        self.assertEqual(clear[25], 6)
        np.testing.assert_array_equal(decode_png(clear), rgba)
        self.assertEqual(bt.encode_png(rgba), clear)

    def test_archive_directory_deduplicates_and_reads_back(self):
        tiles = {(2, 0, 0): b'AAAA', (2, 1, 0): b'BBBBBB', (2, 0, 1): b'AAAA', (2, 1, 1): b'AAAA'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'a.pmtiles'
            bt.write_pmtiles(path, tiles, metadata={'name': 'x'}, bounds=(-122.0, 35.0, -121.0, 36.0),
                             minzoom=2, maxzoom=2, center=(2, -121.5, 35.5))
            header, metadata, by_id, _ = read_archive(path)
        self.assertEqual((header['minzoom'], header['maxzoom'], header['tile_type'], header['clustered']), (2, 2, 2, 1))
        self.assertEqual(header['bounds'], [-122.0, 35.0, -121.0, 36.0])
        self.assertEqual(metadata, {'name': 'x'})
        self.assertEqual({k: by_id[zxy_by_id(*k)] for k in tiles}, tiles)


class BuildTests(unittest.TestCase):
    @classmethod
    def build_once(cls, directory, name='deep.pmtiles', minzoom=11, maxzoom=13):
        source = Path(directory) / 'elevation.tif'
        if not source.exists():
            write_survey(source)
        output = Path(directory) / name
        bt.build(source, output, minzoom, maxzoom, log=lambda *_: None)
        return output

    def test_unsurveyed_cells_are_transparent_and_surveyed_cells_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            header, metadata, by_id, _ = read_archive(self.build_once(directory))
            self.assertEqual((header['minzoom'], header['maxzoom']), (11, 13))
            self.assertEqual(metadata['format'], 'png')
            self.assertEqual(metadata['type'], 'baselayer')
            self.assertIn('NOT FOR NAVIGATION', metadata['description'])
            self.assertNotIn('/home', json.dumps(metadata))
            west, south, east, north = header['bounds']
            self.assertTrue(-121.5 < west < east < -121.2 and 35.3 < south < north < 35.5, header["bounds"])
            self.assertTrue(by_id)
            seen_clear = seen_opaque = False
            for png in by_id.values():
                pixels = decode_png(png)
                self.assertEqual(pixels.shape, (256, 256, 4))
                alpha = pixels[..., 3]
                self.assertTrue(set(np.unique(alpha)) <= {0, 255})  # a cell is surveyed or it is not; no fake blend
                self.assertTrue((pixels[alpha == 0][:, :3] == 0).all())
                seen_clear |= bool((alpha == 0).any())
                seen_opaque |= bool((alpha == 255).any())
            self.assertTrue(seen_clear and seen_opaque)

    def test_a_flat_bottom_is_the_plain_ramp_colour_and_nodata_stays_clear(self):
        size = bt.TILE + 2 * bt.PAD
        window = np.full((size, size), -35.0, dtype='float32')
        window[:, :size // 2] = NODATA
        invalid = window == NODATA
        tiles = bt.render_zoom({(5, 6): (window, invalid, 15.0)}, 13)
        pixels = decode_png(tiles[(13, 5, 6)])
        wanted = bt.deep_lut()[int(0.58 * 256)]                     # 35 m is the 0.58 breakpoint of the nearshore stretch
        east = pixels[:, -1]
        self.assertTrue((east[:, 3] == 255).all())
        self.assertLessEqual(np.abs(east[:, :3].astype(int) - wanted.astype(int)).max(), 1)
        self.assertTrue((pixels[:, 0, 3] == 0).all())

    def test_deeper_water_is_darker_in_the_ramp(self):
        window = np.tile(np.linspace(-5.0, -130.0, bt.TILE + 2 * bt.PAD, dtype='float32'), (bt.TILE + 2 * bt.PAD, 1))
        tile = decode_png(bt.render_zoom({(0, 0): (window, window == NODATA, 15.0)}, 13)[(13, 0, 0)])
        brightness = tile[128, :, :3].astype(float).sum(axis=1)
        self.assertGreater(brightness[:20].mean(), brightness[-20:].mean() + 150)

    def test_build_is_byte_for_byte_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.build_once(directory, 'a.pmtiles', 12, 12).read_bytes()
            second = self.build_once(directory, 'b.pmtiles', 12, 12).read_bytes()
        self.assertEqual(hashlib.sha256(first).digest(), hashlib.sha256(second).digest())

    def test_wrong_crs_or_missing_source_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong.tif'
            with rasterio.open(path, 'w', driver='GTiff', width=4, height=4, count=1, dtype='float32',
                               crs='EPSG:4326', transform=from_origin(-121, 35, 0.001, 0.001)) as ds:
                ds.write(np.full((1, 4, 4), -5, 'float32'))
            with self.assertRaises(ValueError):
                bt.build(path, Path(directory) / 'x.pmtiles', 12, 12, log=lambda *_: None)
            self.assertEqual(bt.main(['--source', str(Path(directory) / 'missing.tif')]), 2)
            self.assertEqual(bt.main(['--source', str(path), '--minzoom', '9', '--maxzoom', '3']), 2)


class CoverageTests(unittest.TestCase):
    def test_archive_records_zero_to_300ft_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            _, metadata, _, _ = read_archive(BuildTests.build_once(directory, minzoom=12, maxzoom=12))
        detail = metadata['detail_coverage']
        self.assertEqual(detail['background'], {'cells': 6333, 'cell_m': 10, 'km2': 0.6333})
        self.assertEqual(detail['limit_m'], 91.44)
        self.assertIn('sources can overlap, so do not add them', detail['basis'])
        self.assertEqual(detail['native'], [])

    def test_coverage_excludes_land_deep_and_nodata(self):
        values = np.array([[5, -91.44, -91.45, np.nan, NODATA, 0, -30]], dtype='float32')
        self.assertEqual(bt.coverage(values, 10, [])['background'],
                         {'cells': 3, 'cell_m': 10, 'km2': 0.0003})
        self.assertEqual(bt.coverage(values, (10, 20), [])['background'],
                         {'cells': 3, 'cell_m': 10, 'cell_y_m': 20, 'km2': 0.0006})

    def test_native_coverage_uses_the_shallow_mask_and_own_cell_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, fine, output, sidecar = (root / n for n in ('base.tif', 'fine.tif', 'a.pmtiles', 'c.json'))
            write_survey(base)
            values = np.full((32, 32), -25, dtype='float32')
            values[:, 16:] = -100  # half deep; a nodata stripe removes 32 shallow cells
            values[:, 15] = -7
            values[0, 0] = -91.44
            with rasterio.open(fine, 'w', driver='GTiff', width=32, height=32, count=1,
                               dtype='float32', crs='EPSG:3310', nodata=-7, tiled=True,
                               blockxsize=16, blockysize=16,
                               transform=from_origin(-121800, -288200, 2, 2)) as ds:
                ds.write(values, 1)
                valid = np.full((32, 32), 255, dtype='uint8')
                valid[0, 1] = 0  # GDAL-invalid shallow cell must not count either
                ds.write_mask(valid)
            manifest = root / 'native.json'
            manifest.write_text(json.dumps([{'id': 'synthetic', 'path': str(fine), 'resolution_m': 2}]))
            bt.build(base, output, 12, 12, log=lambda *_: None,
                     native_sources=bt.load_native_manifest(manifest), coverage_json=sidecar)
            _, metadata, _, _ = read_archive(output)
            self.assertEqual(metadata['detail_coverage']['native'],
                             [{'id': 'synthetic', 'resolution_m': 2, 'cells': 479, 'km2': 0.0019}])
            self.assertNotIn(str(root), json.dumps(metadata))
            self.assertNotIn(str(root), sidecar.read_text())

    def test_coverage_json_matches_metadata_and_names_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, sidecar = (root / n for n in ('base.tif', 'a.pmtiles', 'coverage.json'))
            write_survey(source)
            sidecar.write_text('stale')
            self.assertEqual(bt.main(['--source', str(source), '--output', str(output),
                                      '--minzoom', '12', '--maxzoom', '12', '--coverage-json', str(sidecar)]), 0)
            _, metadata, _, _ = read_archive(output)
            expected = dict(metadata['detail_coverage'], archive=output.name)
            self.assertEqual(json.loads(sidecar.read_text()), expected)
            self.assertEqual(sidecar.read_text(), json.dumps(expected, indent=2, sort_keys=True) + '\n')
            self.assertFalse(list(root.glob('*.part')))

    def test_coverage_json_with_variant_all_is_refused(self):
        import contextlib
        import io
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, sidecar = root / 'base.tif', root / 'coverage.json'
            write_survey(source)
            err = io.StringIO()
            with contextlib.redirect_stderr(err), mock.patch.object(bt, 'DEFAULT_OUTPUT', root / 'a.pmtiles'):
                code = bt.main(['--source', str(source), '--variant', 'all', '--coverage-json', str(sidecar)])
            self.assertEqual(code, 2)
            self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
            self.assertIn('--coverage-json', err.getvalue())
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['base.tif'])


class EnhancementTests(unittest.TestCase):
    SIZE = bt.TILE + 2 * bt.ENHANCED_PAD

    def ridged_window(self, nodata_cols=0):
        yy, xx = np.mgrid[0:self.SIZE, 0:self.SIZE].astype('float64')
        depth = 25 + 0.04 * xx + 1.5 * np.sin(xx / 6.0) * np.exp(-((yy - 128) / 60) ** 2)
        window = (-depth).astype('float32')
        window[:, :nodata_cols] = NODATA
        return window, window == NODATA

    def render(self, variant, window, invalid):
        tiles = bt.render_zoom({(3, 4): (window, invalid, 15.0)}, 13, bt.ENHANCE[variant])
        return decode_png(tiles[(13, 3, 4)])

    def test_variants_step_up_and_base_is_the_default_look(self):
        keys = ('ve_boost', 'gain_boost', 'unsharp', 'light2', 'curv', 'ev')
        for key in keys:
            values = [bt.ENHANCE[v][key] for v in ('base', 'mild', 'medium', 'strong')]
            self.assertEqual(values, sorted(values), key)
            self.assertEqual(values[0], 0)
        self.assertIs(bt.ENHANCE['base'], bt.BASE_ENHANCE)
        self.assertEqual(bt.pad_for(bt.ENHANCE['base']), bt.PAD)
        self.assertGreater(bt.pad_for(bt.ENHANCE['mild']), bt.PAD)
        self.assertEqual(bt.style_for_zoom(13), bt.style_for_zoom(13, bt.BASE_ENHANCE))
        # the boost on vertical exaggeration and shading is a shelf-zoom effect: none at the canyon zoom
        self.assertEqual(bt.style_for_zoom(11, bt.ENHANCE['strong'])['ve'], bt.style_for_zoom(11)['ve'])
        self.assertGreater(bt.style_for_zoom(13, bt.ENHANCE['strong'])['ve'], bt.style_for_zoom(13)['ve'])
        self.assertEqual(bt.lights_for(bt.ENHANCE['base']), bt.LIGHTS)
        self.assertAlmostEqual(sum(w for _, w in bt.lights_for(bt.ENHANCE['strong'])), 1.0)

    def test_stronger_variants_show_more_relief_and_keep_nodata_clear(self):
        window, invalid = self.ridged_window(nodata_cols=40)
        spread = {}
        for variant in bt.ENHANCE:
            pixels = self.render(variant, window, invalid)
            self.assertTrue((pixels[:, :28, 3] == 0).all())     # no survey stays transparent
            self.assertTrue((pixels[:, 40:, 3] == 255).all())
            spread[variant] = pixels[100:150, 60:200, :3].astype(float).sum(axis=2).std()
        self.assertLess(spread['base'], spread['medium'])
        self.assertLess(spread['medium'], spread['strong'])
        self.assertNotEqual(spread['mild'], spread['base'])   # (mild's opposite light can cancel a one-sided test pattern)

    def test_the_boost_does_not_draw_a_ridge_along_the_survey_edge(self):
        from scipy import ndimage
        window, invalid = self.ridged_window(nodata_cols=60)
        intensity = np.random.default_rng(3).random(window.shape)
        boosted = bt.local_contrast(intensity, invalid, 15.0, bt.ENHANCE['strong'])
        near_edge = ndimage.binary_dilation(invalid, iterations=1) & ~invalid
        self.assertTrue(near_edge.any())
        self.assertTrue(np.allclose(boosted[near_edge], intensity[near_edge]))   # untouched at the edge
        self.assertFalse(np.allclose(boosted[:, 200:], intensity[:, 200:]))      # but working inside the survey
        # bounded: no cell moves by more than amount * clip
        limit = bt.ENHANCE['strong']['unsharp'] * bt.ENHANCE['strong']['clip']
        self.assertLessEqual(np.abs(boosted - intensity).max(), limit + 1e-9)

    def test_adjacent_tiles_match_across_their_shared_edge(self):
        # one surface cut into two tile windows 256 px apart: the enhanced shading must agree at the seam
        yy, xx = np.mgrid[0:self.SIZE, 0:self.SIZE + 256].astype('float64')
        surface = (-(25 + 0.03 * xx + 2.0 * np.sin(xx / 5.0 + yy / 9.0))).astype('float32')
        left, right = surface[:, :self.SIZE], surface[:, 256:256 + self.SIZE]
        no_mask = np.zeros(left.shape, bool)
        tiles = bt.render_zoom({(0, 0): (left, no_mask, 15.0), (1, 0): (right, no_mask, 15.0)}, 13, bt.ENHANCE['strong'])
        a, b = decode_png(tiles[(13, 0, 0)]), decode_png(tiles[(13, 1, 0)])
        # columns just inside each tile around the seam are neighbours of one another on the source surface
        step_across = np.abs(a[:, -1, :3].astype(int) - b[:, 0, :3].astype(int)).mean()
        step_within = np.abs(a[:, -2, :3].astype(int) - a[:, -1, :3].astype(int)).mean()
        self.assertLess(step_across, step_within * 1.6 + 2)

    def test_outputs_are_named_so_the_public_build_guard_catches_them(self):
        names = {v: bt.output_for(v).name for v in bt.ENHANCE}
        self.assertEqual(names['base'], 'morro-bay-seafloor-deep.pmtiles')
        self.assertEqual(names['strong'], 'morro-bay-seafloor-deep.pmtiles')
        self.assertEqual(bt.output_for('strong').parent.name, 'strong')
        self.assertEqual(bt.output_for('mild').parent, bt.DEFAULT_OUTPUT.parent / 'mild')
        self.assertEqual(bt.output_for('mild').parent.parts[-4:], ('var', 'seafloor', 'tiles', 'mild'))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'elevation.tif'
            write_survey(source)
            self.assertEqual(bt.main(['--source', str(source), '--variant', 'all', '--output', str(Path(directory) / 'x')]), 2)

    def test_enhanced_build_is_repeatable_and_records_its_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'elevation.tif'
            write_survey(source)
            first, second = (Path(directory) / n for n in ('a.pmtiles', 'b.pmtiles'))
            bt.build(source, first, 12, 12, log=lambda *_: None, variant='medium')
            bt.build(source, second, 12, 12, log=lambda *_: None, variant='medium')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            _, metadata, by_id, _ = read_archive(first)
            self.assertEqual(metadata['relief_variant'], 'medium')
            self.assertEqual(metadata['relief_settings'], bt.ENHANCE['medium'])
            self.assertTrue(by_id)
            for png in by_id.values():
                self.assertEqual(decode_png(png).shape, (256, 256, 4))


class NativeTierTests(unittest.TestCase):
    def test_locked_native_zoom_and_core_support(self):
        """D6: 1 m/0-20 m reaches z17; deep/invalid/halo-only and coarse grids do not."""
        from rasterio.warp import Resampling, reproject
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'base.tif'
            write_survey(base, size=120, west_nodata=0)
            for resolution, depth, masked, expected_max in (
                (1, -10, False, 17), (0.995, -10, False, 17), (1, -20, False, 17),
                (1, -20.01, False, 15), (1, -10, True, 13),
                (2, -10, False, 15), (5, -10, False, 15),
            ):
                with self.subTest(resolution=resolution, depth=depth, masked=masked):
                    size = int(600 / resolution)
                    values = np.full((size, size), depth, dtype='float32')
                    # A 150 m support patch, surrounded by land/deep whose average looks shallow.
                    values[:, size // 4:] = np.where(np.arange(size - size // 4) % 2, 40, -60)
                    transform = from_origin(-121800, -288200, resolution, resolution)
                    path = root / 'native.tif'
                    valid = np.full(values.shape, 0 if masked else 255, dtype='uint8')
                    with rasterio.open(path, 'w', driver='GTiff', width=size, height=size, count=1,
                                       dtype='float32', crs='EPSG:3310', transform=transform, nodata=NODATA) as ds:
                        ds.write(values, 1)
                        ds.write_mask(valid)
                    manifest = root / 'native.json'
                    manifest.write_text(json.dumps([{'id': 'fixture', 'path': str(path),
                                                     'resolution_m': resolution}]))
                    sources = bt.load_native_manifest(manifest)
                    output = root / 'deep.pmtiles'
                    self.assertEqual(bt.main(['--source', str(base), '--output', str(output),
                                              '--minzoom', '13', '--native-manifest', str(manifest)]), 0)
                    header, metadata, tiles, _ = read_archive(output)
                    self.assertEqual(header['maxzoom'], expected_max)
                    self.assertEqual(metadata['maxzoom'], expected_max)
                    self.assertFalse(any(t >= sum(4 ** i for i in range(18)) for t in tiles))
                    # Independent full-source warp of the validity/depth mask, no production
                    # window/halo/mask_native helper: exact emitted core IDs and tile counts.
                    for z in (14, 15, 16, 17):
                        xs, ys = bt.tile_range(sources[0]['bounds'], z)
                        limit = 20 if z > 15 else 91.44
                        keep = (valid != 0) & (values <= 0) & (values >= -limit)
                        support_values = np.where(keep, values, NODATA).astype('float32')
                        expected = set()
                        if z <= (17 if resolution <= 1 else 15):
                            for x in xs:
                                for y in ys:
                                    dest = np.full((256, 256), NODATA, dtype='float32')
                                    tile_transform, _ = bt.tile_grid(z, x, y, pad=0)
                                    reproject(support_values, dest, src_transform=transform, src_crs='EPSG:3310',
                                              src_nodata=NODATA, dst_transform=tile_transform, dst_crs='EPSG:3857',
                                              dst_nodata=NODATA, resampling=Resampling.average)
                                    count = int(np.count_nonzero(dest != NODATA))
                                    if count:
                                        expected.add(bt.tile_id(z, x, y))

                        start, end = sum(4 ** i for i in range(z)), sum(4 ** i for i in range(z + 1))
                        self.assertEqual({t for t in tiles if start <= t < end}, expected)
                        if str(z) in metadata['native_support_by_zoom']:
                            detail = metadata['native_support_by_zoom'][str(z)]
                            self.assertEqual(detail['tiles'], len(expected))
                            self.assertEqual(detail['sources'], ([{'id': 'fixture', 'resolution_m': resolution,
                                                                  'tiles': len(expected)}]
                                                                if expected else []))
                    if expected_max == 17:
                        self.assertLess(len(expected), len(xs) * len(ys))  # unsupported cores omitted
                    # Explicit requests cannot promote coarse/background grids beyond their cap.
                    bt.build(base, output, 13, 18, log=lambda *_: None, native_sources=sources)
                    self.assertEqual(read_archive(output)[0]['maxzoom'], expected_max)
            bt.build(base, output, 13, 18, log=lambda *_: None)
            self.assertEqual(read_archive(output)[0]['maxzoom'], 13)
            original = output.read_bytes()
            self.assertEqual(bt.main(['--source', str(base), '--output', str(output), '--maxzoom', '18']), 2)
            self.assertEqual(output.read_bytes(), original)

    def test_feather_is_monotonic_without_a_false_ridge_and_keeps_holes(self):
        coarse = np.full((120, 160), -30, dtype='float32')
        native = np.full(coarse.shape, NODATA, dtype='float32')
        native[10:110, 40:120] = -25
        blended, support = bt.feather_tier(coarse, native, 2)
        self.assertTrue(support[60, 80])
        self.assertEqual(blended[60, 40], -30)
        self.assertEqual(blended[60, 80], -25)
        self.assertTrue((np.diff(blended[60, :80]) >= 0).all())
        self.assertGreaterEqual(float(blended.min()), -30)
        self.assertLessEqual(float(blended.max()), -25)
        coarse[:, :50] = NODATA
        blended, _ = bt.feather_tier(coarse, native, 2)
        self.assertEqual(blended[60, 45], -25)  # native-only surveyed support retained
        self.assertEqual(blended[60, 5], NODATA)  # no manufactured support

    def test_native_is_used_only_for_nominal_zero_to_300ft(self):
        coarse = np.full((80, 120), -100, dtype='float32')
        native = np.full_like(coarse, -50)
        native[:, :20] = -100
        native[:, -20:] = 1
        blended, support = bt.feather_tier(coarse, native, 2)
        self.assertFalse(support[:, :20].any())
        self.assertFalse(support[:, -20:].any())
        self.assertTrue((blended[:, :20] == -100).all())
        self.assertTrue((blended[:, -20:] == -100).all())
        self.assertEqual(blended[40, 60], -50)

    def test_native_manifest_checks_spacing_and_orders_five_before_two(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for res in (2, 5, 10):
                path = root / f'{res}.tif'
                with rasterio.open(path, 'w', driver='GTiff', width=40, height=40, count=1,
                                   dtype='float32', crs='EPSG:3310', nodata=NODATA,
                                   transform=from_origin(-122000, -288000, res, res)) as ds:
                    ds.write(np.full((1, 40, 40), -25, 'float32'))
                sources.append({'id': str(res), 'path': str(path), 'resolution_m': res,
                                'source_file': f'{res}.tif', 'archive_sha256': 'a' * 64})
            manifest = root / 'native.json'
            manifest.write_text(json.dumps(sources[:2]))
            loaded = bt.load_native_manifest(manifest)
            self.assertEqual([s['resolution_m'] for s in loaded], [5, 2])
            manifest.write_text(json.dumps(sources))
            with self.assertRaises(ValueError):
                bt.load_native_manifest(manifest)

    def test_finer_native_sector_build_keeps_survey_provenance_at_z15(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'base.tif'
            write_survey(base, size=120, west_nodata=0)
            fine = root / 'fine.tif'
            with rasterio.open(fine, 'w', driver='GTiff', width=300, height=300, count=1,
                               dtype='float32', crs='EPSG:3310', nodata=NODATA,
                               transform=from_origin(-121800, -288200, 1, 1)) as ds:
                ds.write(np.full((300, 300), -25, 'float32'), 1)
            provenance = {'survey_id': 'SYNTHETIC', 'survey_dates': ['2008-11-18', '2008-11-23'],
                          'vertical_datum': 'nominal MLLW; realization unknown',
                          'source_url': 'https://example.test/synthetic.bag',
                          'depth_semantics': 'positive-up elevation metres',
                          'release_date': None}
            entry = {'id': 'synthetic-1m', 'path': str(fine), 'resolution_m': 1,
                     'source_file': 'synthetic.bag', 'archive_sha256': 'b' * 64, **provenance}
            manifest = root / 'native.json'
            manifest.write_text(json.dumps([entry]))
            output = root / 'deep.pmtiles'
            self.assertEqual(bt.main(['--source', str(base), '--output', str(output),
                                      '--native-manifest', str(manifest), '--label', 'Del Norte coast']), 0)
            header, metadata, tiles, _ = read_archive(output)
            self.assertEqual(header['maxzoom'], 15)
            self.assertTrue(any(tid >= sum(4 ** i for i in range(15)) for tid in tiles))
            self.assertIn('SYNTHETIC', metadata['attribution'])
            self.assertEqual(metadata['relief_variant'], 'medium')
            self.assertIn('Del Norte coast', metadata['name'])
            self.assertNotIn('Morro', metadata['description'])
            self.assertIn('NOT FOR NAVIGATION', metadata['description'])
            for key, value in provenance.items():
                self.assertEqual(metadata['native_sources'][0][key], value)
            self.assertNotIn(str(root), json.dumps(metadata))

    def test_native_build_defaults_to_medium_and_writes_z15_with_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'base.tif'
            write_survey(base, size=120, west_nodata=0)
            fine = root / 'fine.tif'
            yy, xx = np.mgrid[0:300, 0:300]
            with rasterio.open(fine, 'w', driver='GTiff', width=300, height=300, count=1,
                               dtype='float32', crs='EPSG:3310', nodata=NODATA,
                               transform=from_origin(-121800, -288200, 2, 2)) as ds:
                ds.write((-(25 + 2 * np.sin(xx / 6) + 0.01 * yy)).astype('float32'), 1)
            manifest = root / 'native.json'
            manifest.write_text(json.dumps([{'id': 'synthetic-2m', 'path': str(fine), 'resolution_m': 2,
                                             'source_file': 'synthetic.tif', 'archive_sha256': 'b' * 64}]))
            output = root / 'deep.pmtiles'
            bt.build(base, output, 13, 15, log=lambda *_: None,
                     native_sources=bt.load_native_manifest(manifest))
            header, metadata, tiles, _ = read_archive(output)
            self.assertEqual(metadata['relief_variant'], 'medium')
            self.assertEqual(header['maxzoom'], 15)
            self.assertTrue(any(tid >= sum(4 ** i for i in range(15)) for tid in tiles))
            self.assertEqual(metadata['native_sources'][0]['archive_sha256'], 'b' * 64)
            self.assertNotIn(str(root), json.dumps(metadata))
            self.assertEqual(metadata['shallow_limit_m'], 91.44)

    def _mixed_native(self, root, west_valid):
        """2 m native grid: optional shallow -60 m block on the west; elsewhere alternating land (+40)
        and deep (-140) columns whose plain average (-50) would look like valid shallow water."""
        cols = np.arange(300)
        grid = np.where(cols % 2 == 0, 40.0, -140.0)[None, :].repeat(300, axis=0)
        if west_valid:
            grid[:, :100] = -60
        path = root / 'mixed.tif'
        with rasterio.open(path, 'w', driver='GTiff', width=300, height=300, count=1, dtype='float32',
                           crs='EPSG:3310', nodata=NODATA,
                           transform=from_origin(-121800, -288200, 2, 2)) as ds:
            ds.write(grid.astype('float32'), 1)
        manifest = root / 'native.json'
        manifest.write_text(json.dumps([{'id': 'mixed-2m', 'path': str(path), 'resolution_m': 2,
                                         'source_file': 'mixed.tif', 'archive_sha256': 'c' * 64}]))
        return bt.load_native_manifest(manifest)

    def test_native_depth_gate_precedes_averaging_in_warp_native(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = self._mixed_native(Path(directory), west_valid=True)
            xs, ys = bt.tile_range(sources[0]['bounds'], 15)
            seen = set()
            for x in xs:
                for y in ys:
                    warped, _ = bt.warp_native(sources[0], 15, x, y, 8)
                    seen.update(np.unique(warped[np.isfinite(warped)]).tolist())
            # Land and deep cells never average into a shallow-looking pixel (-50 is the unmasked mean).
            self.assertTrue(seen)
            for value in seen:
                self.assertTrue(value == NODATA or abs(value + 60) < 1e-3, value)
            self.assertIn(-60.0, {round(v, 3) for v in seen})

    def test_mixed_land_deep_native_gives_no_z15_support_or_relief_through_tiered_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            coarse_transform = from_origin(-121800, -288200, 10, 10)
            coarse = np.full((60, 60), -100, dtype='float32')
            for west_valid in (False, True):
                sources = self._mixed_native(root, west_valid)
                windows = bt.tiered_windows(coarse, coarse_transform, 'EPSG:3310',
                                            sources[0]['bounds'], 15, sources, bt.PAD)
                if not west_valid:
                    self.assertEqual(windows, {})  # nothing shallow-valid: no z15 tile at all
                    continue
                self.assertTrue(windows)  # the genuinely shallow-valid block still qualifies z15
                for window, invalid, _ in windows.values():
                    cells = window[~invalid]
                    # coarse -100 blended toward the true -60 native value only: never the -50 land/deep mean
                    self.assertTrue(np.all((cells >= -100 - 1e-3) & (cells <= -60 + 1e-3)))

    def _masked_native(self, root, grid, valid, nodata=None):
        """2 m native grid with an explicit GDAL validity mask (255 valid / 0 invalid)."""
        path = root / f"masked-{len(list(root.glob('masked-*.tif')))}.tif"
        with rasterio.open(path, 'w', driver='GTiff', width=300, height=300, count=1, dtype='float32',
                           crs='EPSG:3310', nodata=nodata,
                           transform=from_origin(-121800, -288200, 2, 2)) as ds:
            ds.write(grid.astype('float32'), 1)
            ds.write_mask(np.where(valid, 255, 0).astype('uint8'))
        manifest = root / f'{path.stem}.json'
        manifest.write_text(json.dumps([{'id': path.stem, 'path': str(path), 'resolution_m': 2,
                                         'source_file': path.name, 'archive_sha256': 'd' * 64}]))
        return bt.load_native_manifest(manifest)

    def _warped_values(self, source, pad=8):
        xs, ys = bt.tile_range(source['bounds'], 15)
        seen = set()
        for x in xs:
            for y in ys:
                warped, _ = bt.warp_native(source, 15, x, y, pad)
                seen.update(np.unique(warped[np.isfinite(warped)]).tolist())
        return seen

    def test_all_masked_native_has_no_warp_support(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grid = np.full((300, 300), -25.0)
            masked = self._masked_native(root, grid, np.zeros((300, 300), bool))[0]
            with rasterio.open(masked['path']) as ds:
                self.assertIsNone(ds.nodata)
                self.assertFalse(ds.read_masks(1).any())
            self.assertEqual(self._warped_values(masked), {NODATA})
            control = self._masked_native(root, grid, np.ones((300, 300), bool))[0]
            self.assertIn(-25.0, {round(v, 3) for v in self._warped_values(control)})

    def test_masked_native_cannot_qualify_z15(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            coarse = np.full((60, 60), -100, dtype='float32')
            coarse_transform = from_origin(-121800, -288200, 10, 10)
            grid = np.full((300, 300), -25.0)
            for valid, expect_tiles in ((False, False), (True, True)):
                sources = self._masked_native(root, grid, np.full((300, 300), valid))
                windows = bt.tiered_windows(coarse, coarse_transform, 'EPSG:3310',
                                            sources[0]['bounds'], 15, sources, bt.PAD)
                self.assertEqual(bool(windows), expect_tiles)

    def test_native_mask_precedes_averaging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cols = np.arange(300)[None, :].repeat(300, axis=0)
            grid = np.where(cols % 2 == 0, -60.0, -25.0)  # masked -25 columns would average to ~-42
            valid = cols % 2 == 0
            grid[:, 200:] = 40.0   # valid but land: excluded by the depth rule
            valid[:, 200:] = True
            grid[:, 100:150] = -7777.0  # finite nodata sentinel on valid-mask cells (nodata variant)
            valid[:, 100:150] = True
            for nodata in (None, -7777.0):
                source = self._masked_native(root, grid, valid, nodata)[0]
                seen = self._warped_values(source)
                self.assertIn(-60.0, {round(v, 3) for v in seen})  # partial mask: valid cells survive
                for value in seen:
                    self.assertTrue(value == NODATA or abs(value + 60) < 1e-3, (nodata, value))

    def test_same_surface_has_no_tier_edge_ridge_or_tile_join(self):
        size = 320
        yy, xx = np.mgrid[:size, :size + 256]
        surface = (-30 - .003 * xx - .005 * yy).astype('float32')
        native = surface.copy()
        native[:, :150] = NODATA
        native[:, 480:] = NODATA
        left, _ = bt.feather_tier(surface[:, :size], native[:, :size], 4)
        right, _ = bt.feather_tier(surface[:, 256:], native[:, 256:], 4)
        np.testing.assert_allclose(left[:, 256:], right[:, :64], atol=1e-5)
        np.testing.assert_allclose(left, surface[:, :size], atol=1e-5)
        self.assertLess(float(np.abs(bt.ridge_signal(left, left == NODATA)[20:-20, 20:-20]).max()), 1e-4)


class NativeManifestCliTests(unittest.TestCase):
    def _run(self, source, manifest, patches=True):
        import contextlib
        import io
        from unittest import mock
        err = io.StringIO()
        with mock.patch.object(rasterio, 'open') as ropen, contextlib.redirect_stderr(err):
            code = bt.main(['--source', str(source), '--native-manifest', str(manifest)])
        return code, err.getvalue(), ropen

    def test_missing_source_wins_and_manifest_not_read(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(bt, 'load_native_manifest') as load:
                code, err, _ = self._run(Path(tmp) / 'nope.tif', Path(tmp) / 'bad.json')
            load.assert_not_called()
            self.assertEqual(code, 2)
            self.assertIn('source not found', err)

    def test_bad_manifests_exit_2_one_line_without_opening_rasters(self):
        bad = {
            'notjson': 'not json', 'dict': '{}', 'empty': '[]', 'scalar': '[1]',
            'noid': '[{"path": "a.tif", "resolution_m": 1}]',
            'dup': '[{"id": "a", "path": "a.tif", "resolution_m": 1}, {"id": "a", "path": "b.tif", "resolution_m": 1}]',
            'path5': '[{"id": "a", "path": 5, "resolution_m": 1}]',
            'resstr': '[{"id": "a", "path": "a.tif", "resolution_m": "1"}]',
            'restrue': '[{"id": "a", "path": "a.tif", "resolution_m": true}]',
            'resnan': '[{"id": "a", "path": "a.tif", "resolution_m": NaN}]',
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'src.tif'
            source.write_bytes(b'x')
            cases = {name: root / f'{name}.json' for name in bad}
            for name, text in bad.items():
                cases[name].write_text(text)
            cases['missing'] = root / 'missing.json'
            cases['directory'] = root
            for name, manifest in cases.items():
                code, err, ropen = self._run(source, manifest)
                self.assertEqual(code, 2, name)
                self.assertEqual(len(err.strip().splitlines()), 1, (name, err))
                self.assertIn('native manifest:', err, name)
                self.assertNotIn('Traceback', err, name)
                ropen.assert_not_called()

    def test_invalid_native_grid_names_entry_index(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / 'm.json'
            entries = []
            for name, res, count, crs in (
                ('valid', 2, 1, 'EPSG:3310'),
                ('coarse', 10, 1, 'EPSG:3310'),
                ('multiband', 2, 2, 'EPSG:3310'),
                ('geographic', 2, 1, 'EPSG:4326'),
            ):
                path = root / f'{name}.tif'
                with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=count,
                                   dtype='float32', crs=crs, nodata=NODATA,
                                   transform=from_origin(0, 10, res, res)) as ds:
                    ds.write(np.full((count, 2, 2), -25, 'float32'))
                entries.append({'id': name, 'path': str(path), 'resolution_m': res})
            for invalid in entries[1:]:
                with self.subTest(grid=invalid['id']):
                    manifest.write_text(json.dumps([entries[0], invalid]))
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        code = bt.main(['--source', entries[0]['path'],
                                        '--native-manifest', str(manifest)])
                    self.assertEqual(code, 2)
                    self.assertEqual(err.getvalue(), 'build_bathy_tiles: native manifest: entry 1: '
                                     'native grid must be a single-band <=2 m or 5 m projected metre grid\n')
                    self.assertEqual(sorted(p.name for p in root.iterdir()),
                                     ['coarse.tif', 'geographic.tif', 'm.json', 'multiband.tif', 'valid.tif'])

    def test_missing_grid_file_names_entry_index(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'src.tif'
            source.write_bytes(b'x')
            manifest = root / 'm.json'
            manifest.write_text(json.dumps([{'id': 'a', 'path': str(root / 'gone.tif'), 'resolution_m': 1}]))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = bt.main(['--source', str(source), '--native-manifest', str(manifest)])
            self.assertEqual(code, 2)
            self.assertIn('entry 0', err.getvalue())
            self.assertEqual(len(err.getvalue().strip().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
