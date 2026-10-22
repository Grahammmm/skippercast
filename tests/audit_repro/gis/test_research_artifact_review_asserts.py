"""Audit repro (2026-10-22): coastal_four128_artifact_review enforces its whole
independent science/resource review with bare ``assert`` statements. Under
``python -O`` (or PYTHONOPTIMIZE without -I/-E) every check vanishes and the
review would issue ``quality_accepted`` with no checks. This test shows the
resource gate accepting nonsense under -O; it asserts the correct behaviour
(refuse) and fails on current code.

Mitigation noted in the report: the governed launcher runs it with ``-I -B``
inside systemd-run, so PYTHONOPTIMIZE is not inherited on that path.
"""
import subprocess
import sys
from pathlib import Path

from tests._support import ROOT


def test_resource_gate_refuses_garbage_even_when_optimized(tmp_path):
    # Same audit probe, executed from a real file without interpreter flags or
    # environment path overrides forbidden by the unattended command guard.
    done = subprocess.run([sys.executable, '-O', str(ROOT / 'tests/audit_repro/artifact_review_probe.py'), str(ROOT), str(tmp_path)], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().startswith('REFUSED'), done.stdout
