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


if __name__ == '__main__':
    unittest.main()
