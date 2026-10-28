"""Portable, inert constructors and reversible offline scope for SC176.

Producer shapes: tests/gis/test_seafloor_government_scope.py (row, ENV,
marker) and seafloor/rights.py (explicit paid for-profit deployment).
No product import or filesystem write occurs at module import.
"""
from contextlib import ExitStack, contextmanager
import builtins
import importlib
import importlib.abc
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
OUTPUT_PREFIX = None
CLOSURE = (
    '__init__.py', 'paths.py', 'platform/__init__.py', 'platform/contracts.py',
    'util/__init__.py', 'util/time.py', 'util/hashing.py', 'http.py',
    'seafloor/__init__.py', 'seafloor/io.py', 'seafloor/rights.py',
    'seafloor/source_scope.py',
)


def row(ident, license='public-domain-us-gov', parents=()):
    return {'id': ident, 'url': 'https://example.test/synthetic-survey',
            'license': license, 'kind': 'bathymetry', 'status': 'usable',
            'sha256': 'a' * 64, 'derived_from': list(parents)}


def invalid_cases():
    public = row('parent')
    private = row('parent', 'csumb-public-use-noncommercial')
    child = row('child', parents=['parent'])
    missing = row('missing'); missing.pop('id')
    cases = {
        'identical': {'surveys': [public, dict(public)]},
        'private-public': {'surveys': [private, public, child]},
        'public-private': {'surveys': [public, private, child]},
        'missing-id': {'surveys': [missing]},
        'surveys-missing': {}, 'surveys-null': {'surveys': None},
        'surveys-object': {'surveys': {}}, 'surveys-string': {'surveys': ''},
        'surveys-tuple': {'surveys': (public,)},
    }
    for label, value in [('empty', ''), ('null', None), ('int', 1),
                         ('bool', True), ('list', []), ('dict', {})]:
        cases[label + '-id'] = {'surveys': [row(value)]}
    for label, value in [('null', None), ('list', []), ('string', 'row'), ('int', 1)]:
        cases['row-' + label] = {'surveys': [value]}
    return cases


def unique_catalog():
    # Deliberately not topological or alphabetical: selection preserves row order.
    return {'revision': 'synthetic', 'surveys': [
        row('leaf', parents=['middle']),
        row('private', 'csumb-public-use-noncommercial'),
        row('middle', parents=['original']), row('original'),
        row('laundered', parents=['private']),
        row('unknown-parent', parents=['absent']),
        row('cycle', parents=['cycle']),
    ]}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def configure(root, manifest):
    write_json(root / 'catalog/surveys.json', manifest)
    write_json(root / 'deployments/production.json', {
        'source_scope': 'government-only', 'source_use': 'for-profit', 'monetization': 'paid'})
    write_json(root / 'var/seafloor/input-scope.json', {
        'version': 1, 'scope': 'government-only', 'isolated_root': str(root.resolve())})


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def new_root(label):
    prefix = OUTPUT_PREFIX
    if prefix is None:
        candidate = REPO.parent
        prefix = (candidate / 'out/discovery' if (candidate / 'ACCEPTANCE-SPEC.json').is_file()
                  else Path(tempfile.gettempdir()))
    prefix = Path(prefix)
    prefix.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='sc176-' + label + '-', dir=prefix))


class OfflineViolation(RuntimeError):
    pass


@contextmanager
def offline_product(root):
    """Guard before imports, bind defaults to synthetic root, restore peer state.

    This is scoped test isolation for the inspected closure, not a hostile-code
    sandbox. No irreversible audit hooks, module fakes or source execution.
    """
    product_before = {key: value for key, value in sys.modules.items()
                      if key == 'skippercast' or key.startswith('skippercast.')}
    namespace_before = {key: dict(value.__dict__) for key, value in product_before.items()}
    old_path = list(sys.path)
    violations = []
    origins = {}

    def deny(*args, **kwargs):
        violations.append('network/model/child effect')
        raise OfflineViolation(violations[-1])

    class NoModels(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in {'ollama', 'openai', 'anthropic', 'litellm'}:
                deny()
            return None

    real_open, real_io_open = builtins.open, io.open

    def guarded_open(opener):
        def opening(file, mode='r', *args, **kwargs):
            if not isinstance(file, int):
                path = Path(file).resolve()
                writing = any(char in mode for char in 'wax+')
                if writing and not path.is_relative_to(root.resolve()):
                    violations.append('write outside synthetic root')
                    raise OfflineViolation(violations[-1])
                if (not writing and path.is_relative_to(REPO)
                        and not path.is_relative_to(root.resolve())
                        and path.suffix not in {'.py', '.pyc', '.so'}):
                    violations.append('product data read outside synthetic root')
                    raise OfflineViolation(violations[-1])
            return opener(file, mode, *args, **kwargs)
        return opening

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                'SKIPPERCAST_ROOT': str(root), 'SKIPPERCAST_SOURCE_SCOPE': 'government-only',
                'SKIPPERCAST_SOURCE_USE': 'for-profit', 'SKIPPERCAST_HTTP_CACHE': '0'}))
            stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
            stack.enter_context(patch.object(sys, 'meta_path', [NoModels(), *sys.meta_path]))
            for module, names in [(socket, ('socket', 'create_connection', 'getaddrinfo')),
                                  (subprocess, ('Popen', 'run', 'call', 'check_call', 'check_output')),
                                  (os, ('system', 'popen', 'fork', 'forkpty', 'posix_spawn', 'posix_spawnp'))]:
                for name in names:
                    if hasattr(module, name):
                        stack.enter_context(patch.object(module, name, deny))
            stack.enter_context(patch.object(builtins, 'open', guarded_open(real_open)))
            stack.enter_context(patch.object(io, 'open', guarded_open(real_io_open)))
            sys.path.insert(0, str(REPO / 'src'))
            paths = importlib.import_module('skippercast.paths')
            stack.enter_context(patch.object(paths, 'repo_root', return_value=root))
            contracts = importlib.import_module('skippercast.platform.contracts')
            stack.enter_context(patch.object(contracts, 'REPO', root))
            stack.enter_context(patch.object(contracts, 'repo_root', return_value=root))
            # Already-imported ordinary CI peers may have bound the original REPO.
            for value in list(vars(contracts).values()):
                if callable(value) and getattr(value, '__module__', None) == contracts.__name__:
                    defaults = getattr(value, '__defaults__', None)
                    if defaults and any(isinstance(item, Path) for item in defaults):
                        stack.enter_context(patch.object(value, '__defaults__', tuple(
                            root if isinstance(item, Path) else item for item in defaults)))
            scope = importlib.import_module('skippercast.seafloor.source_scope')
            rights = importlib.import_module('skippercast.seafloor.rights')
            http = importlib.import_module('skippercast.http')
            stack.enter_context(patch.object(http, 'repo_root', return_value=root))
            stack.enter_context(patch.object(http.Session, 'request', deny))
            stack.enter_context(patch.object(http, 'default_session', deny))
            for name, module in list(sys.modules.items()):
                if name == 'skippercast' or name.startswith('skippercast.'):
                    if name not in product_before or name in {
                            'skippercast.paths', 'skippercast.platform.contracts',
                            'skippercast.seafloor.source_scope', 'skippercast.seafloor.rights',
                            'skippercast.seafloor.io', 'skippercast.http'}:
                        source_file = getattr(module, '__file__', None)
                        if not isinstance(source_file, str):
                            raise RuntimeError('Product module has no source origin: ' + name)
                        origin = Path(source_file).resolve()
                        if not origin.is_relative_to(REPO / 'src'):
                            raise RuntimeError('Product import escaped candidate: ' + name)
                        origins[name] = str(origin)
            yield scope, rights, origins, violations
            if violations:
                raise OfflineViolation('Caught offline violations remain fatal: ' + repr(violations))
    finally:
        sys.path[:] = old_path
        for name in list(sys.modules):
            if (name == 'skippercast' or name.startswith('skippercast.')) and name not in product_before:
                del sys.modules[name]
        for name, module in product_before.items():
            sys.modules[name] = module
            module.__dict__.clear()
            module.__dict__.update(namespace_before[name])
