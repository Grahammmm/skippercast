"""Offline build receipts: synthetic bytes and injected distribution versions only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/basemap/build_glyphs.py'
spec = importlib.util.spec_from_file_location('build_glyphs', SCRIPT)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
build_helper = build.build_provenance


class GlyphProvenanceTests(unittest.TestCase):
    def test_versions_and_exact_artifacts_are_bound_deterministically(self):
        versions = {'fonttools': 'fixture-ft', 'Pillow': 'fixture-pil',
                    'numpy': 'fixture-np', 'scipy': 'fixture-sp', 'Brotli': 'fixture-br'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.woff2'
            source.write_bytes(b'synthetic font input')
            outputs = [root / '8192-8447.pbf', root / '0-255.pbf']
            for path in outputs:
                path.write_bytes(path.name.encode())
            receipt = build.build_provenance(source, outputs, versions.__getitem__)
            self.assertEqual(receipt['dependencies'], versions)
            self.assertEqual(receipt['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(receipt['parameters'], dict(weight=500, size=24, border=3,
                radius=8, cutoff=0.25, scale=4, ranges=[0, 8192], stack='dm-sans-medium'))
            for path in outputs:
                self.assertEqual(receipt['outputs'][path.name], dict(bytes=len(path.read_bytes()),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            self.assertEqual(json.dumps(receipt, sort_keys=True), json.dumps(
                build.build_provenance(source, reversed(outputs), versions.__getitem__), sort_keys=True))
            outputs[0].write_bytes(b'changed')
            self.assertNotEqual(receipt['outputs'], build.build_provenance(source, outputs,
                versions.__getitem__)['outputs'])

    def test_missing_metadata_is_explicitly_unknown(self):
        def lookup(name):
            if name == 'Pillow':
                return 'fixture-pil'
            raise build.PackageNotFoundError(name)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'synthetic'
            source.write_bytes(b'input')
            self.assertEqual(build.build_provenance(source, [], lookup)['dependencies'], {
                'fonttools': 'UNKNOWN', 'Pillow': 'fixture-pil', 'numpy': 'UNKNOWN',
                'scipy': 'UNKNOWN', 'Brotli': 'UNKNOWN'})

    def test_unexpected_lookup_failure_is_not_disguised_as_unknown(self):
        with patch.object(build, 'version', side_effect=RuntimeError('broken metadata')):
            with self.assertRaises(RuntimeError):
                build.build_provenance(Path('unused'), [], build.version)

    def test_main_emits_receipt_after_building_outputs(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace
        instance = unittest.mock.MagicMock()
        instance.__getitem__.side_effect = lambda key: SimpleNamespace(
            **({'ascent': 1000} if key == 'hhea' else {'unitsPerEm': 1000}))
        instance.getBestCmap.return_value = {}
        modules = {
            'fontTools': SimpleNamespace(),
            'fontTools.ttLib': SimpleNamespace(TTFont=lambda source: SimpleNamespace()),
            'fontTools.varLib': SimpleNamespace(),
            'fontTools.varLib.instancer': SimpleNamespace(instantiateVariableFont=lambda *args: instance),
            'PIL': SimpleNamespace(ImageFont=SimpleNamespace(
                truetype=lambda *args, **kwargs: None, Layout=SimpleNamespace(BASIC=0))),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'synthetic.woff2'
            source.write_bytes(b'fixture')
            output = StringIO()
            receipt_builder = lambda source, outputs: build_helper(
                source, outputs, lambda name: 'fixture-' + name)
            with patch.dict('sys.modules', modules), patch.object(build, 'SOURCE', source), \
                    patch.object(build, 'ROOT', root), patch.object(build, 'OUT', root / 'out'), \
                    patch.object(build, 'build_provenance', side_effect=receipt_builder) as recorder, \
                    redirect_stdout(output):
                build.main()
            receipt = json.loads(output.getvalue().splitlines()[-1])
            self.assertEqual(set(receipt['outputs']), {'0-255.pbf', '8192-8447.pbf'})
            self.assertEqual(receipt['dependencies']['Pillow'], 'fixture-Pillow')
            self.assertEqual(len(list((root / 'out').glob('*.pbf'))), 2)



if __name__ == '__main__':
    unittest.main()
