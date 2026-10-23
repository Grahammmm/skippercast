"""Audit repro (2026-10-22): coastal_four128_artifact_review enforces its whole
independent science/resource review with bare ``assert`` statements. Under
``python -O`` (or PYTHONOPTIMIZE without -I/-E) every check vanishes and the
review would issue ``quality_accepted`` with no checks. This test shows the
resource gate accepting nonsense under -O; it asserts the correct behaviour
(refuse) and fails on current code.

Mitigation noted in the report: the governed launcher runs it with ``-I -B``
inside systemd-run, so PYTHONOPTIMIZE is not inherited on that path.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = '''
import research.scripts.coastal_four128_artifact_review as m
try:
    ok = m.validate_review_resources('wrong-unit', {}, '/nowhere', {}, {}, [0, 1, 2, 3, 4, 5], -1)
except Exception as error:
    print('REFUSED', type(error).__name__)
else:
    print('ACCEPTED', ok)
'''


def test_resource_gate_refuses_garbage_even_when_optimized():
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / 'src'), str(ROOT)]))
    done = subprocess.run([sys.executable, '-O', '-c', PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().startswith('REFUSED'), done.stdout


import os as _audit_os  # noqa: E402

import pytest as _audit_pytest  # noqa: E402

pytestmark = _audit_pytest.mark.skipif(
    _audit_os.environ.get("SKIPPERCAST_AUDIT_CLOUD") != "1",
    reason="audit repro (fails on purpose): set SKIPPERCAST_AUDIT_CLOUD=1",
)
