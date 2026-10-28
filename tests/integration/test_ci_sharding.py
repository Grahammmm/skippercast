"""Exercise pytest's real collection/parameterization/setup-skip hook sequence."""
import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

from scripts.ci_survey import verify
from tests._support import FIXTURES


def test_actual_plugin_partitions_and_runs_every_case_once():
    with TemporaryDirectory() as directory:
        receipts = []
        for shard in range(1, 5):
            path = Path(directory) / f'{shard}.json'
            result = subprocess.run([sys.executable, str(FIXTURES / 'ci_shards/runner.py'), str(shard), str(path)],
                                    capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr
            receipts.append(json.loads(path.read_text()))
        assert verify(receipts, 4, 'a' * 40) == 8
        assert any('test_fixture_skip' in node for row in receipts for node in row['executed'])
        failed_shard = next(row['shard'] for row in receipts if any('test_class_method' in node for node in row['selected']))
        path = Path(directory) / 'failed.json'
        result = subprocess.run([sys.executable, str(FIXTURES / 'ci_shards/runner.py'), str(failed_shard), str(path)],
                                env={**os.environ, 'CI_SHARD_FIXTURE_FAIL': '1'}, capture_output=True, text=True, timeout=30)
        assert result.returncode == 1, result.stdout + result.stderr
        assert json.loads(path.read_text())['exit_code'] == 1
