"""Display measured rough patches without inventing an unsupported terrain rank.

These are existing native-mask candidate outlines, not buffered guesses or
new survey coverage. The larger grading neighborhoods remain unchanged.
"""
import math

from skippercast.platform.contracts import REPO, read_json

PROFILE = 'measured-rough-search-v1'


def assessment(properties, rules=None):
    rules = rules or read_json(REPO/'catalog/habitat-rules.json')
    p = properties
    support = p.get('metric_support_fraction')
    lo, hi = p.get('depth_min_ft'), p.get('depth_max_ft')
    fit = p.get('fit')
    if (p.get('terrain') != 'unknown'
            or p.get('rule_version') != rules['rule_version']
            or not isinstance(support, (int, float)) or isinstance(support, bool)
            or not math.isfinite(support)
            or not 0 <= support < rules['metric_minimum_support_fraction']
            or not isinstance(fit, dict) or not fit
            or not set(fit) <= set(rules['species'])
            or any(value != 'unknown' for value in fit.values())
            or not isinstance(p.get('source_ids'), list) or not p['source_ids']
            or not all(isinstance(s, str) and s for s in p['source_ids'])
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in (lo, hi))
            or not 25 <= lo <= hi <= 300 + 1e-6):
        return None
    targets = sorted(key for key in fit if
        lo * .3048 >= rules['species'][key]['planning_depth_m'][0] - 1e-6
        and hi * .3048 <= rules['species'][key]['planning_depth_m'][1] + 1e-6)
    if not targets:
        return None
    return {'profile': PROFILE, 'target_species': targets,
            'confidence': 'limited',
            'basis': 'Measured rough-bottom patch; surrounding support is insufficient for a terrain grade.',
            'precision': 'Area to search with a sounder; no individual rock pile or precise fishing position established.'}


def published_contract(properties):
    """Search-area admission cannot substitute for rights or spatial screening."""
    p = properties
    expected = assessment(p)
    return bool(expected and p.get('search_area') == expected
        and p.get('detail_level') == 'search-area'
        and p.get('tier') == 1 and p.get('status') == 'search-area'
        and p.get('exportable') is False
        and p.get('screen', {}).get('status') == 'pass'
        and not p.get('hold_reasons'))
