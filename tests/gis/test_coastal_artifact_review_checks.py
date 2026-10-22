"""Every baseline science/resource predicate survives optimization unchanged."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests._support import ROOT


def test_all_baseline_predicates_are_explicit_runtime_gates():
    tree = ast.parse((ROOT / 'research/scripts/coastal_four128_artifact_review.py').read_text())
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
    checks = sorted(ast.dump(node.args[0]) for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'require')
    # Independently frozen from baseline 8a1c2c7668e9a3c5157aa865a6b4daf0d9133288
    # before comparing the converted gates. This protects ALL 61 expressions,
    # including MLLW/sign, affine, source/array/mask hashes and deadline checks.
    assert len(checks) == 61
    assert hashlib.sha256('\n'.join(checks).encode()).hexdigest() == 'c6d81fd238e7b083844198459891037138f987fa195ae63819ade3f1f9ee295e'


@pytest.mark.parametrize('optimized', [False, True])
def test_review_gate_positive_and_single_fault_controls(tmp_path, optimized):
    args = [sys.executable]
    if optimized:
        args.append('-O')
    args += [str(Path(__file__).with_name('four128_review_check_probe.py')), str(ROOT), str(tmp_path / 'isolated-home')]
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout)
    assert doc == dict(status='OFFLINE_GATES_VERIFIED', refused_controls=30,
                       optimized=optimized, isolated_defaults=True)
