"""Run the actual shard plugin against small synthetic cases, never inline code."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import pytest
from scripts.ci_survey import make_plugin

shard, output = int(sys.argv[1]), Path(sys.argv[2])
receipt = {'shard': shard, 'count': 4, 'head': 'a' * 40,
           'collected': [], 'selected': [], 'executed': [], 'exit_code': None}
plugin = make_plugin(pytest, receipt, 4, shard, {})
code = pytest.main([str(Path(__file__).with_name('cases.py')), '-q', '-o', 'addopts='], plugins=[plugin])
receipt['exit_code'] = int(code)
output.write_text(json.dumps(receipt))
raise SystemExit(code)
