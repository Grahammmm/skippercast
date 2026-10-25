"""SC142 synthetic metadata-only contract; safe, scoped ordinary discovery.

No import-time product execution or global patches. The standalone runner supplies
RUN_ROOT; ordinary discovery inherits the caller's temporary root. Evidence is
retained, not deleted. Producer shapes are copied from the pinned source, not a
claim to have executed a downloader or the original integration suite.
"""
import builtins
from contextlib import contextmanager, ExitStack, redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
PRODUCT = REPO / 'research/scripts/coast_mvp/prefetch_receipts_check.py'
FIXTURE = REPO / 'tests/fixtures/sc142-prefetch-metadata-binding/metadata.json'
RUN_ROOT = None
EVIDENCE = []
EXPECTED_GATES = ('input_schema', 'receipt_schema', 'inventory_coverage',
                  'sha256_inventory', 'bytes_inventory', 'reviewed_endpoint_hosts',
                  'received_bytes', 'raw_growth', 'duration', 'requests_per_host',
                  'contact_history', 'retry_pacing')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def object_digest(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


@contextmanager
def offline_boundary(root):
    """Scoped safety controls, not a sandbox for hostile arbitrary Python.

    The checker import closure is stdlib-only. There are no product data roots or
    bound external-root defaults to redirect; check/main receive explicit roots.
    Read-only implementation/fixture/stdlib imports are allowed; data and writes
    are confined to this run. Descriptor-relative metadata traversal is resolved
    against its real parent FD before open. All patches restore for peer tests.
    """
    root = root.resolve()
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    code_files = {PRODUCT.resolve(), FIXTURE.resolve()}
    runtime_roots = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
    real_import = builtins.__import__

    def refused(*args, **kwargs):
        raise RuntimeError('SC142 offline boundary: prohibited network/model/child')

    def checked_path(path, writing=False, directory=False, dir_fd=None):
        if isinstance(path, int):
            return
        candidate = Path(os.fsdecode(path))
        if not candidate.is_absolute():
            parent = Path(os.readlink(f'/proc/self/fd/{dir_fd}')) if dir_fd is not None else Path.cwd()
            candidate = parent / candidate
        candidate = candidate.resolve()
        if candidate.is_relative_to(root):
            return
        if not writing and (candidate in code_files or any(candidate.is_relative_to(p) for p in runtime_roots)):
            return
        if not writing and directory and (candidate == root or candidate in root.parents):
            return
        raise RuntimeError('SC142 offline boundary: external data or write refused')

    def guarded_open(file, mode='r', *args, **kwargs):
        checked_path(file, any(c in mode for c in 'wax+'))
        return real_open(file, mode, *args, **kwargs)

    def guarded_io_open(file, mode='r', *args, **kwargs):
        checked_path(file, any(c in mode for c in 'wax+'))
        return real_io_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        checked_path(path, bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)),
                     bool(flags & os.O_DIRECTORY), kwargs.get('dir_fd'))
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_import(name, *args, **kwargs):
        if name.split('.')[0] not in sys.stdlib_module_names | {'__future__'}:
            raise RuntimeError('SC142 offline boundary: non-stdlib product/model import refused')
        return real_import(name, *args, **kwargs)

    with ExitStack() as stack:
        for target, value in [('builtins.open', guarded_open), ('io.open', guarded_io_open),
                              ('os.open', guarded_os_open), ('builtins.__import__', guarded_import),
                              ('socket.create_connection', refused), ('socket.getaddrinfo', refused),
                              ('socket.socket.connect', refused), ('socket.socket.connect_ex', refused),
                              ('socket.socket.sendto', refused), ('subprocess.Popen', refused),
                              ('os.system', refused), ('os.popen', refused)]:
            stack.enter_context(mock.patch(target, value))
        for name in ('fork', 'forkpty', 'posix_spawn', 'posix_spawnp', 'execv', 'execve',
                     'execvp', 'execvpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe'):
            if hasattr(os, name):
                stack.enter_context(mock.patch.object(os, name, refused))
        yield


def import_product():
    spec = importlib.util.spec_from_file_location('_sc142_metadata_checker', PRODUCT)
    if spec is None or spec.loader is None:
        raise RuntimeError('SC142 checker loader unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=RUN_ROOT)).resolve()
        self.addCleanup(self.save_evidence)
        self.boundary = offline_boundary(self.root)
        self.boundary.__enter__()
        self.addCleanup(self.boundary.__exit__, None, None, None)
        self.product = import_product()
        template = json.loads(FIXTURE.read_text())
        self.plan = template['inventory']
        self.receipts = [template['receipt']]
        self.hosts = template['reviewed_hosts']
        self.sentinel = self.root / 'output-sentinel.txt'
        self.sentinel.write_text('Existing output must remain byte-identical.\n')
        self.payload = self.root / 'opaque-payload.bin'
        self.payload.write_bytes(b'Not the claimed digest or byte count.\n')
        self.receipts[0]['path'] = str(self.payload)
        self.cases = []

    def save_evidence(self):
        EVIDENCE.append({'test': self.id(), 'root': str(self.root), 'cases': getattr(self, 'cases', [])})

    def held(self, report):
        self.assertEqual(tuple(r['gate'] for r in report['gates']), EXPECTED_GATES)
        self.assertTrue(report['review_required'])
        self.assertIs(report['semantic_approval'], False)
        self.assertIs(report['prefetch_qualified'], False)
        for gate in EXPECTED_GATES[6:]:
            self.assertEqual(self.gate(report, gate)['status'], 'HELD', gate)
            self.assertEqual(self.gate(report, gate)['reason'], 'NOT_ESTABLISHED', gate)

    @staticmethod
    def gate(report, gate):
        return next(r for r in report['gates'] if r['gate'] == gate)

    def evaluate(self, plan=None, receipts=None, hosts=None, cli=False):
        plan = self.plan if plan is None else plan
        receipts = self.receipts if receipts is None else receipts
        hosts = self.hosts if hosts is None else hosts
        objects = object_digest([plan, receipts, hosts])
        case = self.root / ('case-' + str(len(self.cases)))
        case.mkdir()
        (case / 'receipts/source').mkdir(parents=True)
        (case / 'inventory.json').write_text(json.dumps(plan))
        (case / 'reviewed-hosts.json').write_text(json.dumps(hosts))
        (case / 'receipts/source/manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in receipts))
        files = [p for p in case.rglob('*') if p.is_file()] + [self.sentinel, self.payload]
        before = {str(p.relative_to(self.root)): digest(p.read_bytes()) for p in files}
        # Product cannot open or hash the opaque path, even though the harness can.
        real_os_open = os.open
        def no_payload(path, flags, *args, **kwargs):
            if not isinstance(path, int) and Path(os.fsdecode(path)).is_absolute():
                self.assertNotEqual(Path(os.fsdecode(path)).resolve(), self.payload)
            return real_os_open(path, flags, *args, **kwargs)
        real_builtin_open, real_io_open = builtins.open, io.open
        def no_payload_stream(real):
            def wrapped(path, *args, **kwargs):
                if not isinstance(path, int):
                    self.assertNotEqual(Path(os.fsdecode(path)).resolve(), self.payload)
                return real(path, *args, **kwargs)
            return wrapped
        with mock.patch('os.open', no_payload), mock.patch('builtins.open', no_payload_stream(real_builtin_open)), mock.patch('io.open', no_payload_stream(real_io_open)):
            if cli:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = self.product.main(['--input-root', str(case)])
                report = json.loads(output.getvalue())
                self.assertEqual(code, report['exit_code'])
            else:
                report = self.product.check(str(case))
        after = {str(p.relative_to(self.root)): digest(p.read_bytes()) for p in files}
        self.assertEqual(before, after)
        self.assertEqual(objects, object_digest([plan, receipts, hosts]))
        self.assertEqual({p for p in case.rglob('*') if p.is_file()}, set(files) - {self.sentinel, self.payload})
        self.held(report)
        self.cases.append({'before': before, 'after': after, 'objects_sha256': objects, 'report': report})
        return report

    def coverage(self, report, state='PASS', reason='EXACT_INVENTORY_COVERAGE'):
        gate = self.gate(report, 'inventory_coverage')
        self.assertEqual((gate['status'], gate['reason']), (state, reason))

    def metadata_mismatch(self):
        report = self.evaluate()
        self.coverage(report, 'FAIL', 'INVENTORY_METADATA_MISMATCH')
        self.assertEqual(report['exit_code'], 1)
        for gate in ('input_schema', 'receipt_schema', 'sha256_inventory', 'bytes_inventory', 'reviewed_endpoint_hosts'):
            self.assertEqual(self.gate(report, gate)['status'], 'PASS')
        return report


class Regression(ContractCase):
    def test_exact_metadata(self):
        report = self.evaluate()
        self.coverage(report)
        self.assertEqual(report['exit_code'], 3)
        for gate in EXPECTED_GATES[:6]:
            self.assertEqual(self.gate(report, gate)['status'], 'PASS')

    def test_repeated_union_and_copy(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                a = copy.deepcopy(self.plan['files'][0])
                b = {**a, 'segments': ['C2']}
                self.plan['files'] = [b, a, a] if reverse else [a, a, b]
                before = object_digest(self.plan)
                indexed = self.product.validate_inventory(self.plan)
                merged = indexed[a['url']]
                self.assertIsNot(merged, a)
                self.assertIsNot(merged, b)
                self.assertEqual(set(merged['segments']), {'C1', 'C2'})
                self.assertEqual(before, object_digest(self.plan))
                self.receipts[0]['segments'] = ['C2', 'C1'] if reverse else ['C1', 'C2']
                report = self.evaluate()
                self.coverage(report)
                self.assertEqual(report['exit_code'], 3)
                # Returned list must not alias a supplied list either.
                merged['segments'].append('N1')
                self.assertEqual(before, object_digest(self.plan))

    def test_missing_segment(self):
        self.plan['files'][0]['segments'] = ['C1', 'C2']
        self.metadata_mismatch()

    def test_extra_segment(self):
        self.receipts[0]['segments'] = ['C1', 'C2']
        self.metadata_mismatch()

    def test_wrong_segment(self):
        self.receipts[0]['segments'] = ['C2']
        self.metadata_mismatch()

    def test_licence_bytes(self):
        for licence in ('Other licence', 'Synthetic licence ', 'synthetic licence'):
            with self.subTest(licence=licence):
                self.receipts[0]['licence'] = licence
                self.metadata_mismatch()

    def test_duplicate_disjoint_mismatch(self):
        a = copy.deepcopy(self.plan['files'][0])
        b = {**a, 'segments': ['C2']}
        for rows in ([a, b], [b, a]):
            for segments in (['C1'], ['C2'], ['C3'], ['C1', 'C2', 'N1']):
                with self.subTest(rows=rows, segments=segments):
                    self.plan['files'] = rows
                    self.receipts[0]['segments'] = segments
                    self.metadata_mismatch()

    def test_conflicting_inventory(self):
        a = self.plan['files'][0]
        for field, value in [('source', 'other-source'), ('bytes', 18), ('sha256', 'b' * 64), ('licence', 'Other licence')]:
            with self.subTest(field=field):
                plan = {**self.plan, 'files': [a, {**a, field: value, 'segments': ['C2']}]}
                report = self.evaluate(plan=plan)
                self.assertEqual(self.gate(report, 'input_schema')['status'], 'FAIL')
                self.assertEqual(report['exit_code'], 1)

    def test_coverage_boundaries(self):
        for kind in ('unknown-url', 'missing-url', 'unresolved', 'unresolved-and-metadata'):
            with self.subTest(kind=kind):
                plan, receipts = copy.deepcopy(self.plan), copy.deepcopy(self.receipts)
                if kind == 'unknown-url':
                    receipts[0]['url'] = 'https://coast.example.test/other.bin'
                elif kind == 'missing-url':
                    plan['files'].append({**plan['files'][0], 'url': 'https://coast.example.test/missing.bin'})
                else:
                    plan['unresolved'] = [{'source': 'synthetic-coast', 'reason': 'synthetic unresolved'}]
                    if kind == 'unresolved-and-metadata':
                        receipts[0]['licence'] = 'Other licence'
                report = self.evaluate(plan, receipts)
                self.coverage(report, 'FAIL', 'INVENTORY_COVERAGE_MISMATCH')
                self.assertEqual(report['exit_code'], 1)

    def test_receipt_boundaries(self):
        for kind, gate, reason in [('duplicate', 'receipt_schema', 'DUPLICATE_RECEIPT_IDENTITY'),
                                   ('hash', 'sha256_inventory', 'UNVERIFIED_OR_MISMATCHED_HASH'),
                                   ('size', 'bytes_inventory', 'UNVERIFIED_OR_MISMATCHED_SIZE'),
                                   ('url-host', 'reviewed_endpoint_hosts', 'EXCLUDED_ENDPOINT_HOST'),
                                   ('final-host', 'reviewed_endpoint_hosts', 'EXCLUDED_ENDPOINT_HOST')]:
            with self.subTest(kind=kind):
                plan, receipts = copy.deepcopy(self.plan), copy.deepcopy(self.receipts)
                if kind == 'duplicate':
                    receipts.append(copy.deepcopy(receipts[0]))
                elif kind == 'hash':
                    receipts[0]['sha256'] = 'b' * 64
                elif kind == 'size':
                    receipts[0]['bytes'] = 18
                elif kind == 'url-host':
                    plan['files'][0]['url'] = receipts[0]['url'] = 'https://excluded.example.test/tile.bin'
                else:
                    receipts[0]['final_url'] = 'https://excluded.example.test/tile.bin'
                report = self.evaluate(plan, receipts)
                self.assertEqual((self.gate(report, gate)['status'], self.gate(report, gate)['reason']), ('FAIL', reason))
                self.assertEqual(report['exit_code'], 1)

    def test_malformed_metadata(self):
        for value in (None, [], ['UNKNOWN'], 'C1', [None]):
            for target in ('plan', 'receipt'):
                with self.subTest(value=value, target=target):
                    plan, receipts = copy.deepcopy(self.plan), copy.deepcopy(self.receipts)
                    (plan['files'][0] if target == 'plan' else receipts[0])['segments'] = value
                    report = self.evaluate(plan, receipts)
                    gate = 'input_schema' if target == 'plan' else 'receipt_schema'
                    self.assertEqual(self.gate(report, gate)['status'], 'FAIL')
                    self.assertEqual(report['exit_code'], 1)
        for plan in (None, [], {}, {'schema_version': True, 'files': []}, {'schema_version': 1, 'files': None}):
            # None means default in evaluate, so test it through validate_inventory.
            with self.subTest(plan=plan):
                with self.assertRaises(self.product.Invalid):
                    self.product.validate_inventory(plan)
        for receipts in ([], [{'url': 'not-a-url'}]):
            report = self.evaluate(receipts=receipts)
            self.assertNotEqual(report['exit_code'], 0)

    def test_object_preservation(self):
        for conflict in (False, True):
            a = copy.deepcopy(self.plan['files'][0])
            b = {**a, 'segments': ['C2', 'C2']}
            if conflict:
                b['bytes'] = 18
            plan = {**self.plan, 'files': [a, b]}
            before = object_digest(plan)
            if conflict:
                with self.assertRaises(self.product.Invalid):
                    self.product.validate_inventory(plan)
            else:
                result = self.product.validate_inventory(plan)
                result[a['url']]['segments'].append('N1')
            self.assertEqual(before, object_digest(plan))


class Compatibility(ContractCase):
    def test_producer_shapes_main(self):
        for verification in ('publisher-sha256', 'http-size-and-local-sha256'):
            for etag, modified in ((None, None), ('"synthetic-etag"', 'Thu, 01 Jan 2026 00:00:00 GMT')):
                with self.subTest(verification=verification, etag=etag):
                    self.receipts[0].update(verification=verification, etag=etag, last_modified=modified,
                                            final_url='https://coast.example.test/redirected.bin')
                    report = self.evaluate(cli=True)
                    self.coverage(report)
                    self.assertEqual(report['exit_code'], 3)

    def test_unknown_inventory_claims(self):
        for field, gate in [('sha256', 'sha256_inventory'), ('bytes', 'bytes_inventory')]:
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                plan['files'][0][field] = None
                report = self.evaluate(plan=plan)
                self.coverage(report)
                self.assertEqual(self.gate(report, gate)['status'], 'FAIL')
                self.assertEqual(report['exit_code'], 1)

    def test_opaque_payload_path(self):
        self.assertNotEqual(digest(self.payload.read_bytes()), self.receipts[0]['sha256'])
        report = self.evaluate(cli=True)
        self.coverage(report)
        self.assertEqual(self.gate(report, 'sha256_inventory')['status'], 'PASS')
        self.assertEqual(report['exit_code'], 3)


def url_coverage_only(plan, receipts):
    """Admitted broken control: URL correspondence alone ignores association."""
    return {r['url'] for r in receipts} == {r['url'] for r in plan['files']} and not plan.get('unresolved')


def last_row_without_union(plan):
    """Admitted in-memory union defect; leaves supplied objects untouched."""
    return {r['url']: copy.deepcopy(r) for r in plan['files']}


def negative_controls():
    """Record expected inner assertion failures, not a fake green unittest run."""
    template = json.loads(FIXTURE.read_text())
    plan, receipts = template['inventory'], [template['receipt']]
    assertion = unittest.TestCase()
    results = []
    def association_assertion(predicate):
        assertion.assertTrue(predicate(plan, receipts), 'exact-metadata positive')
        bad = copy.deepcopy(receipts)
        bad[0]['segments'] = ['C2']
        assertion.assertFalse(predicate(plan, bad), 'wrong segment association must be detected')
    try:
        association_assertion(url_coverage_only)
    except AssertionError as exc:
        results.append({'control': 'url_coverage_only', 'mutant_detected': True, 'inner_assertion': str(exc), 'positive_passed': url_coverage_only(plan, receipts)})
    else:
        raise AssertionError('URL-only mutant escaped')
    case = Regression('test_repeated_union_and_copy')
    case.setUp()
    try:
        with mock.patch.object(case.product, 'validate_inventory', last_row_without_union):
            # A single exact row must still pass under this isolated mutant.
            positive = case.evaluate()
            case.coverage(positive)
            try:
                case.test_repeated_union_and_copy()
            except AssertionError as exc:
                results.append({'control': 'last_row_without_union', 'mutant_detected': True, 'inner_assertion': str(exc), 'positive_passed': positive['exit_code'] == 3})
            else:
                raise AssertionError('Last-row union mutant escaped')
        # Restored actual implementation, complete union positive rerun.
        case.test_repeated_union_and_copy()
    finally:
        case.doCleanups()
    return results
