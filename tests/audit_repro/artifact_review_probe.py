"""File-based form of the independent audit's optimized resource-gate probe."""
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
os.environ['HOME'] = sys.argv[2]
os.environ['SKIPPERCAST_FOUR128_CODE_ROOT'] = str(root)
os.environ['SKIPPERCAST_FOUR128_MISSION_ROOT'] = str(Path(sys.argv[2]) / 'synthetic-mission')
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'src'))
import research.scripts.coastal_four128_artifact_review as m

try:
    ok = m.validate_review_resources('wrong-unit', {}, '/nowhere', {}, {}, [0, 1, 2, 3, 4, 5], -1)
except Exception as error:
    print('REFUSED', type(error).__name__)
else:
    print('ACCEPTED', ok)
