"""A startup copy describes the exact bytes named by its derived_from.sha256 (one read of the source per form)."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.platform.startup_forms import (
    ATLAS_MARKS, POSTER, REGS_STARTUP, SHORELINE_OVERVIEW, PLAN_INDEX, _publish, _publish_text, atlas_marks, derived_from,
    poster_svg, publish_startup_forms)

REAL_READ_BYTES, REAL_READ_TEXT = Path.read_bytes, Path.read_text


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atlas(name):
    return {'schema_version': 1, 'name': name, 'targets': [{'id': 't'}], 'areas': [{'id': 'a'}], 'drifts': [], 'sources': []}


def overview(name='old'):
    return {'type': 'FeatureCollection', 'features': [{'id': 'f', 'properties': {'name': name}, 'geometry': {
        'type': 'MultiLineString', 'coordinates': [[[-121.0, 35.35], [-120.95, 35.36], [-120.9, 35.35]]]}}],
        'provenance': {'bounds': [-121.0, 35.3, -120.9, 35.4], 'attribution': f'credit {name}'}}


def shoreline():
    return {'provenance': {'bounds': [-121.0, 35.3, -120.9, 35.4]}, 'features': [{'id': 'f', 'properties': {}, 'geometry': {
        'type': 'LineString', 'coordinates': [[-121.0, 35.35], [-120.95, 35.37], [-120.9, 35.35]]}}]}


REGISTRY = {'schema_version': 1, 'species': {'salmon': {'source_ids': ['s'], 'primary_source_id': 's'}},
            'sources': {'s': {'url': 'https://example.test/s'}}, 'checks': {'s': {}}}


class Replacing:
    """Patch Path.read_bytes and read_text: the first read of a watched source returns its real content, then the
    source is replaced (so any later reopen sees the new bytes, however the content is read)."""

    def __init__(self, replacements):
        self.replacements, self.captured, self.reads = replacements, {}, {}

    def _wrap(self, real):
        def read(path, *args, **kwargs):
            data = real(path, *args, **kwargs)
            if path in self.replacements:
                raw = data if isinstance(data, bytes) else data.encode()
                self.captured.setdefault(path, raw)
                self.reads[path] = self.reads.get(path, 0) + 1
                path.write_bytes(self.replacements[path](self.captured[path]))
            return data
        return read

    def __enter__(self):
        self.patches = [mock.patch.object(Path, 'read_bytes', autospec=True, side_effect=self._wrap(REAL_READ_BYTES)),
                        mock.patch.object(Path, 'read_text', autospec=True, side_effect=self._wrap(REAL_READ_TEXT))]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self.patches:
            patch.stop()


class SnapshotPairing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_startup_json_payload_hash_share_snapshot(self):
        source, target = self.root / 'atlas.json', self.root / 'marks.json'
        old = json.dumps(atlas('old')).encode()
        source.write_bytes(old)
        new = json.dumps(atlas('new')).encode()
        with Replacing({source: lambda data: new}) as seam:
            _publish(target, source, 'data/atlas.json', atlas_marks)
        copy = json.loads(target.read_text())
        self.assertEqual(copy['name'], 'old')
        self.assertEqual(copy['derived_from'], {'path': 'data/atlas.json', 'sha256': sha(old)})
        self.assertNotEqual(copy['derived_from']['sha256'], sha(new))
        self.assertEqual(seam.reads[source], 1, 'the source content is read exactly once')
        self.assertEqual(source.read_bytes(), new, 'the source stays replaced: nothing is rolled back')

    def test_startup_text_poster_hash_share_snapshot(self):
        source, target = self.root / SHORELINE_OVERVIEW, self.root / POSTER
        old = json.dumps(overview('old')).encode()
        source.write_bytes(old)
        new = json.dumps({**overview('new'), 'provenance': {'bounds': [-122.0, 30.0, -121.0, 31.0], 'attribution': 'credit new'}}).encode()
        with Replacing({source: lambda data: new}) as seam:
            _publish_text(target, source, 'regions/r/' + SHORELINE_OVERVIEW, poster_svg)
        text = target.read_text()
        self.assertEqual(text, poster_svg(json.loads(old), {'path': 'x', 'sha256': sha(old)}))
        self.assertIn(f'data-sha256="{sha(old)}"', text)
        self.assertIn('<title>credit old</title>', text)
        self.assertNotIn(sha(new), text)
        self.assertEqual(seam.reads[source], 1)
        self.assertEqual(source.read_bytes(), new)

    def test_startup_public_orchestration_snapshot_pairing(self):
        output = self.root / 'dist/regions/r'
        output.mkdir(parents=True)
        (self.root / 'dist/data').mkdir()
        sources = {
            output / 'atlas.json': json.dumps(atlas('old')).encode(),
            output / 'plans.json': json.dumps({'schema_version': 1, 'profiles': [{'id': 'p'}], 'features': [1]}).encode(),
            output / 'shoreline.geojson': json.dumps(shoreline()).encode(),
            self.root / 'dist/data/regulations.json': json.dumps(REGISTRY).encode(),
        }
        for path, data in sources.items():
            path.write_bytes(data)
        region = {'id': 'r', 'species': ['salmon'], 'assets': {
            'atlas': 'regions/r/atlas.json', 'search_plans': 'regions/r/plans.json', 'regulations': 'data/regulations.json'}}
        watched = [*sources, output / SHORELINE_OVERVIEW]  # the overview is the poster's source, written by the build
        with Replacing({path: (lambda data: data + b'\n') for path in watched}) as seam:
            written = publish_startup_forms(self.root, region, output)
        self.assertEqual(written, [f'regions/r/{n}' for n in (ATLAS_MARKS, PLAN_INDEX, SHORELINE_OVERVIEW, POSTER, REGS_STARTUP)])
        for name, source in ((ATLAS_MARKS, output / 'atlas.json'), (PLAN_INDEX, output / 'plans.json'),
                             (SHORELINE_OVERVIEW, output / 'shoreline.geojson'),
                             (REGS_STARTUP, self.root / 'dist/data/regulations.json')):
            self.assertEqual(json.loads((output / name).read_text())['derived_from']['sha256'], sha(seam.captured[source]), name)
            self.assertNotEqual(sha(source.read_bytes()), sha(seam.captured[source]), 'the source was replaced after capture')
        poster_source = output / SHORELINE_OVERVIEW
        self.assertIn(f'data-sha256="{sha(seam.captured[poster_source])}"', (output / POSTER).read_text())
        self.assertTrue(all(count == 1 for count in seam.reads.values()), seam.reads)

    def test_startup_hash_is_raw_bytes_not_json_reserialization(self):
        document = {'schema_version': 1, 'name': 'Café 🎣', 'targets': [{'id': 't', 'x': 1.0}], 'areas': [], 'drifts': [], 'sources': []}
        variants = [json.dumps(document).encode(), json.dumps(document, indent=2).encode() + b'\n',
                    json.dumps(document, indent=2).replace('\n', '\r\n').encode(),
                    json.dumps(dict(reversed(list(document.items()))), ensure_ascii=False).encode('utf-8')]
        digests = set()
        for index, raw in enumerate(variants):
            source, target = self.root / f'a{index}.json', self.root / f'm{index}.json'
            source.write_bytes(raw)
            _publish(target, source, 'data/atlas.json', atlas_marks)
            copy = json.loads(target.read_text())
            self.assertEqual(copy['derived_from']['sha256'], sha(raw))
            self.assertEqual((copy['name'], copy['targets']), (document['name'], document['targets']))
            # byte-identical to the form the old two-read path produced for an unchanged source
            expected = self.root / f'e{index}.json'
            atomic_json(expected, atlas_marks(read_json(source), derived_from(source, 'data/atlas.json')))
            self.assertEqual(target.read_bytes(), expected.read_bytes())
            digests.add(copy['derived_from']['sha256'])
        self.assertEqual(len(digests), len(variants))

    def test_startup_snapshot_decoder_remains_strict(self):
        refused = {'nested duplicate key': b'{"a": {"b": 1, "b": 2}}', 'NaN': b'{"a": NaN}', 'Infinity': b'{"a": [Infinity]}',
                   '-Infinity': b'{"a": -Infinity}', 'malformed': b'{"a": ', 'BOM': b'\xef\xbb\xbf{"a": 1}',
                   'invalid UTF-8': b'{"a": "\xff"}'}
        for label, raw in refused.items():
            for writer, form in ((_publish, atlas_marks), (_publish_text, lambda value, source: 'text')):
                for existing in (None, b'sentinel'):
                    with self.subTest(label=label, writer=writer.__name__, existing=existing):
                        source, target = self.root / 'source.json', self.root / 'target.out'
                        target.unlink(missing_ok=True)
                        source.write_bytes(raw)
                        if existing is not None:
                            target.write_bytes(existing)
                        with self.assertRaises(ValueError):
                            writer(target, source, 'data/source.json', form)
                        self.assertEqual(target.read_bytes() if target.exists() else None, existing)

    def test_startup_missing_source_and_valid_outputs_unchanged(self):
        target = self.root / 'marks.json'
        target.write_text('{}')
        self.assertIsNone(_publish(target, self.root / 'gone.json', 'data/gone.json', atlas_marks))
        self.assertIsNone(_publish(target, None, None, atlas_marks))
        self.assertFalse(target.exists(), 'a stale copy is removed as before')


if __name__ == '__main__':
    unittest.main()
