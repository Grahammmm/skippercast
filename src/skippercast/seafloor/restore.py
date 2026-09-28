"""Reconstruct the private reference cells without replacing a processed ledger."""
from pathlib import Path
import shutil
import tempfile

from skippercast.platform.contracts import REPO, read_json
from .io import sha256


def install_verified(root, staged):
    root, staged = Path(root), Path(staged)
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
