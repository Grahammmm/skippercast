"""Synthetic fixture and AST loader for the hash-bound supersedes() helper snapshot.

Never imports or runs the installed script. Only the single admitted function
definition is compiled, with PRIOR/expired/sha/Path injected.
"""
import ast
import hashlib
import json
from pathlib import Path

CANDIDATE = Path(__file__).resolve().parent.parent
SNAPSHOT = CANDIDATE / 'sources' / 'supersedes.py'
BASES = json.loads((CANDIDATE / 'BASES.json').read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_helper(source_path=SNAPSHOT, expected_sha=None):
    """Return the verified, single `supersedes` FunctionDef; refuse otherwise."""
    raw = Path(source_path).read_bytes()
    expected = expected_sha or BASES['helper']['snapshot_sha256']
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('helper snapshot digest changed')
    tree = ast.parse(raw.decode('utf-8'))
    if any(not isinstance(n, ast.FunctionDef) for n in tree.body):
        raise ValueError('snapshot has top-level statements other than the helper')
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'supersedes']
    if len(found) != 1:
        raise ValueError('expected exactly one supersedes definition, found %d' % len(found))
    return found[0]


def compile_helper(fn, prior, expired):
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    scope = dict(PRIOR=Path(prior), expired=expired, sha=sha, Path=Path)
    exec(compile(module, 'supersedes-snapshot', 'exec'), scope)
    return scope['supersedes']


class DirectIndexMutant(ast.NodeTransformer):
    """Negative control: rewrite x.get('reviewer_id') into x['reviewer_id'] (the old bug)."""
    count = 0

    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr == 'get' and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'reviewer_id'):
            self.count += 1
            return ast.Subscript(value=f.value, slice=node.args[0], ctx=ast.Load())
        return node


def write_prior(tmp_path, names=('doc',)):
    """Create synthetic PRIOR/metadata/<name>.json files under tmp_path; return PRIOR."""
    prior = Path(tmp_path) / 'prior'
    (prior / 'metadata').mkdir(parents=True)
    for n in names:
        (prior / 'metadata' / (n + '.json')).write_text(json.dumps({'synthetic': n}), encoding='utf-8')
    return prior
