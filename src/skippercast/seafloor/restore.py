"""Reconstruct the private reference cells without replacing a processed ledger."""
from pathlib import Path
import shutil
import stat
import tempfile

from skippercast.platform.contracts import REPO, read_json
from .io import sha256


def _reference_boundary(path):
    """Caller-selected aliases are allowed; only descendants must be link-free."""
    try:
        boundary = Path(path).resolve(strict=True)
        if not boundary.is_dir():
            raise ValueError('not a directory')
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(f'Unsafe reference restore path: {path}') from error
    return boundary


def _check_reference_path(boundary, relative, *, required=False, directory=False):
    """Check lexical components, never resolving a descendant link away.

    This is a preflight, not protection against concurrent path replacement.
    The relative paths are fixed module-owned names, not caller path fragments.
    """
    path = boundary
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        path = path / part
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as error:
            if required:
                raise ValueError(f'Unsafe reference restore path: {path}') from error
            return  # The rest of this fixed destination path does not exist yet.
        except OSError as error:
            raise ValueError(f'Unsafe reference restore path: {path}') from error
        needs_directory = index < len(parts) - 1 or directory
        if not (stat.S_ISDIR(mode) if needs_directory else stat.S_ISREG(mode)):
            raise ValueError(f'Unsafe reference restore path: {path}')


def _preflight_paths(root, staged):
    root, staged = _reference_boundary(root), _reference_boundary(staged)
    for boundary, relative in (
            (root, 'dist/data/seafloor-ledger.json'),
            (root, 'catalog/reaches.json'),
            (staged, 'catalog/reaches.json'),
            (staged, 'var/seafloor/reference/cells.json'),
            (staged, 'var/seafloor/reference/run.json')):
        _check_reference_path(boundary, relative, required=True)
    _check_reference_path(root, 'var/seafloor/reference', directory=True)
    for name in ('cells.json', 'run.json'):
        for suffix in ('', '.restoring'):
            _check_reference_path(root, 'var/seafloor/reference/' + name + suffix)
    return root, staged


def install_verified(root, staged):
    root, staged = _preflight_paths(root, staged)
    ledger = read_json(root / 'dist/data/seafloor-ledger.json')
    expected = ledger.get('reference_cells_sha256')
    cells = staged / 'var/seafloor/reference/cells.json'
    receipt = staged / 'var/seafloor/reference/run.json'
    if (not expected or sha256(cells) != expected
            or read_json(cells)['input_hash'] != ledger['input_hash']
            or read_json(receipt)['input_hash'] != ledger['input_hash']
            or read_json(receipt)['output_hashes']['cells.json'] != expected
            or sha256(staged / 'catalog/reaches.json') != sha256(root / 'catalog/reaches.json')):
        raise ValueError('Rebuilt reference differs from committed baseline; no cache installed')
    destination = root / 'var/seafloor/reference'
    destination.mkdir(parents=True, exist_ok=True)
    for source in (cells, receipt):
        temp = destination / (source.name + '.restoring')
        shutil.copyfile(source, temp)
        temp.replace(destination / source.name)


def restore_reference(*, root=REPO, fetch=False):
    from .grid import build
    root = Path(root)
    with tempfile.TemporaryDirectory(prefix='skippercast-reference-') as temporary:
        staged = Path(temporary)
        (staged / 'catalog').mkdir()
        for name in ('catalog/seafloor-scope.json', 'catalog/bluetopo-sample.json', 'requirements-survey.txt'):
            shutil.copyfile(root / name, staged / name)
        cache = root / 'var/seafloor/reference'
        if cache.exists():
            shutil.copytree(cache, staged / 'var/seafloor/reference',
                            ignore=shutil.ignore_patterns('cells.json', 'run.json'))
        build(root=staged, fetch=fetch)
        install_verified(root, staged)
    return root / 'var/seafloor/reference/cells.json'
