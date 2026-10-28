"""BM1-RENDER-PRIVATE: render.verify requires the explicit publication prohibition.

render.produce always writes ``publication_prohibited=True``. render.verify must
refuse any packet whose field is not exactly the boolean True, right after schema
admission and before facts, review evidence or the horizon-hold early return.

Every collaborator below the render module boundary (mapping facts, review holds,
rights evidence) is replaced by a labelled SYNTHETIC DOUBLE. The doubles isolate
the publication-prohibition admission only; they are not measured terrain,
alignment, imagery rights, science or end-to-end production evidence, and these
tests open no raster, source, BAG, model, renderer or viewer.

Suites (scripts/accept_bm1_render_private.py):
  focused       PositiveA1, NegativeA2, BoundaryA3
  compatibility Compatibility
  negative      GateControl  (A4: test-only module copy without the gate)
  isolation     Isolation    (A6: fresh file-launched process and the runner)

This module follows the repository layout contract: it takes ROOT from
tests._support and never edits sys.path. Ordinary discovery (pytest, or
``python -m unittest`` with the package importable) runs it like any other unit
module. The acceptance runner owns the file-launched process: it installs the
offline sentinels, redirected filesystem globals and the repository-relative
import path BEFORE importing this module, and records the isolation report the
Isolation tests read back from a fresh runner process.
"""
import collections
import contextlib
import copy
import difflib
import hashlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests._support import ROOT

from skippercast.coastal.handoff import common, render

REPO = ROOT
RUNNER = ROOT / 'scripts' / 'accept_bm1_render_private.py'
RENDER_FILE = ROOT / 'src' / 'skippercast' / 'coastal' / 'handoff' / 'render.py'
OFFLINE_MESSAGE = 'BM1 offline sentinel: network access refused'

PROHIBITION_ERROR = 'render publication prohibition required'
PURPOSE_ERROR = 'explicit known render purpose required'
SCHEMA_ERROR = 'render handoff contract mismatch'
WEBSITE_HOLD = 'product_loader_support_contract_unavailable'
REVIEW_SCHEMA = 'coastal-render-review-v1'
PURPOSES = ('private_preview', 'website_display')
NOW = '2026-10-24T12:00:00+00:00'
REAL_LOAD = common.load

# ---- SYNTHETIC DOUBLES: labelled placeholders, never scientific evidence ----
SYN_RUN = dict(schema='coastal-mapping-run-v1', synthetic=True, segment_id='synthetic-double-segment-0001',
               segment=dict(label='SYNTHETIC DOUBLE segment, not a measured coast', synthetic=True))
SYN_REF = lambda name: dict(path=f'synthetic-double/{name}', sha256='0' * 64, bytes=0,  # noqa: E731
                            contract='synthetic-double-not-evidence')
SYN_RIGHTS = dict(private_use=True, evidence=[SYN_REF('rights-evidence.json')], synthetic_double=True)
SYN_RIGHTS_MISSING = dict(private_use=False, evidence=[], synthetic_double=True)


def syn_review(rights):
    return dict(schema=REVIEW_SCHEMA, synthetic_double=True, rights=copy.deepcopy(rights))


class SyntheticDoubles:
    """SYNTHETIC DOUBLES for render collaborators with call counters.

    _facts, review_holds and resolve never read terrain, imagery, review or rights
    bytes. load delegates to the real common.load so byte-reference manifests keep
    their real hash checks; its review-contract calls count as reviewer reads."""

    def __init__(self, facts_holds=(), review_holds_added=()):
        self.facts_holds = list(facts_holds)
        self.review_holds_added = list(review_holds_added)
        self.calls = collections.Counter()

    def _facts(self, root, run, imagery, alignment, *, now, rights=None, minimum_valid_until=None):
        self.calls['_facts'] += 1
        facts = dict(mapping_digest='synthetic-double-mapping-digest', native_facts_digest='synthetic-double-native',
                     terrain=SYN_REF('terrain.tif'), mask=SYN_REF('mask.tif'),
                     vertical=dict(datum='SYNTHETIC-DOUBLE', units='m'), imagery=copy.deepcopy(imagery),
                     alignment=copy.deepcopy(alignment), rights=copy.deepcopy(rights),
                     segment=copy.deepcopy(run['segment']), segment_id=run['segment_id'], synthetic_double=True)
        return facts, sorted(set(self.facts_holds))

    def review_holds(self, root, review, facts_digest, *, now, minimum_valid_until=None, schema=None):
        self.calls['review_holds'] += 1
        if review is None:
            return ['independent_review_missing']
        return sorted(set(self.review_holds_added))

    def load(self, root, value, *, contract=None):
        self.calls[f'load:{contract}'] += 1
        return REAL_LOAD(root, value, contract=contract)

    def resolve(self, root, artifact, *, contract=None, cap=None):
        self.calls['resolve'] += 1
        return Path(root) / 'synthetic-double-not-read'

    def reviewer_reads(self):
        return self.calls['review_holds'] + self.calls[f'load:{REVIEW_SCHEMA}'] + self.calls['resolve']

    @contextlib.contextmanager
    def installed(self, module):
        with contextlib.ExitStack() as stack:
            for name in ('_facts', 'review_holds', 'load', 'resolve'):
                stack.enter_context(mock.patch.object(module, name, getattr(self, name)))
            yield self


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class _RenderCase(unittest.TestCase):
    render_module = None  # GateControl injects a test-only module copy

    @property
    def r(self):
        return type(self).render_module or render

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='bm1-render-'))
        self.outputs = 0

    def produce(self, *, kind='ready'):
        """Create a packet through the real produce with synthetic doubles."""
        facts_holds, review, rights, extra = [], syn_review(SYN_RIGHTS), SYN_RIGHTS, []
        if kind == 'rights_hold':
            review, rights = syn_review(SYN_RIGHTS_MISSING), SYN_RIGHTS_MISSING
        elif kind == 'evidence_hold':
            review, rights = None, None
        elif kind == 'validity_hold':
            facts_holds = ['independent_correspondence_review_insufficient_validity']
        elif kind == 'review_hold':
            extra = ['synthetic_double_review_hold']
        elif kind != 'ready':
            raise AssertionError(kind)
        doubles = SyntheticDoubles(facts_holds, extra)
        self.outputs += 1
        with doubles.installed(self.r):
            doc = self.r.produce(self.root, copy.deepcopy(SYN_RUN), output_dir=f'handoff-{self.outputs}', now=NOW,
                                 imagery=SYN_REF('imagery.tif'), alignment=SYN_REF('alignment.json'),
                                 review=copy.deepcopy(review), rights=copy.deepcopy(rights))
        return doc, doubles

    def verify(self, doc, doubles, purpose='private_preview', root=None):
        doubles.calls.clear()
        with doubles.installed(self.r):
            return self.r.verify(self.root if root is None else root, doc, now=NOW, purpose=purpose)

    def assertRefusedEarly(self, doc, doubles, purpose, message=PROHIBITION_ERROR):
        before = canonical(doc) if isinstance(doc, dict) else None
        with self.assertRaises(ValueError) as caught:
            self.verify(doc, doubles, purpose)
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(doubles.calls['_facts'], 0, 'facts must not be computed before admission')
        self.assertEqual(doubles.reviewer_reads(), 0, 'review evidence must not be read before admission')
        if before is not None:
            self.assertEqual(canonical(doc), before, 'packet must not be repaired or mutated')


def with_prohibition(doc, value):
    changed = copy.deepcopy(doc)
    if value is MISSING:
        del changed['publication_prohibited']
    else:
        changed['publication_prohibited'] = value
    return changed


MISSING = object()


class PositiveA1(_RenderCase):
    def test_producer_emits_exact_true(self):
        doc, _ = self.produce()
        self.assertIs(doc['publication_prohibited'], True)
        written = json.loads((self.root / f'handoff-{self.outputs}' / 'render-handoff.json').read_text())
        self.assertIs(written['publication_prohibited'], True)
        self.assertEqual(canonical(written), canonical(doc))

    def test_private_true_ready(self):
        doc, doubles = self.produce()
        self.assertEqual(doc['state'], 'PRIVATE_PREVIEW_READY')
        result = self.verify(doc, doubles, 'private_preview')
        self.assertIs(result['ready'], True)
        self.assertEqual(result['holds'], [])
        self.assertEqual(result['selected_slice_ids'], [SYN_RUN['segment_id']])
        self.assertIs(result['document'], doc)
        self.assertEqual(result['facts'], doc['facts'])
        self.assertEqual(doubles.calls['_facts'], 1)

    def test_website_true_held(self):
        doc, doubles = self.produce()
        result = self.verify(doc, doubles, 'website_display')
        self.assertIs(result['ready'], False)
        self.assertEqual(result['holds'], [WEBSITE_HOLD])
        self.assertEqual(result['selected_slice_ids'], [])
        self.assertIs(result['document'], doc)

    def test_doubles_are_labelled_synthetic(self):
        doc, _ = self.produce()
        self.assertIs(doc['synthetic'], True)
        self.assertIs(doc['facts']['synthetic_double'], True)
        self.assertIs(doc['review']['synthetic_double'], True)
        self.assertTrue(all(v['contract'] == 'synthetic-double-not-evidence'
                            for v in (doc['facts']['terrain'], doc['facts']['mask'], doc['facts']['imagery'])))


class NegativeA2(_RenderCase):
    def _refuse(self, value):
        for purpose in PURPOSES:
            with self.subTest(purpose=purpose):
                doc, doubles = self.produce()
                self.assertRefusedEarly(with_prohibition(doc, value), doubles, purpose)

    def test_refuses_missing(self):
        self._refuse(MISSING)

    def test_refuses_false(self):
        self._refuse(False)

    def test_refuses_null(self):
        self._refuse(None)

    def test_refuses_zero(self):
        self._refuse(0)

    def test_refuses_integer_one(self):
        self._refuse(1)

    def test_refuses_float_one(self):
        self._refuse(1.0)

    def test_refuses_true_string(self):
        self._refuse('true')

    def test_refuses_capitalised_true_string(self):
        self._refuse('True')

    def test_refuses_empty_list(self):
        self._refuse([])

    def test_refuses_empty_object(self):
        self._refuse({})

    def test_refuses_nonempty_list(self):
        self._refuse([True])

    def test_refuses_nonempty_object(self):
        self._refuse({'publication_prohibited': True})

    def test_unknown_purpose_precedes_prohibition(self):
        doc, doubles = self.produce()
        for purpose in ('public_website', None, 'PRIVATE_PREVIEW'):
            with self.subTest(purpose=purpose):
                self.assertRefusedEarly(with_prohibition(doc, MISSING), doubles, purpose, PURPOSE_ERROR)

    def test_wrong_schema_precedes_prohibition(self):
        doc, doubles = self.produce()
        for schema in ('render-handoff-v2.0', None, MISSING):
            for purpose in PURPOSES:
                with self.subTest(schema=schema, purpose=purpose):
                    changed = with_prohibition(doc, False)
                    if schema is MISSING:
                        del changed['schema']
                    else:
                        changed['schema'] = schema
                    self.assertRefusedEarly(changed, doubles, purpose, SCHEMA_ERROR)


HOLD_KINDS = {
    'rights_hold': dict(holds=['imagery_private_rights_missing']),
    'evidence_hold': dict(holds=['independent_review_missing']),
    'validity_hold': dict(holds=['independent_correspondence_review_insufficient_validity'], early=True),
}


class BoundaryA3(_RenderCase):
    def _held(self, kind):
        expected = HOLD_KINDS[kind]
        doc, doubles = self.produce(kind=kind)
        self.assertIs(doc['publication_prohibited'], True)
        self.assertEqual(doc['selected_slice_ids'], [])
        for purpose in PURPOSES:
            with self.subTest(purpose=purpose):
                result = self.verify(doc, doubles, purpose)
                holds = list(expected['holds'])
                if purpose == 'website_display' and not expected.get('early'):
                    holds = sorted(holds + [WEBSITE_HOLD])
                self.assertIs(result['ready'], False)
                self.assertEqual(result['holds'], holds)
                self.assertEqual(result['selected_slice_ids'], [])
                self.assertIs(result['document'], doc)

    def test_rights_hold_true_flag_stays_held(self):
        self._held('rights_hold')

    def test_evidence_hold_true_flag_stays_held(self):
        self._held('evidence_hold')

    def test_insufficient_validity_hold_true_flag_returns_typed_hold(self):
        self._held('validity_hold')

    def test_holds_cannot_hide_missing_or_false_prohibition(self):
        for kind in HOLD_KINDS:
            for value in (MISSING, False, 1):
                for purpose in PURPOSES:
                    with self.subTest(kind=kind, value=value, purpose=purpose):
                        doc, doubles = self.produce(kind=kind)
                        self.assertRefusedEarly(with_prohibition(doc, value), doubles, purpose)

    def test_replay_with_fresh_copies_is_stable_and_non_mutating(self):
        for kind in ('ready', *HOLD_KINDS):
            doc, doubles = self.produce(kind=kind)
            frozen = canonical(doc)
            for purpose in PURPOSES:
                with self.subTest(kind=kind, purpose=purpose):
                    first = self.verify(copy.deepcopy(doc), doubles, purpose)
                    second = self.verify(copy.deepcopy(doc), doubles, purpose)
                    for key in ('ready', 'holds', 'selected_slice_ids'):
                        self.assertEqual(first[key], second[key])
                    self.assertEqual(canonical(first['document']), frozen)
                    for value in (MISSING, False):
                        self.assertRefusedEarly(with_prohibition(doc, value), doubles, purpose)
                        self.assertRefusedEarly(with_prohibition(doc, value), doubles, purpose)
            self.assertEqual(canonical(doc), frozen)


class Compatibility(_RenderCase):
    """Pre-existing verify behavior on True-flag packets, real verify function."""

    def _raises(self, doc, doubles, message, purpose='private_preview'):
        with self.assertRaises(ValueError) as caught:
            self.verify(doc, doubles, purpose)
        self.assertEqual(str(caught.exception), message)

    def test_unknown_purpose_error_preserved(self):
        doc, doubles = self.produce()
        for purpose in ('public', None, '', 'PRIVATE_PREVIEW'):
            with self.subTest(purpose=purpose):
                self._raises(doc, doubles, PURPOSE_ERROR, purpose)

    def test_wrong_schema_error_preserved(self):
        doc, doubles = self.produce()
        for purpose in PURPOSES:
            changed = copy.deepcopy(doc)
            changed['schema'] = 'render-handoff-v2.0'
            self._raises(changed, doubles, SCHEMA_ERROR, purpose)

    def test_byte_reference_manifest_round_trip(self):
        doc, doubles = self.produce()
        manifest = common.ref(self.root, f'handoff-{self.outputs}/render-handoff.json', render.SCHEMA)
        private = self.verify(manifest, doubles, 'private_preview')
        self.assertEqual((private['ready'], private['holds'], private['selected_slice_ids']),
                         (True, [], [SYN_RUN['segment_id']]))
        self.assertEqual(canonical(private['document']), canonical(doc))
        website = self.verify(manifest, doubles, 'website_display')
        self.assertEqual((website['ready'], website['holds'], website['selected_slice_ids']),
                         (False, [WEBSITE_HOLD], []))

    def test_byte_reference_tamper_refused_by_real_load(self):
        self.produce()
        relative = f'handoff-{self.outputs}/render-handoff.json'
        manifest = common.ref(self.root, relative, render.SCHEMA)
        path = self.root / relative
        path.write_text(path.read_text().replace('"publication_prohibited":true', '"publication_prohibited":false'))
        self._raises(manifest, SyntheticDoubles(), 'artifact bytes/hash changed')

    def test_segment_lineage_error_preserved(self):
        doc, doubles = self.produce()
        changed = copy.deepcopy(doc)
        changed['segment_id'] = 'synthetic-double-other-segment'
        self._raises(changed, doubles, 'render segment lineage changed')

    def test_facts_digest_forgery_preserved(self):
        doc, doubles = self.produce()
        for mutate in (lambda d: d.update(facts_digest='0' * 64),
                       lambda d: d['facts'].update(mapping_digest='synthetic-double-forged')):
            changed = copy.deepcopy(doc)
            mutate(changed)
            self._raises(changed, doubles, 'render facts changed or forged')

    def test_selection_changes_preserved(self):
        doc, doubles = self.produce()
        mutations = (
            lambda d: d.update(selected_slice_ids=[]),
            lambda d: d.update(website_selected_slice_ids=[SYN_RUN['segment_id']]),
            lambda d: d['slices'].append(copy.deepcopy(d['slices'][0])),
            lambda d: d['slices'][0].update(private_preview=dict(state='held', holds=['x'])),
            lambda d: d['slices'][0].update(website_display=dict(state='accepted', holds=[])),
            lambda d: d['slices'][0].update(mask=SYN_REF('other-mask.tif')),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                changed = copy.deepcopy(doc)
                mutate(changed)
                self._raises(changed, doubles, 'derived render selection changed')

    def test_review_holds_added_still_hold(self):
        doc, doubles = self.produce(kind='review_hold')
        private = self.verify(doc, doubles, 'private_preview')
        self.assertEqual((private['ready'], private['holds'], private['selected_slice_ids']),
                         (False, ['synthetic_double_review_hold'], []))
        website = self.verify(doc, doubles, 'website_display')
        self.assertEqual(website['holds'], sorted(['synthetic_double_review_hold', WEBSITE_HOLD]))

    def test_validity_hold_early_return_shape_preserved(self):
        doc, doubles = self.produce(kind='validity_hold')
        result = self.verify(doc, doubles, 'website_display')
        self.assertEqual(sorted(result), ['document', 'facts', 'holds', 'ready', 'selected_slice_ids'])
        self.assertEqual(result['holds'], ['independent_correspondence_review_insufficient_validity'])

    def test_validate_alias_and_signature_preserved(self):
        self.assertIs(self.r.validate, self.r.verify)
        self.assertEqual(str(inspect.signature(self.r.verify)),
                         "(root, manifest, *, now, purpose='private_preview', minimum_valid_until=None)")


GATE_LINES = ("    if doc.get('publication_prohibited') is not True:\n"
              "        raise ValueError('render publication prohibition required')\n")
DECIDING = ('test_refuses_missing', 'test_refuses_false', 'test_refuses_null', 'test_refuses_zero',
            'test_refuses_integer_one', 'test_refuses_float_one', 'test_refuses_true_string',
            'test_refuses_capitalised_true_string', 'test_refuses_empty_list', 'test_refuses_empty_object',
            'test_refuses_nonempty_list', 'test_refuses_nonempty_object')
POSITIVE_CONTROLS = (
    (PositiveA1, 'test_private_true_ready'), (PositiveA1, 'test_website_true_held'),
    (BoundaryA3, 'test_rights_hold_true_flag_stays_held'), (BoundaryA3, 'test_evidence_hold_true_flag_stays_held'),
    (BoundaryA3, 'test_insufficient_validity_hold_true_flag_returns_typed_hold'),
    (NegativeA2, 'test_unknown_purpose_precedes_prohibition'), (NegativeA2, 'test_wrong_schema_precedes_prohibition'),
)


class GateControl(unittest.TestCase):
    """A4: a test-only complete-module copy with only the new gate removed."""

    @classmethod
    def setUpClass(cls):
        cls.source = Path(render.__file__).read_text()
        cls.workdir = Path(tempfile.mkdtemp(prefix='bm1-gate-control-'))
        if cls.source.count(GATE_LINES) != 1:
            raise AssertionError('candidate gate text not found exactly once')
        cls.mutant_path = cls.workdir / 'render_bm1_gate_removed.py'
        cls.mutant_path.write_text(cls.source.replace(GATE_LINES, ''))
        cls.restored_path = cls.workdir / 'render_bm1_gate_restored.py'
        cls.restored_path.write_text(cls.source)

    @staticmethod
    def _load(path):
        spec = importlib.util.spec_from_file_location(f'skippercast.coastal.handoff.{path.stem}', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _run(self, module, cases):
        loaded = []
        for cls, name in cases:
            bound = type(f'{cls.__name__}_{module.__name__.rsplit(".", 1)[-1]}', (cls,), {'render_module': module})
            loaded.append(bound(name))
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.TestSuite(loaded))
        print(f'--- GateControl inner run: {module.__name__} ---\n{stream.getvalue()}', file=sys.stdout)
        owner = lambda test: getattr(test, 'test_case', test)._testMethodName  # noqa: E731 (subTest -> parent)
        failed = {owner(t) for t, _ in result.failures}
        errored = {owner(t) for t, _ in result.errors}
        return result, failed, errored

    def test_mutation_removes_only_the_gate(self):
        diff = [line for line in difflib.unified_diff(self.source.splitlines(True),
                self.mutant_path.read_text().splitlines(True), n=0) if line[:1] in '+-'
                and not line.startswith(('+++', '---'))]
        self.assertEqual(diff, ['-' + line + '\n' for line in GATE_LINES.splitlines()])
        self.assertEqual(hashlib.sha256(self.restored_path.read_bytes()).hexdigest(),
                         hashlib.sha256(Path(render.__file__).read_bytes()).hexdigest())

    def test_gate_removed_fails_deciding_tests_and_keeps_positive_controls(self):
        mutant = self._load(self.mutant_path)
        result, failed, errored = self._run(mutant, [(NegativeA2, n) for n in DECIDING])
        self.assertEqual(result.testsRun, len(DECIDING))
        self.assertEqual(failed, set(DECIDING), 'every deciding refusal must fail without the gate')
        self.assertEqual(errored, set())
        result, failed, errored = self._run(mutant, POSITIVE_CONTROLS)
        self.assertEqual(result.testsRun, len(POSITIVE_CONTROLS))
        self.assertEqual((failed, errored, len(result.skipped)), (set(), set(), 0))
        self.assertTrue(result.wasSuccessful())

    def test_restored_gate_passes_the_same_tests(self):
        restored = self._load(self.restored_path)
        result, failed, errored = self._run(restored, [(NegativeA2, n) for n in DECIDING] + list(POSITIVE_CONTROLS))
        self.assertEqual(result.testsRun, len(DECIDING) + len(POSITIVE_CONTROLS))
        self.assertEqual((failed, errored, len(result.skipped)), (set(), set(), 0))
        self.assertTrue(result.wasSuccessful())


class Isolation(unittest.TestCase):
    """A6: the authored runner's fresh file-launched process, its import closure
    and its argument/output-root boundary. The runner is launched twice for the
    compatibility suite; every run records the isolation report it measured
    in-process before and after importing this module and the candidate."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='bm1-isolation-class-'))
        cls.out = cls.base / 'runner-out'
        cls.receipts = [cls._launch(cls.base, '--suite', 'compatibility', '--output-root', str(cls.out))
                        for _ in range(2)]
        cls.children = sorted(p for p in cls.out.iterdir() if p.is_dir()) if cls.out.is_dir() else []

    @staticmethod
    def _launch(cwd, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
        env.update(TMPDIR=str(cwd))
        return subprocess.run([sys.executable, str(RUNNER), *args], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=600)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='bm1-isolation-'))

    def _runner(self, *args):
        return self._launch(self.tmp, *args)

    def _report(self):
        for done in self.receipts:
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(self.children), 2)
        return self.children[0], json.loads((self.children[0] / 'isolation-report.json').read_text())

    def test_fresh_process_offline_before_project_import(self):
        child, report = self._report()
        self.assertEqual(report['pre_import_project_modules'], [])
        self.assertIs(report['pre_import_test_module_loaded'], False)
        self.assertEqual(report['sentinel'], dict.fromkeys(('create_connection', 'socket_connect', 'getaddrinfo'),
                                                           OFFLINE_MESSAGE))
        self.assertIs(report['dont_write_bytecode'], True)
        self.assertEqual(report['isolated_flag'], 1)
        self.assertEqual(report['pycache_after'], report['pycache_before'])
        run_tmp = (child / 'tmp').resolve()
        self.assertEqual(Path(report['tempdir']).resolve(), run_tmp)
        self.assertEqual(Path(report['home']).resolve(), run_tmp)
        self.assertEqual(report['sys_path_head'], [str(REPO / 'src'), str(REPO)])

    def test_fresh_process_imports_only_the_candidate_closure(self):
        _, report = self._report()
        self.assertEqual(Path(report['render_file']).resolve(), RENDER_FILE.resolve())
        self.assertIn('skippercast.coastal.handoff.render', report['closure'])
        self.assertIn('skippercast.coastal.mapping', report['closure'])
        for name, file in report['closure'].items():
            with self.subTest(module=name):
                self.assertTrue(Path(file).resolve().is_relative_to((REPO / 'src').resolve()), file)
        self.assertEqual(report['path_defaults'], [])

    def test_runner_rejects_unknown_suite_and_extra_arguments(self):
        target = self.tmp / 'refused-out'
        for args in (('--suite', 'everything', '--output-root', str(target)),
                     ('--suite', 'focused', '--output-root', str(target), '--extra'),
                     ('--suite', 'focused'),
                     ('--suite', 'focused', '--output-root', 'relative/out')):
            with self.subTest(args=args):
                done = self._runner(*args)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertFalse(target.exists())
                self.assertFalse((self.tmp / 'relative').exists())

    def test_runner_rejects_repo_contained_root_before_writing(self):
        target = REPO / 'out-bm1-refused-probe'
        self.assertFalse(target.exists())
        done = self._runner('--suite', 'focused', '--output-root', str(target / 'child'))
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn('repository', done.stderr)
        self.assertFalse(target.exists())

    def test_runner_rejects_linked_roots_before_writing(self):
        real = self.tmp / 'link-target'
        real.mkdir()
        alias = self.tmp / 'link-alias'
        alias.symlink_to(real, target_is_directory=True)
        for candidate in (alias, alias / 'child'):
            with self.subTest(root=str(candidate)):
                done = self._runner('--suite', 'focused', '--output-root', str(candidate))
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn('symlink', done.stderr)
                self.assertEqual(list(real.iterdir()), [])

    def test_runner_writes_fresh_bound_evidence(self):
        for done in self.receipts:
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(len(self.children), 2)
        self.assertNotEqual(self.children[0].name, self.children[1].name)
        for child in self.children:
            result = json.loads((child / 'result.json').read_text())
            invocation = json.loads((child / 'invocation.json').read_text())
            self.assertEqual(result['verdict'], 'PASS_REVIEW_REQUIRED')
            self.assertEqual(result['tests_ran'], result['tests_expected'])
            self.assertGreater(result['tests_ran'], 0)
            self.assertEqual(result['skipped'], 0)
            for stream in ('stdout', 'stderr'):
                raw = (child / f'suite.{stream}.txt').read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), result[f'suite_{stream}_sha256'])
            self.assertEqual(hashlib.sha256((child / 'isolation-report.json').read_bytes()).hexdigest(),
                             result['isolation_report_sha256'])
            self.assertEqual(hashlib.sha256((child / 'invocation.json').read_bytes()).hexdigest(),
                             result['invocation_sha256'])
            self.assertEqual(invocation['suite'], 'compatibility')
            self.assertEqual(invocation['hashes']['src/skippercast/coastal/handoff/render.py'],
                             hashlib.sha256(RENDER_FILE.read_bytes()).hexdigest())
            self.assertRegex(invocation['git']['head'], '^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
