"""Portable fixture-scoped safety and import isolation for SC15A.

All modules are genuine checkout modules. No product predicate is substituted.
The guards are reversible preflight sentinels, not a hostile-code sandbox.
"""
from contextlib import contextmanager, ExitStack
import builtins
import copy
import hashlib
import importlib
import importlib.abc
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent
KEYS = ('saved_area_continuation_contract', 'saved_area_adoption', 'source_volume_cap_bytes', 'prior_effective_bytes', 'cumulative_limit_bytes')
OUTPUT_BASE = None
OBSERVATIONS = []

def encoded(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()

def load_input(root):
    return json.loads((FIXTURE / 'input.json').read_text().replace('${STATE}', str(root)))

def expected_packet(root):
    return json.loads((FIXTURE / 'baseline.packet.json').read_text().replace('${STATE}', str(root)))

def packet(api, fixture):
    grant = fixture['grant']
    return api.canonical_packet(fixture['template'], grant, **fixture['roles'], code_sha=grant['code_sha'], deps_sha=grant['deps_sha'])

def legacy_constructor(real):
    """Reversible test-local mutation of only the continuation copy behavior."""
    def legacy(template, grant, **kwargs):
        result = real(template, grant, **kwargs)
        if grant.get('saved_area_continuation_contract') is not None:
            for key in KEYS:
                result[key] = grant[key]
        return result
    return legacy

def denied(*args, **kwargs):
    raise RuntimeError('SC15A offline preflight sentinel reached')

class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'ollama', 'litellm', 'hermes_tools'}:
            raise RuntimeError('SC15A model import forbidden')
        return None

@contextmanager
def offline_guards():
    """Install before any product import, with no permanent audit hooks."""
    def checked_open(original):
        def checked(name, *args, **kwargs):
            if isinstance(name, (str, bytes, os.PathLike)):
                text = os.fsdecode(name).lower()
                if text.endswith('.bag') or '/seafloor/cache/' in text:
                    raise RuntimeError('SC15A source access forbidden')
            return original(name, *args, **kwargs)
        return checked
    with ExitStack() as stack:
        for owner, attribute in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                                 (socket, 'create_connection'), (socket, 'getaddrinfo'),
                                 (subprocess, 'Popen'), (os, 'system'), (sqlite3, 'connect')):
            stack.enter_context(patch.object(owner, attribute, denied))
        for attribute in ('fork', 'forkpty', 'posix_spawn', 'posix_spawnp', 'execv', 'execve', 'execvp', 'execvpe'):
            if hasattr(os, attribute):
                stack.enter_context(patch.object(os, attribute, denied))
        for owner, attribute in ((builtins, 'open'), (io, 'open'), (os, 'open')):
            stack.enter_context(patch.object(owner, attribute, checked_open(getattr(owner, attribute))))
        stack.enter_context(patch.object(sys, 'meta_path', [NoModels(), *sys.meta_path]))
        stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
        yield

@contextmanager
def product_context(root):
    """Fresh checkout import, synthetic captured defaults, exact module teardown."""
    before = {n: m for n, m in sys.modules.items() if n == 'skippercast' or n.startswith('skippercast.')}
    environment = dict(os.environ)
    path_before = list(sys.path)
    cwd_before = os.getcwd()
    for name in before:
        sys.modules.pop(name)
    try:
        with offline_guards(), patch.object(sys, 'path', [str(REPO / 'src'), str(REPO), *sys.path]):
            paths = importlib.import_module('skippercast.paths')
            with patch.object(paths, 'repo_root', lambda: root):
                api = importlib.import_module('skippercast.coastal.coordinator.packet_release')
                profiles = importlib.import_module('skippercast.coastal.authenticated_v1.profiles')
                saved = importlib.import_module('skippercast.coastal.coordinator.saved_area')
                policy = importlib.import_module('skippercast.coastal.authenticated_v1.policy')
                contracts = importlib.import_module('skippercast.platform.contracts')
                if contracts.REPO != root:
                    raise RuntimeError('synthetic contracts root was not captured')
                origins = {n: str(Path(m.__file__).resolve()) for n, m in list(sys.modules.items())
                           if n.startswith('skippercast') and getattr(m, '__file__', None)}
                if not all(Path(p).is_relative_to(REPO / 'src') for p in origins.values()):
                    raise RuntimeError('product import escaped staged checkout')
                OBSERVATIONS.append({'root': str(root), 'module_origins': origins, 'contracts_REPO': str(contracts.REPO)})
                yield api, profiles, saved, policy
    finally:
        for name in list(sys.modules):
            if name == 'skippercast' or name.startswith('skippercast.'):
                sys.modules.pop(name)
        sys.modules.update(before)
        if sys.path != path_before or dict(os.environ) != environment or os.getcwd() != cwd_before:
            raise RuntimeError('SC15A fixture leaked ambient state')
