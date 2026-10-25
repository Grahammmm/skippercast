"""Direct synthetic install tests; importing this module changes no process guards.

The standalone runner supplies a retained synthetic workspace. Ordinary unittest
uses its own temporary tree and cleanup, with no hooks or defaults changed.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from skippercast.seafloor import restore

SEED = Path(__file__).resolve().parents[1] / 'fixtures/sc8c-restore-paths/seed.json'
UNSAFE = 'Unsafe reference restore path'
INPUTS = (
    ('root', 'dist/data/seafloor-ledger.json'),
    ('root', 'catalog/reaches.json'),
    ('staged', 'catalog/reaches.json'),
    ('staged', 'var/seafloor/reference/cells.json'),
    ('staged', 'var/seafloor/reference/run.json'),
)
DIRECTORIES = (
    ('root', 'dist'), ('root', 'dist/data'), ('root', 'catalog'),
    ('staged', 'catalog'), ('staged', 'var'), ('staged', 'var/seafloor'),
    ('staged', 'var/seafloor/reference'), ('root', 'var'),
    ('root', 'var/seafloor'), ('root', 'var/seafloor/reference'),
)
OUTPUTS = tuple(('root', 'var/seafloor/reference/' + name)
                for name in ('cells.json', 'run.json', 'cells.json.restoring', 'run.json.restoring'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    """Never follow links or open a FIFO while recording preservation evidence."""
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            key = path.relative_to(root).as_posix()
            if stat.S_ISLNK(mode):
                result[key] = {'type': 'link', 'target': os.readlink(path)}
            elif stat.S_ISREG(mode):
                result[key] = {'type': 'file', 'sha256': digest(path.read_bytes())}
            elif stat.S_ISDIR(mode):
                result[key] = {'type': 'directory'}
            else:
                result[key] = {'type': 'nonregular', 'mode': stat.S_IFMT(mode)}
    return result


class CopyReached(RuntimeError):
    """No-I/O copy spy: the old install would now write through the link."""


class RestorePaths(unittest.TestCase):
    workspace = None
    evidence = None

    def setUp(self):
        if self.workspace is None:
            temporary = tempfile.TemporaryDirectory(prefix='sc8c-unit-')
            self.addCleanup(temporary.cleanup)
            self.case = Path(temporary.name)
        else:
            self.case = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=self.workspace))
        self.root, self.staged = self.case / 'root', self.case / 'staged'
        self.seed = json.loads(SEED.read_text())
        for base in (self.root, self.staged):
            (base / 'catalog').mkdir(parents=True)
            (base / 'catalog/reaches.json').write_text(self.seed['reaches'])
        reference = self.staged / 'var/seafloor/reference'
        reference.mkdir(parents=True)
        self.write_json(reference / 'cells.json', self.seed['cells'])
        cells_hash = digest((reference / 'cells.json').read_bytes())
        self.write_json(reference / 'run.json', {
            'input_hash': 'baseline', 'output_hashes': {'cells.json': cells_hash}})
        (self.root / 'dist/data').mkdir(parents=True)
        self.ledger = self.root / 'dist/data/seafloor-ledger.json'
        self.write_json(self.ledger, dict(self.seed['ledger_extra'], input_hash='baseline',
                                         reference_cells_sha256=cells_hash))
        (self.case / 'outside').mkdir()
        (self.case / 'outside/sentinel.txt').write_text(self.seed['sentinel'])
        self.addCleanup(self.record)
        self.before = snapshot(self.case)
        self.assertion_class = 'compatibility'

    @staticmethod
    def write_json(path, value):
        path.write_text(json.dumps(value) + '\n')

    def record(self):
        if self.evidence is not None:
            self.evidence.append({'test_id': self.id(), 'assertion_class': self.assertion_class,
                                  'before': self.before, 'after': snapshot(self.case)})

    def existing(self):
        destination = self.root / 'var/seafloor/reference'
        destination.mkdir(parents=True, exist_ok=True)
        for name in ('cells.json', 'run.json', 'cells.json.restoring', 'run.json.restoring'):
            (destination / name).write_text('prior ' + name)
        return destination

    def install_success(self, root=None, staged=None):
        self.before = snapshot(self.case)
        restore.install_verified(self.root if root is None else root,
                                 self.staged if staged is None else staged)
        after = snapshot(self.case)
        for key, value in self.before.items():
            if not key.startswith('root/var/'):
                self.assertEqual(after[key], value, key)
        for name in ('cells.json', 'run.json'):
            self.assertEqual((self.root / 'var/seafloor/reference' / name).read_bytes(),
                             (self.staged / 'var/seafloor/reference' / name).read_bytes())
            self.assertFalse((self.root / 'var/seafloor/reference' / (name + '.restoring')).exists())

    def reject(self, root=None, staged=None):
        self.assertion_class = 'preflight-before-payload-and-copy'
        self.before = snapshot(self.case)
        with patch.object(restore, 'read_json', wraps=restore.read_json) as reads, \
                patch.object(restore, 'sha256', wraps=restore.sha256) as hashes, \
                patch.object(restore.shutil, 'copyfile', side_effect=CopyReached) as copies:
            with self.assertRaisesRegex(ValueError, UNSAFE):
                restore.install_verified(self.root if root is None else root,
                                         self.staged if staged is None else staged)
            reads.assert_not_called()
            hashes.assert_not_called()
            copies.assert_not_called()
        self.assertEqual(snapshot(self.case), self.before)

    def test_fresh_destination(self):
        self.install_success()

    def test_existing_destination(self):
        self.existing()
        self.install_success()

    def test_missing_reference_directory(self):
        (self.root / 'var/seafloor').mkdir(parents=True)
        self.install_success()

    def test_missing_seafloor_directory(self):
        (self.root / 'var').mkdir()
        self.install_success()

    def test_unrelated_venv_link(self):
        (self.root / '.venv').symlink_to(self.case / 'outside', target_is_directory=True)
        self.install_success()

    def test_unresolved_ancestor_aliases(self):
        (self.case / 'alias').symlink_to(self.case, target_is_directory=True)
        self.install_success(self.case / 'alias/root', self.case / 'alias/staged')

    def test_root_alias(self):
        (self.case / 'root-alias').symlink_to(self.root, target_is_directory=True)
        self.install_success(self.case / 'root-alias')

    def test_staged_alias(self):
        (self.case / 'staged-alias').symlink_to(self.staged, target_is_directory=True)
        self.install_success(staged=self.case / 'staged-alias')

    def test_both_aliases(self):
        (self.case / 'root-alias').symlink_to(self.root, target_is_directory=True)
        (self.case / 'staged-alias').symlink_to(self.staged, target_is_directory=True)
        self.install_success(self.case / 'root-alias', self.case / 'staged-alias')

    def mutate(self, boundary, relative, kind):
        self.existing()
        path = getattr(self, boundary) / relative
        held = self.case / 'outside/held'
        path.rename(held)
        if kind == 'link':
            path.symlink_to(held, target_is_directory=held.is_dir())
        elif kind == 'internal-link':
            inside = getattr(self, boundary) / 'held-input'
            held.rename(inside)
            path.symlink_to(inside, target_is_directory=inside.is_dir())
        elif kind == 'file':
            path.write_text('non-directory')
        elif kind == 'directory':
            path.mkdir()
        elif kind == 'fifo':
            os.mkfifo(path)
        elif kind == 'dangling':
            path.symlink_to(self.case / 'absent')
        elif kind != 'missing':
            raise AssertionError(kind)

    def test_reject_symlink_root_var(self):
        """The exact deciding baseline regression; the copy spy never copies."""
        self.mutate('root', 'var', 'link')
        self.reject()

    def test_reject_descendant_through_root_alias(self):
        (self.case / 'root-alias').symlink_to(self.root, target_is_directory=True)
        self.mutate('root', 'var', 'link')
        self.reject(root=self.case / 'root-alias')

    def mismatch(self, kind):
        self.assertion_class = 'original-hash-and-content-gate'
        self.existing()
        cells = self.staged / 'var/seafloor/reference/cells.json'
        receipt = self.staged / 'var/seafloor/reference/run.json'
        ledger = json.loads(self.ledger.read_text())
        run = json.loads(receipt.read_text())
        if kind == 'missing-hash':
            ledger.pop('reference_cells_sha256')
        elif kind == 'cells-hash':
            cells.write_text('changed bytes')
        elif kind == 'cells-input':
            self.write_json(cells, {'input_hash': 'different', 'cells': []})
            ledger['reference_cells_sha256'] = digest(cells.read_bytes())
            run['output_hashes']['cells.json'] = ledger['reference_cells_sha256']
        elif kind == 'receipt-input':
            run['input_hash'] = 'different'
        elif kind == 'receipt-hash':
            run['output_hashes']['cells.json'] = 'different'
        elif kind == 'reaches':
            (self.staged / 'catalog/reaches.json').write_text('different reaches')
        self.write_json(self.ledger, ledger)
        self.write_json(receipt, run)
        self.before = snapshot(self.case)
        with patch.object(restore.shutil, 'copyfile', side_effect=CopyReached) as copies:
            with self.assertRaisesRegex(ValueError, 'differs from committed baseline'):
                restore.install_verified(self.root, self.staged)
            copies.assert_not_called()
        self.assertEqual(snapshot(self.case), self.before)

    def test_mutant_preflight_disabled(self):
        self.assertion_class = 'negative-control-copy-spy'
        self.mutate('root', 'var', 'link')
        self.before = snapshot(self.case)
        # Keep the real install function, hash gates and content unchanged. Only
        # the named preflight helper is disabled; no old function is reimplemented.
        with patch.object(restore, '_preflight_paths', side_effect=lambda root, staged: (root, staged)), \
                patch.object(restore.shutil, 'copyfile', side_effect=CopyReached) as copies:
            with self.assertRaises(CopyReached):
                restore.install_verified(self.root, self.staged)
            self.assertEqual(copies.call_count, 1)
        self.assertEqual(snapshot(self.case), self.before)
        # Prove restoration: the same linked destination now refuses before I/O.
        self.reject()
        self.assertion_class = 'negative-control-copy-spy'
        # And the normal checked positive still succeeds after mutation removal.
        # Use the original root's ordinary inputs, with a fresh destination path:
        # rename the synthetic link rather than delete retained evidence.
        (self.root / 'var').rename(self.case / 'retained-link')
        self.install_success()
        self.mutant_detected = True
        self.positive_passed = True


def add_case(name, body):
    body.__name__ = name
    setattr(RestorePaths, name, body)


for _boundary, _relative in DIRECTORIES + INPUTS + OUTPUTS:
    for _kind in ('link', 'internal-link', 'dangling'):
        def _test(self, boundary=_boundary, relative=_relative, kind=_kind):
            self.mutate(boundary, relative, kind)
            self.reject()
        add_case('test_reject_' + _kind.replace('-', '_') + '_' + _boundary + '_' +
                 _relative.replace('/', '_').replace('.', '_'), _test)

for _boundary, _relative in DIRECTORIES:
    def _test(self, boundary=_boundary, relative=_relative):
        self.mutate(boundary, relative, 'file')
        self.reject()
    add_case('test_reject_nondirectory_' + _boundary + '_' + _relative.replace('/', '_'), _test)

for _boundary, _relative in INPUTS + OUTPUTS:
    for _kind in (('missing', 'directory', 'fifo') if (_boundary, _relative) in INPUTS
                  else ('directory', 'fifo')):
        def _test(self, boundary=_boundary, relative=_relative, kind=_kind):
            self.mutate(boundary, relative, kind)
            self.reject()
        add_case('test_reject_' + _kind + '_' + _boundary + '_' +
                 _relative.replace('/', '_').replace('.', '_'), _test)

for _boundary in ('root', 'staged'):
    for _kind in ('missing', 'dangling', 'loop', 'file'):
        def _test(self, boundary=_boundary, kind=_kind):
            self.existing()
            path = self.case / ('invalid-' + boundary)
            if kind == 'dangling':
                path.symlink_to(self.case / 'absent')
            elif kind == 'loop':
                path.symlink_to(path)
            elif kind == 'file':
                path.write_text('not a boundary directory')
            self.reject(**{boundary: path})
        add_case('test_reject_boundary_' + _boundary + '_' + _kind, _test)

for _kind in ('missing-hash', 'cells-hash', 'cells-input', 'receipt-input', 'receipt-hash', 'reaches'):
    def _test(self, kind=_kind):
        self.mismatch(kind)
    add_case('test_mismatch_' + _kind.replace('-', '_'), _test)


if __name__ == '__main__':
    unittest.main()
