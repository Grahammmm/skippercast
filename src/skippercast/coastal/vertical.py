"""Evidence-bound raw vertical semantics and explicit depth normalization.

Rasterio reads packed samples without applying GDAL scales/offsets. Sample sign
distributions never establish a convention. No operation transforms datums.

Deep-band datum classes (G3, 2026-10-20): EGM2008, instantaneous sea level and
an unstated datum are admitted only in a block that declares depth lane M
(300-600 ft) or D (>600 ft). No uncertainty bound is required. Every admitted
block carries a fixed ``deep_datum`` record marking it not for navigation, and
depth normalization drops its cells shallower than the lane floor. A block with
no ``depth_lane`` is lane S (0-300 ft), which keeps the survey-grade datum set.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

VERSION = 'vertical-v1'
FIELDS = ('sign', 'units', 'datum', 'scale', 'offset', 'scale_offset_applied')
DATUMS = {'MLLW', 'MSL', 'NAVD88', 'ellipsoid:WGS84'}
DEEP_DATUMS = {'EGM2008', 'instantaneous-sea-level', 'unstated'}
LANES = ('S', 'M', 'D')
DEEP_LANES = ('M', 'D')
LANE_FLOOR_M = {'M': 91.44, 'D': 182.88}
DEEP_DATUM_SCHEMA = 'vertical-deep-datum-v1'
DEEP_DATUM_NOTES = {
    'EGM2008': 'Heights relative to the EGM2008 geoid; no offset to a tidal chart datum is applied.',
    'instantaneous-sea-level': 'Soundings relative to the water surface at survey time; tides are not removed.',
    'unstated': 'The source raster states no vertical datum.',
}
_DEEP_ALIASES = {'egm2008': 'EGM2008', 'egm2008 height': 'EGM2008', 'egm2008 geoid': 'EGM2008',
                 'egm08': 'EGM2008', 'instantaneous sea level': 'instantaneous-sea-level',
                 'instantaneous-sea-level': 'instantaneous-sea-level', 'unstated': 'unstated',
                 'not stated': 'unstated', 'not-stated': 'unstated'}


class VerticalHold(ValueError):
    def __init__(self, holds):
        self.holds = list(dict.fromkeys(holds))
        super().__init__('; '.join(self.holds))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _number(value):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value))


def _safe_number(value):
    return value if value is None or _number(value) else str(value)


def _unit(value):
    return {'m': 'm', 'metre': 'm', 'metres': 'm', 'meter': 'm', 'meters': 'm',
            'ft': 'ft', 'foot': 'ft', 'feet': 'ft', 'international foot': 'ft'}.get(str(value).lower())


def _sign(value):
    return {'up': 'positive_up', 'down': 'positive_down', 'positive_up': 'positive_up',
            'positive_down': 'positive_down'}.get(value)


def _datum(crs):
    name = (crs.datum.name + ' ' + crs.name).lower()
    if 'lower low water' in name or 'mllw' in name:
        return 'MLLW'
    if 'navd88' in name or 'north american vertical datum 1988' in name:
        return 'NAVD88'
    if 'mean sea level' in name or name.startswith('msl '):
        return 'MSL'
    if 'egm2008' in name or 'egm08' in name:
        return 'EGM2008'
    return None


def _datum_tag(value):
    """Canonical deep-class names; every other tag value stays as written."""
    return _DEEP_ALIASES.get(str(value).strip().lower(), value)


def deep_datum_record(datum, lane):
    """The fixed G3 label for an admitted deep-band datum; reviews cannot alter it."""
    return {'schema': DEEP_DATUM_SCHEMA, 'datum_class': datum, 'depth_lane': lane,
            'lane_floor_m': LANE_FLOOR_M[lane], 'uncertainty_bound_m': None,
            'uncertainty_bound_required': False, 'uncertainty_status': 'datum_offset_unbounded',
            'note': DEEP_DATUM_NOTES[datum], 'navigation': 'not-for-navigation',
            'chart_datum': False, 'datum_transform': False,
            'policy': 'G3 2026-10-20: lanes M and D admit EGM2008, instantaneous-sea-level and '
                      'unstated datums without an uncertainty bound; outputs are not for navigation.'}


def is_deep(block):
    """True when the block uses a deep-band datum class in lane M or D."""
    return _deep_class(block) and block.get('depth_lane') in DEEP_LANES


def _deep_class(block):
    datum = block.get('datum') if isinstance(block, dict) else None
    return isinstance(datum, str) and datum in DEEP_DATUMS


def _statement_holds(block):
    # Key presence, not truthiness: a present null or empty statement is malformed.
    if 'datum_statement' not in block:
        return []
    statement = block['datum_statement']
    if (block.get('datum') not in ('EGM2008', 'instantaneous-sea-level')
            or not isinstance(statement, dict)
            or set(statement) != {'kind', 'sha256', 'locator'}
            or statement.get('kind') != 'source_metadata'
            or not re.fullmatch('[a-f0-9]{64}', str(statement.get('sha256')))
            or not isinstance(statement.get('locator'), str) or not statement['locator'].strip()):
        return ['vertical_datum_statement_invalid']
    return []


def from_raster(dataset, *, source_sha256=None, bag_metadata=None):
    """Observe the actual first-band metadata, loading GIS dependencies lazily.

    BAG's elevation array is positive up even with a depth-coordinate CRS.
    This format-specific distinction requires matching embedded XML and GDAL.
    """
    from pyproj import CRS
    tags, band_tags = dataset.tags(), dataset.tags(1)
    relevant = ('vertical_sign', 'z_positive', 'positive', 'vertical_datum', 'z_units',
                'scale_offset_applied', 'vertical_contract', 'datum_realization')
    header = {'driver': dataset.driver, 'crs_wkt': dataset.crs.to_wkt() if dataset.crs else None,
              'dtype': dataset.dtypes[0], 'nodata': _safe_number(dataset.nodatavals[0]),
              'units': dataset.units[0], 'scale': _safe_number(dataset.scales[0]),
              'offset': _safe_number(dataset.offsets[0]), 'description': dataset.descriptions[0],
              'tags': {key: tags[key] for key in relevant if key in tags},
              'band_tags': {key: band_tags[key] for key in relevant if key in band_tags}}
    conflicts = []
    hints = {key: [] for key in ('sign', 'units', 'datum', 'scale_offset_applied', 'datum_realization')}
    if dataset.units[0] is not None:
        hints['units'].append(_unit(dataset.units[0]) or 'unsupported:' + str(dataset.units[0]))
    for context in (tags, band_tags):
        for key in ('vertical_sign', 'z_positive', 'positive'):
            if key in context:
                hints['sign'].append(_sign(context[key]) or 'unsupported:' + context[key])
        if 'z_units' in context:
            hints['units'].append(_unit(context['z_units']) or 'unsupported:' + context['z_units'])
        if 'datum_realization' in context:
            hints['datum_realization'].append(context['datum_realization'])
        if 'vertical_datum' in context:
            hints['datum'].append(_datum_tag(context['vertical_datum']))
        if 'scale_offset_applied' in context:
            value = context['scale_offset_applied'].lower()
            hints['scale_offset_applied'].append({'true': True, 'false': False}.get(value, value))
    vertical = None
    if dataset.crs:
        crs = CRS.from_user_input(dataset.crs)
        parts = crs.sub_crs_list if crs.is_compound else [crs]
        verticals = [part for part in parts if part.is_vertical]
        if len(verticals) > 1:
            conflicts.append('vertical_crs_ambiguous')
        if len(verticals) == 1:
            vertical = verticals[0]
            if len(vertical.axis_info) != 1:
                conflicts.append('vertical_crs_axis_unsupported')
            else:
                axis = vertical.axis_info[0]
                unit = _unit(axis.unit_name)
                hints['units'].append(unit or 'unsupported:' + axis.unit_name)
                factor = {'m': 1, 'ft': .3048}.get(unit)
                if factor is None or not math.isclose(axis.unit_conversion_factor, factor,
                                                       rel_tol=0, abs_tol=1e-12):
                    conflicts.append('vertical_crs_unit_unsupported')
                if dataset.driver != 'BAG':
                    hints['sign'].append(_sign(axis.direction) or 'unsupported:' + axis.direction)
                hints['datum'].append(_datum(vertical) or 'unknown')
    if dataset.driver == 'BAG':
        if not bag_metadata or vertical is None:
            conflicts.append('bag_vertical_metadata_required')
        else:
            try:
                xml_crs = CRS.from_wkt(bag_metadata['vertical_wkt'])
                xml_axis, gdal_axis = xml_crs.axis_info[0], vertical.axis_info[0]
                if (not xml_crs.equals(vertical, ignore_axis_order=False)
                        or xml_axis.direction != gdal_axis.direction
                        or _unit(xml_axis.unit_name) != 'm'
                        or xml_axis.unit_conversion_factor != 1
                        or bag_metadata['vertical_datum'] != _datum(vertical)):
                    conflicts.append('bag_xml_gdal_vertical_conflict')
                if xml_axis.direction not in {'up', 'down'}:
                    conflicts.append('bag_vertical_axis_unsupported')
                if (dataset.descriptions[0] != 'elevation'
                        or bag_metadata.get('elevation_convention', {}).get('sign') != 'positive_up'
                        or bag_metadata.get('elevation_convention', {}).get('units') != 'm'
                        or bag_metadata.get('elevation_convention', {}).get('array') != 'BAG_root/elevation'):
                    conflicts.append('bag_elevation_convention_unconfirmed')
                header['bag_metadata_sha256'] = bag_metadata['metadata_sha256']
                header['bag_vertical_wkt'] = bag_metadata['vertical_wkt']
                header['bag_format_relation'] = deepcopy(bag_metadata.get('elevation_convention'))
                header['bag_format_relation_sha256'] = digest(header['bag_format_relation'])
                hints['sign'].append('positive_up')
                hints['units'].append('m')
            except (KeyError, ValueError, IndexError):
                conflicts.append('bag_vertical_metadata_invalid')
    facts = {}
    for key, values in hints.items():
        if len({json.dumps(value) for value in values}) > 1:
            conflicts.append('vertical_' + key + '_conflict')
        facts[key] = values[0] if values else (False if key == 'scale_offset_applied' else 'unknown' if key == 'datum_realization' else None)
    facts.update(scale=_safe_number(dataset.scales[0]), offset=_safe_number(dataset.offsets[0]))
    return {'schema': 'vertical-observation-v1', 'source_sha256': source_sha256,
            'header': header, 'header_sha256': digest(header), 'facts': facts,
            'conflicts': sorted(set(conflicts)), 'sign_hint': facts['sign'],
            'units': facts['units'], 'datum': facts['datum'], 'scale': facts['scale'],
            'offset': facts['offset'], 'scale_offset_applied': facts['scale_offset_applied']}


def evidence_from_observation(observed):
    """Consumers recompute this evidence from the actual raster."""
    return {'kind': 'raster_header', 'source_sha256': observed['source_sha256'],
            'header_sha256': observed['header_sha256'], 'facts': deepcopy(observed['facts'])}


def validate(block):
    """Validate semantic structure without claiming to inspect a file."""
    holds = []
    if not isinstance(block, dict) or block.get('schema', VERSION) != VERSION:
        return ['vertical_contract_missing_or_unsupported']
    for key, allowed in (('sign', {'positive_up', 'positive_down'}), ('units', {'m', 'ft'}),
                         ('datum', DATUMS | DEEP_DATUMS)):
        value = block.get(key)
        if not isinstance(value, str) or value not in allowed:
            holds.append('vertical_' + key + ('_unknown' if value in (None, 'unknown', '') else '_unsupported'))
    if 'depth_lane' in block and block['depth_lane'] not in LANES:
        holds.append('vertical_depth_lane_unsupported')
    elif _deep_class(block):
        lane = block.get('depth_lane', 'S')
        if lane not in DEEP_LANES:
            holds.append('vertical_datum_deep_lane_only')
        elif block.get('deep_datum') != deep_datum_record(block['datum'], lane):
            holds.append('vertical_deep_datum_metadata_invalid')
        holds.extend(_statement_holds(block))
    elif 'deep_datum' in block or 'datum_statement' in block:
        holds.append('vertical_deep_datum_metadata_invalid')
    if not _number(block.get('scale')) or block.get('scale', 0) <= 0:
        holds.append('vertical_scale_unsupported')
    if not _number(block.get('offset')):
        holds.append('vertical_offset_invalid')
    if not isinstance(block.get('scale_offset_applied'), bool):
        holds.append('vertical_scale_offset_applied_unknown')
    if block.get('conflicts'):
        holds.append('vertical_conflict_unresolved')
    items = block.get('evidence')
    if not isinstance(items, list) or not items or not any(isinstance(item, dict)
            and item.get('kind') != 'operator_declaration' for item in items):
        holds.append('vertical_evidence_declaration_only')
    if isinstance(items, list):
        verified = []
        for item in items:
            if not isinstance(item, dict) or item.get('kind') != 'raster_header':
                continue
            if (not re.fullmatch('[a-f0-9]{64}', str(item.get('source_sha256')))
                    or not re.fullmatch('[a-f0-9]{64}', str(item.get('header_sha256')))
                    or not isinstance(item.get('facts'), dict)):
                holds.append('vertical_evidence_invalid')
            else:
                verified.append(item)
        if not verified:
            holds.append('vertical_header_evidence_required')
    return sorted(set(holds))


def resolve(declared, observed, evidence=None):
    """A review cannot remove unknown/conflict holds; evidence must match facts."""
    if not isinstance(observed, dict) or not isinstance(observed.get('facts'), dict):
        return {'block': None, 'holds': ['vertical_observation_invalid']}
    if declared is not None and not isinstance(declared, dict):
        return {'block': None, 'holds': ['vertical_contract_missing_or_unsupported']}
    facts = observed.get('facts', {})
    block = deepcopy(declared) if declared is not None else dict(facts)
    block.setdefault('schema', VERSION)
    block.setdefault('datum_realization', 'unknown')
    block.setdefault('conflicts', [])
    if is_deep(block):
        block.setdefault('deep_datum', deep_datum_record(block['datum'], block['depth_lane']))
    items = deepcopy(evidence if evidence is not None else block.get('evidence', []))
    block['evidence'] = items
    holds = validate(block) + list(observed.get('conflicts', []))
    if not isinstance(items, list):
        return {'block': None, 'holds': sorted(set(holds + ['vertical_evidence_invalid']))}
    if observed.get('header_sha256') != digest(observed.get('header', {})):
        holds.append('vertical_observation_header_hash_mismatch')
    if not re.fullmatch('[a-f0-9]{64}', str(observed.get('source_sha256'))):
        holds.append('vertical_source_hash_required')
    for key in FIELDS:
        if key == 'datum' and facts.get(key) is None and is_deep(block):
            # G3: a raster header that states no datum is the 'unstated' class.
            # EGM2008 / instantaneous sea level then need the source's own statement.
            if block['datum'] != 'unstated' and block.get('datum_statement') is None:
                holds.append('vertical_datum_statement_required')
        elif facts.get(key) is None or facts.get(key) == 'unknown':
            holds.append('vertical_' + key + '_unobserved')
        elif block.get(key) != facts[key]:
            holds.append('vertical_' + key + '_conflict')
    if block.get('datum_realization') != facts.get('datum_realization', 'unknown'):
        holds.append('vertical_datum_realization_conflict')
    verified = False
    for item in items:
        if not isinstance(item, dict) or item.get('kind') != 'raster_header':
            continue
        if (item.get('source_sha256') != observed.get('source_sha256')
                or item.get('header_sha256') != observed.get('header_sha256')
                or item.get('facts') != facts):
            holds.append('vertical_evidence_mismatch')
        else:
            verified = True
    if not verified:
        holds.append('vertical_header_evidence_required')
    holds = sorted(set(holds))
    return {'block': None if holds else block, 'holds': holds}


def require_resolved(declared, observed, evidence=None):
    result = resolve(declared, observed, evidence)
    if result['holds']:
        raise VerticalHold(result['holds'])
    return result['block']


def to_depth(values, block, *, valid=None, nodata=None):
    """Normalize depth while combining input, finite, support, and explicit nodata masks."""
    import numpy as np
    holds = validate(block)
    if holds:
        raise VerticalHold(holds)
    samples = np.ma.asarray(values, dtype='float64')
    raw = np.asarray(samples.filled(np.nan))
    mask = ~np.ma.getmaskarray(samples) & np.isfinite(raw)
    if valid is not None:
        support = np.ma.asarray(valid, dtype=bool)
        if support.shape != mask.shape:
            raise ValueError('vertical_support_mask_shape_mismatch')
        mask &= ~np.ma.getmaskarray(support) & np.asarray(support.filled(False), dtype=bool)
    if nodata is not None:
        if isinstance(nodata, (bool, np.bool_)) or not np.isscalar(nodata):
            raise ValueError('vertical_nodata_scalar_required')
        nodata_value = float(nodata)
        if math.isfinite(nodata_value):
            mask &= raw != nodata_value
    if not block['scale_offset_applied']:
        raw = raw * block['scale'] + block['offset']
    if block['units'] == 'ft':
        raw = raw * .3048
    if block['sign'] == 'positive_up':
        raw = -raw
    mask &= np.isfinite(raw)
    if is_deep(block):
        # Deep-band datum classes never yield lane S (0-300 ft) depths.
        mask &= np.where(mask, raw, -np.inf) >= LANE_FLOOR_M[block['depth_lane']]
    return np.where(mask, raw, np.nan)


def normalized(block):
    """Describe transformed storage separately from raw source semantics."""
    holds = validate(block)
    if holds:
        raise VerticalHold(holds)
    result = {'schema': VERSION, 'sign': 'positive_down', 'units': 'm', 'datum': block['datum'],
              'datum_realization': block.get('datum_realization', 'unknown'), 'scale': 1.0,
              'offset': 0.0, 'scale_offset_applied': True, 'evidence': deepcopy(block['evidence']),
              'conflicts': [], 'storage': 'normalized_depth',
              'lineage': {'source_vertical': deepcopy(block), 'source_vertical_sha256': digest(block),
                          'operations': ['apply_unapplied_scale_offset', 'convert_units_to_m',
                                         'convert_sign_to_positive_down'], 'datum_transform': False}}
    if is_deep(block):
        result.update(depth_lane=block['depth_lane'], deep_datum=deepcopy(block['deep_datum']))
        if 'datum_statement' in block:
            result['datum_statement'] = deepcopy(block['datum_statement'])
        result['lineage']['operations'].append('drop_cells_shallower_than_lane_floor')
    return result


def normalized_from_raster(dataset, *, source_sha256):
    """Check normalized tags against the physical header before another read."""
    try:
        block = json.loads(dataset.tags()['vertical_contract'])
        lineage = block['lineage']
    except (KeyError, ValueError, TypeError) as exc:
        raise VerticalHold(['normalized_vertical_contract_missing']) from exc
    if (block.get('storage') != 'normalized_depth' or block.get('sign') != 'positive_down'
            or block.get('units') != 'm' or block.get('scale') != 1 or block.get('offset') != 0
            or block.get('scale_offset_applied') is not True
            or lineage.get('datum_transform') is not False
            or digest(lineage.get('source_vertical')) != lineage.get('source_vertical_sha256')
            or validate(lineage.get('source_vertical'))):
        raise VerticalHold(['normalized_vertical_lineage_invalid'])
    observed = from_raster(dataset, source_sha256=source_sha256)
    # Upstream raw evidence and this actual normalized storage header differ.
    return require_resolved(block, observed, [evidence_from_observation(observed)])
