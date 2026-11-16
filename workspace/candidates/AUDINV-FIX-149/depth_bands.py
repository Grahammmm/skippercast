"""Pure, already-qualified normalized-metre samples only; never normalize again."""
import math
import hashlib
import json
from pathlib import Path
from skippercast.coastal import vertical

ROOT = Path(__file__).resolve().parents[3]
SOURCE = 'src/skippercast/coastal/vertical.py'
BASES = json.loads(Path(__file__).with_name('BASES.json').read_text())
if (Path(vertical.__file__).resolve() != ROOT / SOURCE
        or hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest() != BASES['sources'][SOURCE]):
    raise ValueError('vertical source origin/hash mismatch')
LANE_FLOOR_M = vertical.LANE_FLOOR_M


def depth_bands(depths, support, *, producer, qualified, units, sign, storage):
    if (not isinstance(producer, str) or not producer.strip() or qualified is not True
            or (units, sign, storage) != ('m', 'positive_down', 'normalized_depth')):
        raise ValueError('qualified normalized metre producer required')
    if len(depths) != len(support) or any(type(x) is not bool for x in support):
        raise ValueError('support mask mismatch')
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in depths):
        raise ValueError('finite nonnegative normalized depths required')
    valid = [x for x, supported in zip(depths, support) if supported]
    return {'valid_cells_by_band': {
        '0-300ft': sum(x <= LANE_FLOOR_M['M'] for x in valid),
        '300-600ft': sum(LANE_FLOOR_M['M'] < x <= LANE_FLOOR_M['D'] for x in valid),
        '>600ft': sum(x > LANE_FLOOR_M['D'] for x in valid)},
        'deepest_mapped_cell_m': max(valid, default=None),
        'quality': 'unavailable', 'visual_certified': False}
